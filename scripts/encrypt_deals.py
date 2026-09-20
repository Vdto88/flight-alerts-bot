import base64
import gzip
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 200000


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_bytes(plaintext: bytes, password: str, compress: bool = True) -> dict:
    """AES-GCM under a PBKDF2 key. Ciphertext does not compress in transit, so the
    plaintext is gzipped first (payload v2); compress=False writes the old v1 shape."""
    body = gzip.compress(plaintext, mtime=0) if compress else plaintext
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = _derive_key(password, salt, ITERATIONS)
    payload = {
        "v": 2 if compress else 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "ciphertext": base64.b64encode(AESGCM(key).encrypt(iv, body, None)).decode("ascii"),
    }
    if compress:
        payload["enc"] = "gzip"
    return payload


def decrypt_bytes(payload: dict, password: str) -> bytes:
    salt = base64.b64decode(payload["salt"])
    iv = base64.b64decode(payload["iv"])
    key = _derive_key(password, salt, payload["iterations"])
    body = AESGCM(key).decrypt(iv, base64.b64decode(payload["ciphertext"]), None)
    return gzip.decompress(body) if payload.get("enc") == "gzip" else body


decrypt = decrypt_bytes   # older name, still imported by tests and scripts


def encrypt_file(in_path: str, out_path: str, password: str) -> str:
    with open(in_path, "rb") as fh:
        payload = encrypt_bytes(fh.read(), password)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return out_path


def main(password: str, root: str = ".") -> int:
    """Encrypt the snapshot and every per-route history file under `root`. History plaintext
    is removed once encrypted (nothing unencrypted may be published); deals.json stays because
    the workflow's snapshot check reads it. Returns the history files encrypted."""
    base = Path(root)
    encrypt_file(str(base / "deals.json"), str(base / "deals.enc.json"), password)
    count = 0
    for plain in sorted((base / "history").glob("*.json")):
        if plain.name.endswith(".enc.json"):
            continue
        encrypt_file(str(plain), str(plain.with_name(plain.stem + ".enc.json")), password)
        plain.unlink()
        count += 1
    return count


if __name__ == "__main__":
    main(os.environ["PANEL_PASSWORD"])
