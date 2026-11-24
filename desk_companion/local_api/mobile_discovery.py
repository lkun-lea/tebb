"""Authenticated LAN discovery. Only the same account can decrypt the desktop invitation."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import threading

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PORT = 41926
PROBE = re.compile(rb'tebb2 ([0-9a-f]{32}) ([0-9a-f]{64})')


def proof(key, message):
    return hmac.new(key, message.encode('ascii'), hashlib.sha256).hexdigest()


class Discovery:
    def __init__(self, offer):
        self.offer = offer
        self.sock = None

    def start(self):
        if self.sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('', PORT))
        except OSError:
            sock.close()
            return
        self.sock = sock
        threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def close(self):
        sock, self.sock = self.sock, None
        if sock:
            sock.close()

    def _serve(self, sock):
        while self.sock is sock:
            try:
                packet, sender = sock.recvfrom(256)
                match = PROBE.fullmatch(packet)
                if match and ipaddress.ip_address(sender[0]).is_private:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                        route.connect(sender)
                        address = route.getsockname()[0]
                    reply = self.offer(*(v.decode('ascii') for v in match.groups()), address)
                    if reply:
                        sock.sendto(reply, sender)
            except OSError:
                if self.sock is not sock:
                    return
            except (ValueError, RuntimeError):
                continue


def sealed_offer(key, nonce, device):
    iv = os.urandom(12)
    body = json.dumps(device, separators=(',', ':')).encode()
    return base64.b64encode(iv + AESGCM(key).encrypt(iv, body, nonce.encode('ascii')))
