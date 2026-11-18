"""Local TLS/proxy servers verify Node obeys the product's model-only policy."""
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import http.client
from http.server import BaseHTTPRequestHandler
import ipaddress
import os
from pathlib import Path
import select
import socket
import socketserver
import ssl
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

from atlas.llm import IncompleteResponseError
from tests.test_pi_inference import PiInferenceFixture


def relay(left, right):
    try:
        while True:
            ready, _, _ = select.select([left, right], [], [], 3)
            if not ready: return
            for source in ready:
                data = source.recv(65536)
                if not data: return
                (right if source is left else left).sendall(data)
    except OSError:
        pass


class PiNetworkTests(PiInferenceFixture):
    def start_proxy(self, handler):
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        server = Server(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_environment_custom_auth_and_direct_proxy_isolation(self):
        seen = []
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                seen.append(self.headers.get('Proxy-Authorization'))
                target = urlsplit(self.path)
                body = self.rfile.read(int(self.headers['Content-Length']))
                with closing(http.client.HTTPConnection(target.hostname, target.port, timeout=5)) as upstream:
                    upstream.request('POST', target.path, body, {'Content-Type':'application/json'})
                    response = upstream.getresponse()
                    self.send_response(response.status); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                    self.wfile.write(response.read())
        proxy = self.start_proxy(Proxy)
        address = f'http://127.0.0.1:{proxy}'
        with patch.dict(os.environ, http_proxy=address, https_proxy=address, no_proxy='', NO_PROXY=''):
            with patch('desk_companion.models.model_network.load', return_value=dict(mode='system')), self.llm() as llm:
                self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
            with patch('desk_companion.models.model_network.load', return_value=dict(mode='direct')), self.llm() as llm:
                self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
        with patch('desk_companion.models.model_network.load', return_value=dict(mode='custom',proxy_url=address,username='fixture',password='password')), self.llm() as llm:
            self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
        self.assertEqual(seen, [None, 'Basic '+base64.b64encode(b'fixture:password').decode()])
        self.assertEqual(len(self.requests), 3)

    def test_authenticated_socks5h_resolves_hostname_at_proxy(self):
        targets, credentials = [], []
        provider_port = self.http.server_port
        class Socks(socketserver.StreamRequestHandler):
            def handle(self):
                read = self.rfile.read
                version, methods = read(2); read(methods)
                self.connection.sendall(b'\x05\x02')
                version, size = read(2); username = read(size); password = read(read(1)[0])
                credentials.append((username,password)); self.connection.sendall(b'\x01\x00')
                version, command, reserved, kind = read(4)
                host = read(read(1)[0]).decode() if kind == 3 else socket.inet_ntoa(read(4))
                port = int.from_bytes(read(2),'big'); targets.append((host,port))
                with socket.create_connection(('127.0.0.1',provider_port),timeout=5) as upstream:
                    self.connection.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                    relay(self.connection, upstream)
        proxy = self.start_proxy(Socks)
        for scheme in ('socks5','socks5h'):
            with self.subTest(scheme=scheme), patch('desk_companion.models.model_network.load',return_value=dict(mode='custom',
                    proxy_url=f'{scheme}://127.0.0.1:{proxy}',username='fixture',password='password')), self.llm() as llm:
                llm.item['base_url'] = f'http://provider.invalid:{provider_port}/v1'
                self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
        self.assertEqual(targets, [('provider.invalid',provider_port)]*2)
        self.assertEqual(credentials, [(b'fixture',b'password')]*2)

    def test_tls_requires_valid_ca_file_or_directory_and_never_disables_verification(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,'isolated Pi test')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
            .sign(key,hashes.SHA256()))
        ca = root/'ca.pem'; ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private = root/'server.key'; private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(ca,private)
        self.http.socket = tls.wrap_socket(self.http.socket,server_side=True)
        with self.llm() as llm:
            llm.item['base_url'] = llm.item['base_url'].replace('http:','https:')
            with self.assertRaises(IncompleteResponseError): llm.chat(self.messages)
        self.assertEqual(self.requests, [])
        for environment in [dict(SSL_CERT_FILE=str(ca)),dict(SSL_CERT_DIR=str(root))]:
            with self.subTest(environment=environment), patch.dict(os.environ,environment), self.llm() as llm:
                llm.item['base_url'] = llm.item['base_url'].replace('http:','https:')
                self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
        with patch.dict(os.environ, SSL_CERT_FILE=str(ca), http_proxy='http://127.0.0.1:1', https_proxy='',
                HTTPS_PROXY='', all_proxy='', ALL_PROXY='', no_proxy='', NO_PROXY=''), \
                patch('desk_companion.models.model_network.load',return_value=dict(mode='system')), self.llm() as llm:
            llm.item['base_url'] = llm.item['base_url'].replace('http:','https:')
            self.assertEqual(llm.chat(self.messages)['message']['content'], '40')
        self.assertEqual(len(self.requests), 3)
