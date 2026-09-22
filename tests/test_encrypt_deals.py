import json
import pytest
from cryptography.exceptions import InvalidTag

from scripts.encrypt_deals import encrypt_file, decrypt, encrypt_bytes, decrypt_bytes, main


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


def test_cli_encrypts_deals_and_every_history_file_and_removes_the_plaintext(tmp_path):
    (tmp_path / "deals.json").write_text('{"deals":[{"preco":1}]}', encoding="utf-8")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "CNF-GIG.json").write_text('{"rota":null,"series":{}}', encoding="utf-8")
    (hist / "GIG-CNF.json").write_text('{"rota":null,"series":{"k":[]}}', encoding="utf-8")

    assert main("segredo", root=str(tmp_path)) == 2

    assert sorted(p.name for p in hist.iterdir()) == ["CNF-GIG.enc.json", "GIG-CNF.enc.json"]
    payload = json.loads((hist / "GIG-CNF.enc.json").read_text(encoding="utf-8"))
    assert payload["v"] == 2 and json.loads(decrypt_bytes(payload, "segredo"))["series"] == {"k": []}
    assert (tmp_path / "deals.enc.json").exists()
    assert (tmp_path / "deals.json").exists()          # the workflow's snapshot check still reads it


def test_cli_without_a_history_directory_encrypts_only_the_deals(tmp_path):
    (tmp_path / "deals.json").write_text('{"deals":[]}', encoding="utf-8")
    assert main("segredo", root=str(tmp_path)) == 0
    assert (tmp_path / "deals.enc.json").exists()


def test_cli_does_not_re_encrypt_already_encrypted_files(tmp_path):
    (tmp_path / "deals.json").write_text('{"deals":[]}', encoding="utf-8")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "CNF-GIG.enc.json").write_text('{"v":2}', encoding="utf-8")
    assert main("segredo", root=str(tmp_path)) == 0
    assert (hist / "CNF-GIG.enc.json").read_text(encoding="utf-8") == '{"v":2}'


def test_cli_encrypts_the_promotions_payload_when_it_exists(tmp_path):
    (tmp_path / "deals.json").write_text(json.dumps({"deals": []}), encoding="utf-8")
    (tmp_path / "promo_data").mkdir()
    promos = {"gerado_em": "2026-09-21T12:00:00Z", "promos": [{"titulo": "Promoção"}]}
    (tmp_path / "promo_data" / "promos.json").write_text(json.dumps(promos), encoding="utf-8")

    main("senha", root=str(tmp_path))

    payload = json.loads((tmp_path / "promos.enc.json").read_text(encoding="utf-8"))
    assert payload["v"] == 2
    assert json.loads(decrypt_bytes(payload, "senha")) == promos


def test_cli_without_a_promotions_payload_writes_no_promotions_file(tmp_path):
    (tmp_path / "deals.json").write_text(json.dumps({"deals": []}), encoding="utf-8")
    main("senha", root=str(tmp_path))
    assert not (tmp_path / "promos.enc.json").exists()
