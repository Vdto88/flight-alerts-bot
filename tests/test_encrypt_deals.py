import json
import pytest
from cryptography.exceptions import InvalidTag

from scripts.encrypt_deals import encrypt_file, decrypt


def test_encrypt_then_decrypt_roundtrip(tmp_path):
    src = tmp_path / "deals.json"
    src.write_text('{"gerado_em":"2026-06-18T11:03:00Z","deals":[{"preco":289.0}]}', encoding="utf-8")
    out = tmp_path / "deals.enc.json"

    encrypt_file(str(src), str(out), "segredo")

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["v"] == 1 and payload["kdf"] == "PBKDF2-SHA256"
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
