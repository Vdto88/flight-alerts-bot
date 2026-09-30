"""Exchange only the encrypted local mileage snapshot with the public panel."""
import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.encrypt_deals import decrypt_bytes, encrypt_file

TAG = "mileage-panel"
ASSET = "miles.enc.json"
log = logging.getLogger(__name__)


def publish(password, root=Path("."), run=subprocess.run):
    root = Path(root)
    # Confirm this is the existing panel password before replacing its snapshot.
    with tempfile.TemporaryDirectory(prefix="miles-password-") as directory:
        result = run(["gh", "release", "download", "history-db", "--pattern", "cache.db.gz.enc",
                      "--dir", directory], cwd=root, capture_output=True)
        if result.returncode:
            raise RuntimeError("Não foi possível verificar a senha do painel no GitHub.")
        try:
            payload = json.loads((Path(directory) / "cache.db.gz.enc").read_text(encoding="utf-8"))
            decrypt_bytes(payload, password)
        except Exception:
            raise ValueError("A senha local precisa ser a mesma do painel atual.") from None
    encrypted = root / ASSET
    encrypt_file(str(root / "miles.json"), str(encrypted), password)
    exists = run(["gh", "release", "view", TAG], cwd=root, capture_output=True)
    if exists.returncode:
        created = run(["gh", "release", "create", TAG, "--target", "master",
                       "--title", "Mileage panel data", "--notes", "Encrypted local mileage snapshot."],
                      cwd=root, capture_output=True)
        if created.returncode:
            raise RuntimeError("Não foi possível preparar os dados do painel no GitHub.")
    uploaded = run(["gh", "release", "upload", TAG, str(encrypted.resolve()), "--clobber"],
                   cwd=root, capture_output=True)
    if uploaded.returncode:
        raise RuntimeError("Não foi possível enviar os dados criptografados ao painel.")
    log.info("Dados de milhas criptografados enviados; entram na próxima publicação do site.")


def restore(root=Path("."), run=subprocess.run):
    root = Path(root)
    with tempfile.TemporaryDirectory(prefix="miles-restore-") as directory:
        result = run(["gh", "release", "download", TAG, "--pattern", ASSET, "--dir", directory],
                     cwd=root, capture_output=True)
        if result.returncode:
            log.info("Ainda não há coleta local publicada; painel de milhas aguarda configuração.")
            return False
        content = (Path(directory) / ASSET).read_bytes()
        payload = json.loads(content)
        if not all(payload.get(k) for k in ("salt", "iv", "ciphertext", "iterations")):
            raise ValueError("Invalid encrypted mileage snapshot")
        (root / ASSET).write_bytes(content)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["restore"])
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    restore()
