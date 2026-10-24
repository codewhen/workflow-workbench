"""Bounded process execution with cancellation of descendants on every platform."""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from release_workbench.domain.values import ContractError

from .host import process_environment, program_arguments

MAX_OUTPUT = 1024 * 1024


class ProcessAdapter:
    async def run(
        self,
        argv: list[str],
        cwd: Path,
        environment: dict[str, str],
        payload: dict[str, Any] | None,
        log: Callable[[str], None],
        check: Callable[[], None],
        timeout: float = 3600,
    ) -> dict[str, Any]:
        if not argv or any(not isinstance(arg, str) for arg in argv):
            raise ContractError("Program arguments must be a nonempty list of strings.")
        options: dict[str, Any] = (
            {"start_new_session": True} if os.name != "nt" else {"creationflags": 512}
        )
        environment = process_environment(environment)
        arguments = program_arguments(argv, cwd, environment)
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )
        streams: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        sizes = {"stdout": 0, "stderr": 0}

        async def read(name: str, reader: asyncio.StreamReader | None) -> None:
            assert reader is not None
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while chunk := await reader.read(4096):
                sizes[name] += len(chunk)
                streams[name].extend(chunk)
                if len(streams[name]) > MAX_OUTPUT // 2:
                    del streams[name][: -MAX_OUTPUT // 2]
                log(decoder.decode(chunk))
            remainder = decoder.decode(b"", final=True)
            if remainder:
                log(remainder)

        async def send() -> None:
            if process.stdin:
                try:
                    if payload is not None:
                        process.stdin.write(json.dumps(payload, allow_nan=False).encode())
                        await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    # Successful programs may exit without consuming optional JSON stdin.
                    # Their exit code and captured output still determine the result.
                    pass
                finally:
                    process.stdin.close()

        tasks = [
            asyncio.create_task(read("stdout", process.stdout)),
            asyncio.create_task(read("stderr", process.stderr)),
            asyncio.create_task(send()),
            asyncio.create_task(process.wait()),
        ]
        descendants: dict[int, psutil.Process] = {}
        start = asyncio.get_running_loop().time()
        try:
            while not all(task.done() for task in tasks):
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        descendants[child.pid] = child
                except psutil.Error:
                    pass
                check()
                if asyncio.get_running_loop().time() - start >= timeout:
                    raise TimeoutError(f"Process exceeded {timeout:g} seconds.")
                for task in tasks:
                    if task.done() and not task.cancelled():
                        error = task.exception()
                        if error is not None:
                            raise error
                await asyncio.sleep(0.03)
            await asyncio.gather(*tasks)
            result: dict[str, Any] = {
                "exit_code": process.returncode,
                "truncated": any(sizes[name] > len(streams[name]) for name in streams),
                "stdout_truncated": sizes["stdout"] > len(streams["stdout"]),
                "stderr_truncated": sizes["stderr"] > len(streams["stderr"]),
                "output_bytes": dict(sizes),
                **{key: value.decode("utf-8", "replace") for key, value in streams.items()},
            }
            if process.returncode:
                raise ContractError(
                    f"Program exited {process.returncode}: {result['stderr'][-1000:]}"
                )
            return result
        finally:
            await self._cleanup(process, list(descendants.values()))
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _cleanup(
        self, process: asyncio.subprocess.Process, tracked: list[psutil.Process]
    ) -> None:
        try:
            descendants = psutil.Process(process.pid).children(recursive=True)
        except psutil.Error:
            descendants = []
        for child in reversed([*tracked, *descendants]):
            try:
                child.kill()
            except psutil.Error:
                pass
        if sys.platform != "win32":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()
        await process.wait()

    async def structured(
        self,
        request: dict[str, Any],
        cwd: Path,
        environment: dict[str, str],
        log: Callable[[str], None],
        check: Callable[[], None],
        timeout: float,
    ) -> Any:
        with tempfile.TemporaryDirectory(prefix="workbench-return-") as directory:
            result = Path(directory) / "result.json"
            await self.run(
                [
                    sys.executable,
                    "-u",
                    str(Path(__file__).with_name("worker.py")),
                    str(result),
                ],
                cwd,
                environment,
                request,
                log,
                check,
                timeout,
            )
            if not result.exists() or result.stat().st_size > MAX_OUTPUT:
                raise ContractError("Structured result is missing or exceeds 1 MiB.")
            value = json.loads(result.read_text(encoding="utf-8"))
            if "error" in value:
                raise ContractError(value["error"])
            return value["value"]
