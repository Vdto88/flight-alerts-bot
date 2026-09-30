import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import local_miles, miles_publication
from scripts.encrypt_deals import decrypt_bytes, encrypt_bytes


def test_private_message_link_and_chat_id():
    assert local_miles.normalize_chat('https://t.me/c/1234567890/42/76') == '-1001234567890'
    assert local_miles.normalize_chat(' -1001234567890 ') == '-1001234567890'
    with pytest.raises(ValueError):
        local_miles.normalize_chat('https://example.com/123')


def test_wrong_panel_password_never_uploads(tmp_path):
    commands = []

    def command(args, **kwargs):
        commands.append(args)
        directory = Path(args[args.index('--dir') + 1])
        (directory / 'cache.db.gz.enc').write_text(json.dumps(encrypt_bytes(b'history', 'correct')))
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError, match='mesma do painel'):
        miles_publication.publish('wrong', tmp_path, command)
    assert len(commands) == 1
    assert not (tmp_path / 'miles.enc.json').exists()


def test_publication_uploads_only_encrypted_snapshot(tmp_path):
    snapshot = b'{"programs":{"azul":{"offers":[]}}}'
    (tmp_path / 'miles.json').write_bytes(snapshot)
    commands = []

    def command(args, **kwargs):
        commands.append(args)
        if args[2] == 'download':
            directory = Path(args[args.index('--dir') + 1])
            (directory / 'cache.db.gz.enc').write_text(json.dumps(encrypt_bytes(b'history', 'correct')))
        return SimpleNamespace(returncode=0)

    miles_publication.publish('correct', tmp_path, command)
    uploaded = commands[-1]
    assert uploaded[:4] == ['gh', 'release', 'upload', 'mileage-panel']
    assert Path(uploaded[4]).name == 'miles.enc.json'
    payload = json.loads(Path(uploaded[4]).read_text())
    assert decrypt_bytes(payload, 'correct') == snapshot
    assert all('correct' not in str(c) for c in commands)


def test_missing_release_preserves_existing_ciphertext(tmp_path):
    target = tmp_path / 'miles.enc.json'
    target.write_bytes(b'previous')
    assert not miles_publication.restore(tmp_path, lambda *a, **kw: SimpleNamespace(returncode=1))
    assert target.read_bytes() == b'previous'


def test_restore_rejects_plaintext(tmp_path):
    def command(args, **kwargs):
        directory = Path(args[args.index('--dir') + 1])
        (directory / 'miles.enc.json').write_text('{"offers":[]}')
        return SimpleNamespace(returncode=0)

    with pytest.raises(ValueError):
        miles_publication.restore(tmp_path, command)
    assert not (tmp_path / 'miles.enc.json').exists()


def test_manual_and_scheduled_runs_cannot_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(local_miles, 'ROOT', tmp_path)
    with local_miles.SingleRun():
        with pytest.raises(RuntimeError, match='execução'):
            with local_miles.SingleRun():
                pass
    with local_miles.SingleRun():
        pass
