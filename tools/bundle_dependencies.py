#!/usr/bin/python3
"""Maintainer-only: restore pinned sources/licenses and core wheel metadata."""

import hashlib
import io
import json
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    target = ROOT / "vendor"
    if target.exists():
        raise SystemExit("vendor already exists; move it aside before rebuilding")
    lock = json.loads((ROOT / "vendor-lock.json").read_text())
    with tempfile.TemporaryDirectory(prefix=".vendor-", dir=ROOT) as directory:
        stage = Path(directory) / "vendor"
        stage.mkdir()
        for package in lock["packages"]:
            url = package["url"]
            if not url.startswith("https://files.pythonhosted.org/"):
                raise ValueError("Expected an official PyPI wheel URL")
            with urllib.request.urlopen(url, timeout=30) as response:
                wheel = response.read()
            if hashlib.sha256(wheel).hexdigest() != package["sha256"]:
                raise ValueError("Wheel hash mismatch: " + package["name"])
            with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
                for member in archive.infolist():
                    path = Path(member.filename)
                    if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Unsafe wheel path")
                    if any(part.endswith(".data") for part in path.parts):
                        raise ValueError("Wheel requires installation outside vendor")
                    if member.is_dir():
                        continue
                    destination = stage / path
                    if destination.exists():
                        raise ValueError("Overlapping wheel contents")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    data = archive.read(member)
                    if path.name == "METADATA" and path.parent.name.endswith(".dist-info"):
                        # Upstream install tutorials do not apply to this vendored plugin.
                        headers, separator, _ = data.partition(b"\n\n")
                        if not separator:
                            raise ValueError("Wheel metadata has no header separator")
                        data = headers + b"\n"
                        if hashlib.sha256(data).hexdigest() != package["metadata_sha256"]:
                            raise ValueError("Core metadata hash mismatch: " + package["name"])
                    destination.write_bytes(data)
            print(package["name"], package["version"])
        stage.rename(target)


if __name__ == "__main__":
    main()
