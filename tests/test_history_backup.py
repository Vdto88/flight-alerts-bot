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
        if verb in ("download", "view"):
            if self.asset is None:      # no asset configured == the release does not exist
                raise subprocess.CalledProcessError(1, cmd, stderr=b"release not found")
        if verb == "download":
            out_dir = Path(cmd[cmd.index("--dir") + 1])
            (out_dir / hb.ASSET).write_bytes(self.asset)
        return subprocess.CompletedProcess(cmd, 0)


def marker_in(tmp_path) -> Path:
    return tmp_path / "marker_data" / ".restore_failed"


def test_backup_then_restore_round_trips_the_database(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"SQLite format 3\x00" + b"x" * 5000)
    uploaded = {}

    def gh(cmd, **kwargs):
        if cmd[2] == "upload":
            uploaded["bytes"] = Path(cmd[4]).read_bytes()
        return subprocess.CompletedProcess(cmd, 0)

    assert hb.backup(db, "segredo", run=gh, marker=marker_in(tmp_path)) is True
    assert b"SQLite format" not in uploaded["bytes"]          # never leaves in the clear

    restored = tmp_path / "restored.db"
    assert hb.restore(restored, "segredo", run=FakeGh(asset=uploaded["bytes"]),
                      marker=marker_in(tmp_path)) is True
    assert restored.read_bytes() == db.read_bytes()


def test_restore_without_a_release_starts_empty_and_does_not_raise(tmp_path):
    target = tmp_path / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=None),
                      marker=marker_in(tmp_path)) is False
    assert not target.exists()


def test_restore_with_a_corrupt_or_foreign_asset_leaves_nothing_behind(tmp_path):
    target = tmp_path / "cache.db"
    wrong_key = json.dumps(encrypt_bytes(b"data", "outra-senha")).encode()
    marker = marker_in(tmp_path)
    assert hb.restore(target, "segredo", run=FakeGh(asset=b"not json"), marker=marker) is False
    assert hb.restore(target, "segredo", run=FakeGh(asset=wrong_key), marker=marker) is False
    assert not target.exists()


def test_restore_that_cannot_write_the_database_reports_failure(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("this is a regular file, not a directory")
    good_asset = json.dumps(encrypt_bytes(b"payload", "segredo")).encode()
    target = blocker / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=good_asset),
                      marker=marker_in(tmp_path)) is False
    assert blocker.read_text() == "this is a regular file, not a directory"


def test_failed_restore_blocks_backups_when_the_release_still_has_a_backup(tmp_path):
    target, marker = tmp_path / "cache.db", marker_in(tmp_path)
    # the release is there (so `view` succeeds) but the download itself blew up
    gh = FakeGh(asset=b"whatever", fail={"download"})
    assert hb.restore(target, "segredo", run=gh, marker=marker) is False
    assert marker.exists()
    assert not target.exists()


def test_failed_restore_without_a_release_does_not_block_backups(tmp_path):
    target, marker = tmp_path / "cache.db", marker_in(tmp_path)
    assert hb.restore(target, "segredo", run=FakeGh(asset=None), marker=marker) is False
    assert not marker.exists()


def test_a_successful_restore_clears_a_stale_block(tmp_path):
    marker = marker_in(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    asset = json.dumps(encrypt_bytes(b"payload", "segredo")).encode()
    target = tmp_path / "cache.db"
    assert hb.restore(target, "segredo", run=FakeGh(asset=asset), marker=marker) is True
    assert not marker.exists()


def test_backup_refuses_to_upload_over_a_backup_it_could_not_restore(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"an empty-ish database built from nothing")
    marker = marker_in(tmp_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    gh = FakeGh(asset=b"whatever")

    assert hb.backup(db, "segredo", run=gh, marker=marker) is False
    assert gh.calls == []                       # nothing was uploaded over the good copy
    # The marker stays: data/ is cached, so a later run would otherwise find a warm cache,
    # skip the restore entirely and clobber the release with this thin database.
    assert marker.exists()
    assert hb.backup(db, "segredo", run=gh, marker=marker) is False
    assert gh.calls == []


def test_a_retried_restore_replaces_the_thin_database_and_unblocks_backups(tmp_path):
    """The workflow re-runs the restore while the marker is there; that must self-heal."""
    db, marker = tmp_path / "cache.db", marker_in(tmp_path)
    db.write_bytes(b"the empty database the blocked run built")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    asset = json.dumps(encrypt_bytes(b"SQLite format 3\x00the real history", "segredo")).encode()

    assert hb.restore(db, "segredo", run=FakeGh(asset=asset), marker=marker) is True
    assert db.read_bytes() == b"SQLite format 3\x00the real history"
    assert not marker.exists()

    gh = FakeGh()
    assert hb.backup(db, "segredo", run=gh, marker=marker) is True
    assert [c[2] for c in gh.calls] == ["upload"]


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

    assert hb.backup(db, "segredo", run=gh, marker=marker_in(tmp_path)) is True
    assert verbs == ["upload", "create", "upload"]


def test_backup_reports_failure_without_raising(tmp_path):
    db = tmp_path / "cache.db"
    db.write_bytes(b"data")
    marker = marker_in(tmp_path)
    assert hb.backup(db, "segredo", run=FakeGh(fail={"upload", "create"}), marker=marker) is False
    assert hb.backup(tmp_path / "missing.db", "segredo", run=FakeGh(), marker=marker) is False
