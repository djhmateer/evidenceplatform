from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel

FILE_TOKEN_SECRET_ENV = "FILE_TOKEN_SECRET"
# number of bytes of nonce for ChaCha20-Poly1305
NONCE_SIZE = 12
KEY_LEN = 32


class FileTokenError(Exception):
    pass


def _get_secret() -> bytes:
    s = os.getenv("FILE_TOKEN_SECRET")
    if not s:
        raise FileTokenError(f"Environment variable FILE_TOKEN_SECRET not set")
    # treat secret as raw bytes; allow hex or direct string
    # Try hex decode if it looks hex-ish and even-length
    try:
        if all(c in "0123456789abcdefABCDEF" for c in s) and len(s) % 2 == 0:
            return bytes.fromhex(s)
    except Exception:
        pass
    return s.encode("utf-8")


def _derive_key_for_path(file_path: str) -> bytes:
    """Derive a 32-byte AEAD key for the given file path using HKDF-SHA256.
    This binds tokens to the path. The file_path MUST be canonicalized the same way
    by both generator and verifier (we use the raw request.path string).
    """
    secret = _get_secret()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=None,
        info=(b"file-token" + file_path.encode("utf-8")),
    )
    return hkdf.derive(secret)


class FileTokenPayload(BaseModel):
    login_token: str


def generate_file_token(login_token: str, file_path: str) -> str:
    print("Generating file token for path:", file_path)
    # Generate a url-safe per-file token that encrypts the login token.
    key = _derive_key_for_path(file_path)
    aead = ChaCha20Poly1305(key)
    nonce = os.urandom(NONCE_SIZE)
    payload = FileTokenPayload(login_token=login_token).model_dump()
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = aead.encrypt(nonce, plaintext, associated_data=None)
    blob = nonce + ciphertext
    return base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def decrypt_file_token(token: str, file_path: str) -> FileTokenPayload:
    try:
        # pad base64
        padding = "=" * ((4 - len(token) % 4) % 4)
        blob = base64.urlsafe_b64decode(token + padding)
    except Exception as e:
        raise FileTokenError("Malformed token (base64 decode failed)") from e

    if len(blob) < NONCE_SIZE + 16:
        # 16 is minimal tag + some ciphertext
        raise FileTokenError("Malformed token (too short)")

    nonce = blob[:NONCE_SIZE]
    ciphertext = blob[NONCE_SIZE:]
    key = _derive_key_for_path(file_path)
    aead = ChaCha20Poly1305(key)
    try:
        plaintext = aead.decrypt(nonce, ciphertext, associated_data=None)
    except InvalidTag as e:
        raise FileTokenError("Invalid token or wrong file path") from e
    except Exception as e:
        raise FileTokenError("Decryption failed") from e

    try:
        payload = json.loads(plaintext.decode("utf-8"))
        payload = FileTokenPayload(**payload)
    except Exception as e:
        raise FileTokenError("Failed to parse token payload") from e

    return payload

