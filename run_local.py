#!/usr/bin/env python3
"""Set up, build and run this Workbench checkout with one command."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n==> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT, help="Workflow project to open")
    parser.add_argument("--port", type=int, default=3110, help="Local HTTP port (default: 3110)")
    parser.add_argument(
        "--storage", type=Path, default=ROOT / ".workbench", help="Local library and run evidence"
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required.")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    project = args.project.expanduser().resolve()
    storage = args.storage.expanduser().resolve()
    if not project.is_dir():
        parser.error(f"Project folder does not exist: {project}")
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        parser.error("Install Node.js 22 or newer with npm, then run this command again.")
    try:
        node_major = int(
            subprocess.check_output(
                [node, "-p", "process.versions.node.split('.')[0]"], text=True
            ).strip()
        )
        if node_major < 22:
            parser.error("Node.js 22 or newer is required to build the bundled documentation.")
        environment = ROOT / ".venv"
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            print("==> Creating .venv", flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        env = dict(os.environ)
        env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = str(ROOT / "src") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        stamp = environment / "workbench-local-dependencies.json"
        try:
            installed = json.loads(stamp.read_text())
            if not isinstance(installed, dict):
                installed = {}
        except (OSError, ValueError):
            installed = {}
        python_key = fingerprint(ROOT / "pyproject.toml")
        if installed.get("python") != python_key:
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-e",
                    str(ROOT),
                ],
                env=env,
            )
            installed["python"] = python_key
            stamp.write_text(json.dumps(installed, indent=2) + "\n")
        for name in ("frontend", "docs-site"):
            directory = ROOT / name
            key = fingerprint(directory / "package.json", directory / "package-lock.json")
            if (
                installed.get(name) != key
                or not (directory / "node_modules" / ".package-lock.json").is_file()
            ):
                run([npm, "ci"], cwd=directory, env=env)
                installed[name] = key
                stamp.write_text(json.dumps(installed, indent=2) + "\n")
            run([npm, "run", "build"], cwd=directory, env=env)
        command = [
            str(python),
            "-m",
            "release_workbench.interfaces.cli",
            "serve",
            "--project",
            str(project),
            "--storage",
            str(storage),
            "--port",
            str(args.port),
        ]
        if args.no_open:
            command.append("--no-open")
        print(f"\n==> Workbench: http://127.0.0.1:{args.port}/ · stop with Ctrl+C", flush=True)
        run(command, env=env)
        return 0
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as error:
        print(
            f"Local startup stopped: command exited with status {error.returncode}.",
            file=sys.stderr,
        )
        return error.returncode if error.returncode > 0 else 1
    except OSError as error:
        print(f"Local startup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
