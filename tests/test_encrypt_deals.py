import json
import pytest
from cryptography.exceptions import InvalidTag

from scripts.encrypt_deals import encrypt_file, decrypt, encrypt_bytes, decrypt_bytes


def test_encrypt_then_decrypt_roundtrip(tmp_path):
    src = tmp_path / "deals.json"
    src.write_text('{"gerado_em":"2026-06-18T11:03:00Z","deals":[{"preco":289.0}]}', encoding="utf-8")
    out = tmp_path / "deals.enc.json"

    encrypt_file(str(src), str(out), "segredo")

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["v"] == 2 and payload["enc"] == "gzip"
    assert payload["kdf"] == "PBKDF2-SHA256"
    assert payload["iterations"] == 200000
    assert payload["salt"] and payload["iv"] and payload["ciphertext"]

    clear = decrypt(payload, "segredo")
    assert json.loads(clear)["deals"][0]["preco"] == 289.0


def test_decrypt_wrong_password_raises(tmp_path):
    src = tmp_path / "deals.json"
    src.write_text('{"deals":[]}', encoding="utf-8")
    out = tmp_path / "deals.enc.json"
    encrypt_file(str(src), str(out), "certa")
    payload = json.loads(out.read_text(encoding="utf-8"))
    with pytest.raises(InvalidTag):
        decrypt(payload, "errada")


def test_v2_payload_is_much_smaller_for_repetitive_json():
    plain = json.dumps({"deals": [{"origem": "CNF", "destino": "GIG", "preco": 300.0}] * 2000}).encode()
    v1 = encrypt_bytes(plain, "s", compress=False)
    v2 = encrypt_bytes(plain, "s")
    assert len(v2["ciphertext"]) < len(v1["ciphertext"]) / 5
    assert decrypt_bytes(v2, "s") == plain


def test_v1_payloads_written_before_compression_still_decrypt():
    v1 = encrypt_bytes(b'{"deals":[]}', "s", compress=False)
    assert v1["v"] == 1 and "enc" not in v1
    assert decrypt_bytes(v1, "s") == b'{"deals":[]}'
