"""Build a pinned private HTTP client; publish only the mileage panel."""
import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REVISION = "e83d4e4d3abfb51d2552c8950e97d664526c8c9a"


def build(root):
    root = Path(root).resolve()
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    if result.returncode or result.stdout.strip() != REVISION:
        raise ValueError("Unexpected client revision; review before changing the pin")
    candidates = []
    for path in root.glob("crates/*-cli/Cargo.toml"):
        meta = tomllib.loads(path.read_text(encoding="utf-8"))
        if meta.get("package", {}).get("description", "").startswith("Native CLI:"):
            candidates.append(meta)
    if len(candidates) != 1 or len(candidates[0].get("bin", [])) != 1:
        raise ValueError("Private client package layout changed")
    meta = candidates[0]
    package, binary = meta["package"]["name"], meta["bin"][0]["name"]
    # Compiler diagnostics include internal dependency names and paths. Keep
    # them off public workflow logs; report only a generic build failure.
    result = subprocess.run(["cargo", "build", "-p", package, "--bin", binary],
                            cwd=root, capture_output=True)
    if result.returncode:
        raise RuntimeError("Private mileage client build failed")
    suffix = ".exe" if os.name == "nt" else ""
    output = Path(__file__).resolve().parents[1] / "scripts" / "exploration" / "bin"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "target" / "debug" / (binary + suffix), output / ("award-http" + suffix))
    print("Mileage HTTP client ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    try:
        build(parser.parse_args().checkout)
    except Exception:
        print("Could not prepare the private mileage client; check access and build configuration.", file=sys.stderr)
        raise SystemExit(1) from None
