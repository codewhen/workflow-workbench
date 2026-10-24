"""Build, verify and publish Workbench to npm on Windows or macOS."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package_metadata(root: Path) -> tuple[str, str]:
    package = json.loads((root / "npm/workbench/package.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    module = ast.parse((root / "src/release_workbench/__init__.py").read_text(encoding="utf-8"))
    runtime = next(
        ast.literal_eval(statement.value)
        for statement in module.body
        if isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        )
    )
    version = package["version"]
    if version != project["project"]["version"] or version != runtime:
        raise ValueError(
            "Align npm/workbench/package.json, pyproject.toml and __version__ before releasing."
        )
    return package["name"], version


def npm_program(windows: bool) -> str:
    name = "npm.cmd" if windows else "npm"
    found = shutil.which(name)
    if not found:
        raise ValueError("Install Node.js 22 or later with npm and add it to PATH.")
    return found


def release(args: argparse.Namespace, root: Path = ROOT) -> None:
    name, version = package_metadata(root)
    npm = npm_program(sys.platform == "win32")
    node = shutil.which("node")
    if not node:
        raise ValueError("Install Node.js 22 or later and add it to PATH.")
    environment = dict(os.environ)
    environment["PATH"] = (
        str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    )
    environment["WORKBENCH_PYTHON"] = sys.executable
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"

    def run(command: list[str], cwd: Path = root) -> None:
        print("RUN: " + subprocess.list2cmdline(command), flush=True)
        subprocess.run(command, cwd=cwd, env=environment, check=True)

    major = int(
        subprocess.check_output(
            [node, "-p", "process.versions.node.split('.')[0]"], text=True
        ).strip()
    )
    if major < 22:
        raise ValueError("Release builds require Node.js 22 or later for documentation tooling.")
    if not args.pack_only and not args.dry_run:
        # Check before the build; npm inherits the terminal for login/2FA prompts.
        run([npm, "whoami"])
    print(f"Preparing {name}@{version}", flush=True)
    frontend, docs, package = (root / path for path in ("frontend", "docs-site", "npm/workbench"))
    for directory in (frontend, docs):
        run([npm, "ci"], directory)
    for command in (
        [sys.executable, "-m", "ruff", "check", "src", "tests"],
        [sys.executable, "-m", "ruff", "format", "--check", "src", "tests"],
        [sys.executable, "-m", "mypy", "src"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    ):
        run(command)
    run([npm, "test"], frontend)
    run([npm, "run", "build"], frontend)
    run([npm, "exec", "--", "playwright", "install", "chromium"], frontend)
    run([npm, "run", "test:browser"], frontend)
    for task in ("check", "examples", "build", "build:pages", "test:browser"):
        run([npm, "run", task], docs)
    run([sys.executable, "-m", "build"])
    run([npm, "test"], package)
    dist = root / "dist"
    run([npm, "pack", "--pack-destination", str(dist)], package)
    archive = dist / f"{name.lstrip('@').replace('/', '-')}-{version}.tgz"
    artifacts = [
        dist / f"release_workbench-{version}-py3-none-any.whl",
        dist / f"release_workbench-{version}.tar.gz",
        archive,
    ]
    run(
        [
            sys.executable,
            str(root / "tools/verify_distribution.py"),
            *(str(path) for path in artifacts),
        ]
    )
    checksums = "".join(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
        for path in artifacts
    )
    (dist / f"SHA256SUMS-{version}").write_text(checksums, encoding="utf-8", newline="\n")
    print(f"Verified npm archive: {archive}", flush=True)
    if args.pack_only:
        return
    command = [npm, "publish", str(archive), "--access", "public", "--tag", args.tag]
    if args.dry_run:
        command.append("--dry-run")
    run(command, package)
    if not args.dry_run:
        run([npm, "view", f"{name}@{version}", "version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all checks and npm publish --dry-run; do not upload.",
    )
    mode.add_argument(
        "--pack-only",
        action="store_true",
        help="Run all checks and create the .tgz without publishing.",
    )
    parser.add_argument("--tag", default="latest", help="npm distribution tag (default: latest).")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", args.tag):
        parser.error("Use an npm tag starting with a letter, such as latest or next.")
    try:
        release(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
