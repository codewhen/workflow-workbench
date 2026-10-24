"""Verify a wheel installation's offline docs outside the checkout (browser driver is dev-only)."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        type=Path,
        required=True,
        help="Python executable in a clean installed-wheel venv",
    )
    args = parser.parse_args()
    executable = args.python.absolute()
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["PATH"] = str(executable.parent)  # No Node on the installed server's PATH.
    program = """
import json
from pathlib import Path
import release_workbench
from release_workbench.interfaces.server import create_server
root = Path.cwd()
server, app = create_server(root, root / "storage", 0)
print(json.dumps({"port": server.server_port, "package": release_workbench.__file__}), flush=True)
server.serve_forever()
"""
    with tempfile.TemporaryDirectory(prefix="workbench-installed-docs-") as directory:
        process = subprocess.Popen(
            [str(executable), "-c", program],
            cwd=directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout
            line = process.stdout.readline()
            if not line:
                assert process.stderr
                raise RuntimeError(process.stderr.read())
            instance = json.loads(line)
            assert not Path(instance["package"]).is_relative_to(ROOT), (
                "Test selected source checkout rather than installed wheel"
            )
            browser_environment = dict(os.environ)
            browser_environment.pop("PYTHONPATH", None)
            browser_environment["WORKBENCH_DOCS_TEST_URL"] = "http://127.0.0.1:" + str(
                instance["port"]
            )
            subprocess.run(
                ["node", str(ROOT / "docs-site/scripts/test-browser.mjs")],
                cwd=ROOT / "docs-site",
                env=browser_environment,
                check=True,
                timeout=90,
            )
            print(
                "Installed wheel served documentation/search/downloads without Node on server PATH, source imports or external browser networking."
            )
        finally:
            if os.name == "nt":
                process.terminate()
            else:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
