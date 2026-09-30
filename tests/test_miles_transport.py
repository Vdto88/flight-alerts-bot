import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from miles import transport


def test_post_goes_only_through_client_and_temp_payload_is_removed(monkeypatch):
    monkeypatch.setattr(transport, "binary_path", lambda: "local-client")
    monkeypatch.setenv("HTTPS_PROXY", "https://not-used.invalid")
    seen = {}
    def invoke(command, **kwargs):
        assert command[0] == "local-client" and "-L" in command
        assert command[command.index("-X") + 1] == "POST"
        assert "HTTPS_PROXY" not in kwargs["env"]
        request = Path(command[command.index("--data-binary") + 1][1:])
        assert json.loads(request.read_text()) == {"query": "public offers"}
        seen["request"] = request
        Path(command[command.index("-D") + 1]).write_bytes(b"HTTP/1.1 302 Redirect\r\n\r\nHTTP/2 200 OK\r\n\r\n")
        Path(command[command.index("-o") + 1]).write_bytes(b'{"offers": []}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(transport.subprocess, "run", invoke)
    response = transport.Client().post("https://vg-api.airtrfx.com/graphql", json={"query": "public offers"})
    assert response.status_code == 200 and response.json() == {"offers": []}
    assert not seen["request"].exists()


def test_missing_binary_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("MILES_CLIENT_BIN", "not-installed")
    monkeypatch.setattr(transport.shutil, "which", lambda _: None)
    with pytest.raises(transport.ClientUnavailable):
        transport.Client()


def test_error_output_is_not_exposed_and_request_has_bounded_timeout(monkeypatch):
    monkeypatch.setattr(transport, "binary_path", lambda: "local-client")
    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=35, stderr=b"sensitive headers"))
    with pytest.raises(ValueError, match="Mileage client exited 35") as error:
        transport.Client().get("https://www.smiles.com.br/passagens")
    assert "sensitive" not in str(error.value)
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 8
        raise subprocess.TimeoutExpired(command, 8)
    monkeypatch.setattr(transport.subprocess, "run", timeout)
    with pytest.raises(TimeoutError, match="Mileage client request timed out"):
        transport.Client(timeout=5).get("https://www.smiles.com.br/passagens")
