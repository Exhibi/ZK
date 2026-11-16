import base64
import hashlib
import hmac
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def make_nonce():
    return secrets.token_hex(32)


def make_proof(nonce, token):
    return hmac.new(
        token.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_proof(nonce, proof, token):
    expected = make_proof(nonce, token)

    return hmac.compare_digest(
        expected,
        str(proof)
    )


def _key(token):
    return hashlib.sha256(
        b"LanControl-V2.1|" + token.encode("utf-8")
    ).digest()


def encrypt_packet(payload, token):
    nonce = secrets.token_bytes(12)

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")

    encrypted = AESGCM(_key(token)).encrypt(
        nonce,
        raw,
        b"LanControl-V2.1"
    )

    return {
        "enc": base64.b64encode(
            nonce + encrypted
        ).decode("ascii")
    }


def decrypt_packet(packet, token):
    if not isinstance(packet, dict) or "enc" not in packet:
        raise ValueError("收到无效的加密数据包")

    raw = base64.b64decode(packet["enc"])

    if len(raw) < 29:
        raise ValueError("加密数据包长度错误")

    plain = AESGCM(_key(token)).decrypt(
        raw[:12],
        raw[12:],
        b"LanControl-V2.1"
    )

    return json.loads(
        plain.decode("utf-8")
    )