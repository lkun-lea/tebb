"""One-device LAN enrollment. Only the desktop RPC can approve an application."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import segno
import uvicorn
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Header, HTTPException
from starlette.responses import Response
from desk_companion.local_api.mobile_discovery import Discovery, proof, sealed_offer
from pydantic import BaseModel, Field


class Application(BaseModel):
    token: str = Field(max_length=128)
    name: str = Field(min_length=1, max_length=100)
    public_key: str = Field(max_length=256)
    signature: str = Field(max_length=256)


class QuestionReference(BaseModel):
    conversation: str = Field(min_length=1, max_length=180)
    run: str = Field(min_length=1, max_length=180)
    version: str = Field(min_length=1, max_length=128)


class QuestionDefer(QuestionReference):
    until: int


class TaskAnswer(QuestionReference):
    text: str = Field(min_length=1, max_length=4000)


def lan_addresses():
    candidates = []
    for name, entries in psutil.net_if_addrs().items():
        for entry in entries:
            if entry.family == socket.AF_INET and any(ipaddress.ip_address(entry.address) in net for net in PRIVATE):
                candidates.append((not any(word in name.lower() for word in ('wi-fi', 'wlan', '无线')), entry.address))
    return [addr for _, addr in sorted(candidates)]


PRIVATE = tuple(map(ipaddress.ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))


def write_identity(path, address):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'tebb pairing')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), False)
            .sign(key, hashes.SHA256()))
    (path/'key').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    (path/'cert').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert.fingerprint(hashes.SHA256()).hex()


class MobilePairing:
    def __init__(self, directory, account, active, collaboration=None, lease=None, relay_headers=None):
        self.directory = Path(directory)
        self.account = account
        self.active = active
        self.relay_headers = relay_headers
        self.lease = lease
        self.cached_key = None
        self.expires = 0
        self.discovery = Discovery(self._offer)
        self.collaboration = collaboration
        self.token = None
        self.lock = threading.RLock()
        self.state = 'idle'
        self.server = None
        self.deadline = 0
        self.record = self.directory/'android-device.json'

    def _key(self):
        if self.account == 'local' or not self.active() or self.lease is None:
            raise ValueError('请先登录 tebb 账号并切换到账号空间。')
        if time.time() >= self.expires:
            self.cached_key, self.expires = self.lease()
        if self.expires <= time.time() or len(self.cached_key) != 32:
            raise ValueError('账号凭据已过期。')
        return self.cached_key

    def _offer(self, nonce, signature, address=''):
        with self.lock:
            # 定时器预取短期凭据；陌生广播不能触发云端请求或生成二维码。
            if time.time() >= self.expires or not self.cached_key or not hmac.compare_digest(
                    signature, proof(self.cached_key, 'discover:' + nonce)):
                return None
            if not self.active() or self.record.exists():
                return None
            self._expire()
            if self.state not in ('waiting', 'pending'):
                self._start(address)
            if self.state == 'waiting' and (not address or self.address == address):
                return sealed_offer(self.cached_key, nonce, dict(self.invite, computer=socket.gethostname()))
            return None

    def _expire(self):
        if self.state in ('waiting', 'pending') and (time.monotonic() >= self.deadline or not self.active()):
            self.state = 'expired'

    def desktop(self, action='status', request_id='', address=''):
        with self.lock:
            self._expire()
            if action == 'pending':
                if self.state == 'pending':
                    return dict(state=self.state, id=self.ident, name=self.name, code=self.code)
                return dict(state='idle')
            if action == 'status' and self.record.exists() and self.server is None:
                self.restore()
            if action == 'start':
                self._start(address)
            elif action in ('approve', 'approve_relay', 'reject'):
                if self.state != 'pending' or request_id != self.ident:
                    raise ValueError('配对申请已变化，请刷新。')
                if action != 'reject':
                    self._key()
                    self.directory.mkdir(parents=True, exist_ok=True)
                    tmp = self.record.with_suffix('.tmp')
                    tmp.write_text(json.dumps(dict(protocol=2, account=self.account, public_key=self.key, name=self.name,
                                                   id=self.ident, computer=socket.gethostname(),
                                                   relay_key=base64.b64encode(hashlib.sha256(('tebb-relay-v1:' + self.access).encode()).digest()).decode() if action == 'approve_relay' else '',
                                                   host=self.address, port=self.server.config.port,
                                                   credential=hashlib.sha256(self.access.encode()).hexdigest())), encoding='utf-8')
                    os.replace(tmp, self.record)
                self.state = 'rejected' if action == 'reject' else 'approved'
            elif action in ('share_history', 'unshare_history'):
                self._key()
                if not self.record.exists():
                    raise ValueError('请先配对手机并启用加密中转')
                record = json.loads(self.record.read_text(encoding='utf-8'))
                if record.get('account') != self.account or not record.get('relay_key'):
                    raise ValueError('请重新配对并选择加密中转')
                chats = set(record.get('shared_chats', []))
                if action == 'share_history':
                    if not self.collaboration().shared_history([request_id]):
                        raise ValueError('会话已移除')
                    chats.add(request_id)
                    if len(chats) > 4:
                        raise ValueError('最多同时共享四个会话')
                else:
                    chats.discard(request_id)
                record['shared_chats'] = sorted(chats)
                tmp = self.record.with_suffix('.tmp')
                tmp.write_text(json.dumps(record), encoding='utf-8')
                os.replace(tmp, self.record)
            elif action == 'forget':
                self.record.unlink(missing_ok=True)
                self.state = 'idle'
                self.close()
            elif action != 'status':
                raise ValueError('未知配对操作')
            view = dict(state=self.state, addresses=lan_addresses(), account_ready=self.account != 'local' and self.active())
            if self.record.exists():
                record = json.loads(self.record.read_text(encoding='utf-8'))
                view['paired'] = record['name']
                view['shared_chats'] = record.get('shared_chats', [])
                view['legacy'] = record.get('protocol') != 2
            if self.state == 'waiting':
                view['qr'] = self.qr
            if self.state in ('pending', 'approved', 'rejected'):
                view.update(id=self.ident, name=self.name, code=self.code)
            return view

    def close(self):
        if self.server:
            self.server.should_exit = True
            self.server = None

    def _start(self, address):
        self._key()
        addresses = lan_addresses()
        if self.record.exists():
            raise ValueError('请先解除已有手机配对。')
        if not self.active() or not addresses or (address and address not in addresses):
            raise ValueError('请检查当前账号和局域网地址。')
        address = address or addresses[0]
        self.close()
        self.state = 'idle'
        token = secrets.token_urlsafe(32)
        self.directory.mkdir(parents=True, exist_ok=True)
        pin = write_identity(self.directory, address)
        self.pin = pin
        self.token = token
        self.address = address
        self.access = secrets.token_urlsafe(48)
        self.deadline = time.monotonic() + 180
        port = self._listen(address, 0, token)
        self.state = 'waiting'
        self.invite = dict(v=2, host=address, port=port, pin=pin, token=token)
        data = json.dumps(self.invite, separators=(',', ':'))
        self.qr = segno.make_qr(data).png_data_uri(scale=5)
        timer = threading.Timer(210, self._close_unused, args=(token,))
        timer.daemon = True
        timer.start()

    def _close_unused(self, token):
        with self.lock:
            if self.token == token and self.state != 'approved':
                self.close()

    def relay_tick(self):
        if self.relay_headers and self.record.exists() and self.active():
            from desk_companion.local_api.paired_workspace import exchange
            exchange(self, self.relay_headers)

    def restore(self):
        """Rebind the approved endpoint after a backend restart, on its original LAN address only."""
        with self.lock:
            if not self.active():
                self.discovery.close()
                self.expires = 0
                return
            self._key()
            if not self.record.exists():
                self.discovery.start()
                return
            if self.server:
                return
            record = json.loads(self.record.read_text(encoding='utf-8'))
            if record.get('protocol') != 2 or record.get('account') != self.account or record.get('host') not in lan_addresses():
                return
            try:
                self.pin = x509.load_pem_x509_certificate((self.directory/'cert').read_bytes()).fingerprint(hashes.SHA256()).hex()
                self._listen(record['host'], record['port'], None)
            except OSError:
                return
            self.state = 'linked'

    def _listen(self, address, port, generation):
        sock = socket.socket()
        try:
            sock.bind((address, port))
            sock.listen(16)
            port = sock.getsockname()[1]
            config = uvicorn.Config(self._api(generation), host=address, port=port,
                                    ssl_certfile=str(self.directory/'cert'), ssl_keyfile=str(self.directory/'key'),
                                    access_log=False, log_level='error', lifespan='off')
            config.load()
            self.server = uvicorn.Server(config)
            threading.Thread(target=self.server.run, kwargs={'sockets': [sock]}, daemon=True).start()
            return port
        except Exception:
            sock.close()
            raise

    def _api(self, generation):
        api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @api.middleware('http')
        async def account_guard(request, call_next):
            header = request.headers.get('x-tebb-account', '')
            path = request.url.path
            with self.lock:
                if (len(header) != 64 or self.cached_key is None or time.time() >= self.expires
                        or not self.active()):
                    return Response(status_code=403)
                expected = proof(self.cached_key, self.pin + ':' + path)
                if not hmac.compare_digest(header.encode(), expected.encode()):
                    return Response(status_code=403)
            return await call_next(request)

        @api.post('/mobile/v1/pairings')
        def apply(body: Application):
            with self.lock:
                self._expire()
                if generation is None or generation != self.token or not secrets.compare_digest(generation, body.token):
                    raise HTTPException(403)
                try:
                    key = serialization.load_der_public_key(base64.b64decode(body.public_key, validate=True))
                    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
                        raise ValueError()
                    challenge = ('tebb-pair-v1:' + generation).encode()
                    key.verify(base64.b64decode(body.signature, validate=True), challenge, ec.ECDSA(hashes.SHA256()))
                except (ValueError, TypeError, InvalidSignature):
                    raise HTTPException(403)
                if not self.active():
                    raise HTTPException(403)
                if self.state == 'waiting':
                    self.key, self.name = body.public_key, body.name
                    self.ident, self.ticket = secrets.token_hex(16), secrets.token_urlsafe(32)
                    self.code = f'{secrets.randbelow(1000000):06d}'
                    self.state = 'pending'
                elif self.state != 'pending' or self.key != body.public_key:
                    raise HTTPException(409)
                return dict(id=self.ident, ticket=self.ticket, code=self.code, computer=socket.gethostname())

        @api.get('/mobile/v1/pairings/{ident}')
        def status(ident: str, authorization: str = Header(default='')):
            with self.lock:
                self._expire()
                if (generation is None or generation != self.token or not self.active() or ident != getattr(self, 'ident', None)
                        or not hmac.compare_digest(authorization, 'Bearer ' + self.ticket)):
                    raise HTTPException(403)
                return dict(state=self.state, **({'access': self.access, 'relay': bool(json.loads(self.record.read_text(encoding='utf-8')).get('relay_key'))}
                                                 if self.state == 'approved' else {}))

        def authorize(header):
            if not self.active() or not self.record.exists() or not header.startswith('Bearer '):
                raise HTTPException(403)
            record = json.loads(self.record.read_text(encoding='utf-8'))
            digest = hashlib.sha256(header[7:].encode()).hexdigest()
            if record.get('protocol') != 2 or record.get('account') != self.account or not hmac.compare_digest(digest, record.get('credential', '')):
                raise HTTPException(403)
            return record['id']

        @api.get('/mobile/v1/questions')
        def questions(authorization: str = Header(default='')):
            with self.lock:
                authorize(authorization)
                return dict(questions=self.collaboration().mobile_questions())

        @api.post('/mobile/v1/defer')
        def defer(body: QuestionDefer, authorization: str = Header(default='')):
            with self.lock:
                authorize(authorization)
                try:
                    return self.collaboration().defer_question(body.conversation, body.run, body.version, body.until)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc

        @api.post('/mobile/v1/answers')
        def submit(body: TaskAnswer, authorization: str = Header(default='')):
            with self.lock:
                device = authorize(authorization)
                # Identical retries replay the durable desktop receipt, even after the run has resumed.
                fields = [device, body.conversation, body.run, body.version, body.text]
                ident = hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()
                action = dict(type='send', conversation=body.conversation, run=body.run, text=body.text,
                              question_version=body.version, request_id='mobile-'+ident)
                try:
                    self.collaboration().action(action)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
                return dict(run=body.run, version=body.version, accepted=True)
        return api
