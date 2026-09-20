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
# Written when a backup exists on the release but could not be restored; while it is there the
# database in hand is not the real history, so uploading it would clobber the only good copy.
RESTORE_FAILED_MARKER = Path("data/.restore_failed")


def _release_exists(run) -> bool:
    """True when the release is there, i.e. a restore failure lost an existing backup."""
    try:
        run(["gh", "release", "view", TAG], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _restore_failed(marker: Path, run, error: Exception) -> bool:
    if not _release_exists(run):                    # nothing was there to lose
        logger.warning(f"backup do histórico não restaurado, começando vazio: {error!r}")
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("", encoding="utf-8")
    except Exception as e:                          # best effort; the ERROR below is the signal
        logger.error(f"não foi possível marcar a falha de restore em {marker}: {e!r}")
    logger.error(
        f"a release {TAG} tem um backup mas ele não foi restaurado ({error!r}); "
        "backups bloqueados nesta execução para preservar a cópia boa"
    )
    return False


def restore(db_path: Path, password: str, run=subprocess.run,
            marker: Path = RESTORE_FAILED_MARKER) -> bool:
    db_path, marker = Path(db_path), Path(marker)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(["gh", "release", "download", TAG, "--pattern", ASSET, "--dir", tmp],
                check=True, capture_output=True)
            payload = json.loads((Path(tmp) / ASSET).read_text(encoding="utf-8"))
            data = decrypt_bytes(payload, password)
        except Exception as e:                      # missing release, bad asset, wrong key...
            return _restore_failed(marker, run, e)
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(data)
    except Exception as e:                          # read-only fs, full disk, parent is a file...
        return _restore_failed(marker, run, e)
    try:
        marker.unlink()                             # a good restore clears a stale block
    except OSError:
        pass
    logger.info(f"histórico restaurado da release {TAG}: {len(data)} bytes")
    return True


def backup(db_path: Path, password: str, run=subprocess.run,
           marker: Path = RESTORE_FAILED_MARKER) -> bool:
    db_path, marker = Path(db_path), Path(marker)
    if marker.exists():
        logger.error("backup bloqueado: o restore falhou nesta execução, "
                     "a cópia boa na release foi preservada")
        try:
            marker.unlink()     # data/ is cached, so the block must not survive into another run
        except OSError:
            pass
        return False
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
    if action == "restore":
        restore(DB_PATH, password)
        sys.exit(0)             # a failed restore must never turn the run red
    blocked = RESTORE_FAILED_MARKER.exists()
    backup(DB_PATH, password)
    sys.exit(1 if blocked else 0)   # only a blocked backup is worth showing as failed
