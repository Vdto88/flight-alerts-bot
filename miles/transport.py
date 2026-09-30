"""Local private HTTP client. Never falls back to another transport."""
import json as json_module
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode


class ClientUnavailable(RuntimeError):
    pass


def binary_path():
    configured = os.environ.get("MILES_CLIENT_BIN")
    if configured:
        found = shutil.which(configured)
        if found:
            return found
        raise ClientUnavailable("MILES_CLIENT_BIN is not executable")
    name = "award-http.exe" if os.name == "nt" else "award-http"
    candidate = Path(__file__).resolve().parents[1] / "scripts" / "exploration" / "bin" / name
    if candidate.is_file():
        return str(candidate)
    installed = shutil.which("award-http")
    if installed:
        return installed
    raise ClientUnavailable("Mileage HTTP client is not installed")


class Response:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.text = content.decode("utf-8", errors="replace")

    def json(self):
        return json_module.loads(self.text)

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise ValueError(f"HTTP {self.status_code}")


class Client:
    def __init__(self, timeout=15, follow_redirects=True):
        self.binary = binary_path()
        self.timeout, self.follow_redirects = timeout, follow_redirects

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, *, headers=None, params=None, json=None):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        with tempfile.TemporaryDirectory(prefix="flight-awards-") as directory:
            base = Path(directory)
            command = [self.binary, "-s", "--compressed", "--max-time", str(self.timeout),
                       "-X", method, "-D", str(base / "headers"), "-o", str(base / "body")]
            # The shared CLI otherwise inserts its own UA and forwards it as
            # an override to the browser persona. Use its matching browser UA.
            command.extend(["-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"])
            if self.follow_redirects:
                command.append("-L")
            for name, value in (headers or {}).items():
                command.extend(["-H", f"{name}: {value}"])
            if json is not None:
                (base / "request").write_text(json_module.dumps(json), encoding="utf-8")
                command.extend(["-H", "Content-Type: application/json", "--data-binary", "@" + str(base / "request")])
            command.append(url)
            # Direct outbound TLS from this machine/runner. No inherited proxy,
            # owner-hosted daemon, or paid CAPTCHA service.
            env = {k: v for k, v in os.environ.items()
                   if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}}
            try:
                result = subprocess.run(command, capture_output=True, timeout=self.timeout + 3,
                                        env=env, check=False)
            except subprocess.TimeoutExpired:
                raise TimeoutError("Mileage client request timed out") from None
            if result.returncode:
                # Never log argv (public-page JWT), stderr, headers or response bodies.
                raise ValueError(f"Mileage client exited {result.returncode}")
            statuses = re.findall(rb"HTTP/\S+ (\d{3})", (base / "headers").read_bytes())
            if not statuses:
                raise ValueError("Mileage client returned no HTTP status")
            return Response(int(statuses[-1]), (base / "body").read_bytes())
