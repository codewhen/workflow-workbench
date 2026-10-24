"""Verify generic package boundaries without executing packaged commands."""

from __future__ import annotations

import io
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN = re.compile(
    r"(^|/)(coverage|private-plugins|workflows/(test|build|release))(/|$)|browser-sessions\.json"
)

STRAY_ROOT_WORKFLOWS = re.compile(r"^(?:[^/]+/)?(?:full|release-workbench)\.yaml$")


def inspect(name: str, data: bytes) -> None:
    if FORBIDDEN.search(name):
        raise ValueError("Application data found in public artifact: " + name)
    if STRAY_ROOT_WORKFLOWS.fullmatch(name):
        raise ValueError("Application workflow found in public artifact: " + name)
    if name.endswith(".whl"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for child in archive.namelist():
                inspect(child, archive.read(child))
            assert any(child.endswith("application/starters.py") for child in archive.namelist())


def main(paths: list[str]) -> None:
    if not paths:
        raise SystemExit("Usage: verify_distribution.py WHEEL SOURCE_ARCHIVE NPM_ARCHIVE")
    for filename in paths:
        path = Path(filename)
        if path.suffix == ".whl":
            inspect(path.name, path.read_bytes())
        else:
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if member.isfile():
                        stream = archive.extractfile(member)
                        assert stream is not None
                        inspect(member.name, stream.read())
        print("PASS generic distribution:", path.name)
    print(json.dumps({"artifacts_checked": len(paths), "application_workflows_bundled": False}))


if __name__ == "__main__":
    main(sys.argv[1:])
