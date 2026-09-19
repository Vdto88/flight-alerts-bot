"""Durable copy of data/cache.db in a GitHub Release asset.

actions/cache is the fast path but is evicted after 7 idle days. After every good cycle
the database is gzipped, encrypted with the panel password (the repo is public) and
uploaded over the previous copy; a run that starts with no cache downloads it back.
Neither direction may ever fail the job.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.encrypt_deals import decrypt_bytes, encrypt_bytes  # noqa: E402

logger = logging.getLogger("history_backup")

TAG = "history-db"
ASSET = "cache.db.gz.enc"
DB_PATH = Path("data/cache.db")


def restore(db_path: Path, password: str, run=subprocess.run) -> bool:
    db_path = Path(db_path)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(["gh", "release", "download", TAG, "--pattern", ASSET, "--dir", tmp],
                check=True, capture_output=True)
            payload = json.loads((Path(tmp) / ASSET).read_text(encoding="utf-8"))
            data = decrypt_bytes(payload, password)
        except Exception as e:                      # missing release, bad asset, wrong key...
            logger.warning(f"backup do histórico não restaurado, começando vazio: {e!r}")
            return False
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(data)
    except Exception as e:                          # read-only fs, full disk, parent is a file...
        logger.warning(f"backup do histórico não restaurado, começando vazio: {e!r}")
        return False
    logger.info(f"histórico restaurado da release {TAG}: {len(data)} bytes")
    return True


def backup(db_path: Path, password: str, run=subprocess.run) -> bool:
    db_path = Path(db_path)
    if not db_path.exists():
        logger.warning(f"{db_path} não existe; nada para salvar")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        asset = Path(tmp) / ASSET
        asset.write_text(json.dumps(encrypt_bytes(db_path.read_bytes(), password)), encoding="utf-8")
        upload = ["gh", "release", "upload", TAG, str(asset), "--clobber"]
        try:
            try:
                run(upload, check=True, capture_output=True)
            except subprocess.CalledProcessError:
                run(["gh", "release", "create", TAG, "--title", "Price history backup",
                     "--notes", "Encrypted sqlite backup, overwritten after every cycle."],
                    check=True, capture_output=True)
                run(upload, check=True, capture_output=True)
        except Exception as e:
            logger.warning(f"backup do histórico falhou: {e!r}")
            return False
    logger.info(f"histórico salvo na release {TAG}")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("restore", "backup"):
        sys.exit("usage: history_backup.py restore|backup")
    password = os.environ.get("PANEL_PASSWORD")
    if not password:
        logger.warning("PANEL_PASSWORD ausente; backup do histórico ignorado")
        sys.exit(0)
    (restore if action == "restore" else backup)(DB_PATH, password)
    sys.exit(0)     # a failed backup or restore must never turn the run red
