import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 200000


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(in_path: str, out_path: str, password: str) -> str:
    with open(in_path, "rb") as fh:
        plaintext = fh.read()
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive_key(password, salt, ITERATIONS)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)
    payload = {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return out_path


def decrypt(payload: dict, password: str) -> bytes:
    salt = base64.b64decode(payload["salt"])
    iv = base64.b64decode(payload["iv"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    key = _derive_key(password, salt, payload["iterations"])
    return AESGCM(key).decrypt(iv, ciphertext, None)


if __name__ == "__main__":
    encrypt_file("deals.json", "deals.enc.json", os.environ["PANEL_PASSWORD"])
