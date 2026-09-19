import json
import subprocess
from pathlib import Path

from scripts import history_backup as hb
from scripts.encrypt_deals import encrypt_bytes


class FakeGh:
    """Stands in for subprocess.run; records calls and plays the part of `gh`."""

    def __init__(self, asset: bytes | None = None, fail: set[str] = frozenset()):
        self.asset, self.fail, self.calls = asset, fail, []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        verb = cmd[2]
        if verb in self.fail:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"boom")
        if verb == "download":
            if self.asset is None:
                raise subprocess.CalledProcessError(1, cmd, stderr=b"release not found")
            out_dir = Path(cmd[cmd.index("--dir") + 1])
            (out_dir / hb.ASSET).write_bytes(self.asset)
        return subprocess.CompletedProcess(cmd, 0)


def test_backup_then_restore_round_trips_the_database(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"SQLite format 3\x00" + b"x" * 5000)
    uploaded = {}

    def gh(cmd, **kwargs):
        if cmd[2] == "upload":
            uploaded["bytes"] = Path(cmd[4]).read_bytes()
        return subprocess.CompletedProcess(cmd, 0)

    assert hb.backup(db, "segredo", run=gh) is True
    assert b"SQLite format" not in uploaded["bytes"]          # never leaves in the clear

    restored = tmp_path / "restored.db"
    assert hb.restore(restored, "segredo", run=FakeGh(asset=uploaded["bytes"])) is True
    assert restored.read_bytes() == db.read_bytes()


def test_restore_without_a_release_starts_empty_and_does_not_raise(tmp_path):
    target = tmp_path / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=None)) is False
    assert not target.exists()


def test_restore_with_a_corrupt_or_foreign_asset_leaves_nothing_behind(tmp_path):
    target = tmp_path / "cache.db"
    wrong_key = json.dumps(encrypt_bytes(b"data", "outra-senha")).encode()
    assert hb.restore(target, "segredo", run=FakeGh(asset=b"not json")) is False
    assert hb.restore(target, "segredo", run=FakeGh(asset=wrong_key)) is False
    assert not target.exists()


def test_restore_that_cannot_write_the_database_reports_failure(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("this is a regular file, not a directory")
    good_asset = json.dumps(encrypt_bytes(b"payload", "segredo")).encode()
    target = blocker / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=good_asset)) is False
    assert blocker.read_text() == "this is a regular file, not a directory"


def test_backup_creates_the_release_when_the_upload_finds_none(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"data")
    state = {"created": False}
    verbs = []

    def gh(cmd, **kwargs):
        verbs.append(cmd[2])
        if cmd[2] == "upload" and not state["created"]:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"release not found")
        if cmd[2] == "create":
            state["created"] = True
        return subprocess.CompletedProcess(cmd, 0)

    assert hb.backup(db, "segredo", run=gh) is True
    assert verbs == ["upload", "create", "upload"]


def test_backup_reports_failure_without_raising(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"data")
    assert hb.backup(db, "segredo", run=FakeGh(fail={"upload", "create"})) is False
    assert hb.backup(tmp_path / "missing.db", "segredo", run=FakeGh()) is False
