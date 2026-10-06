"""Runs the mock Z-Wave network (tests/mock/network.mjs) as a subprocess and talks to it.

The network is zwave-js's own mock controller and mock nodes, with a real zwave-js driver and a real
zwave-js-server in front: the integration connects to it exactly as to a real server. Needs Node.js and
`npm ci --prefix tests/mock`.
"""

import asyncio
import contextlib
import itertools
import json
import socket
from pathlib import Path
from typing import Any, Self

MOCK_DIR = Path(__file__).parent / "mock"
HOME_ID = 0x7E570001  # the mock controller's home id


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockNetwork:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes = nodes
        self.port = free_port()
        self.url = f"ws://127.0.0.1:{self.port}"
        self._process: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()

    async def start(self, serve: bool = True) -> Self:
        if not (MOCK_DIR / "node_modules").exists():
            raise RuntimeError("mock network not installed: run `npm ci --prefix tests/mock`")
        self._process = await asyncio.create_subprocess_exec(
            "node",
            str(MOCK_DIR / "network.mjs"),
            json.dumps({"nodes": self.nodes}),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            limit=2**20,
        )
        line = await asyncio.wait_for(self._stdout.readline(), 60)
        if json.loads(line or b"{}").get("ready") is not True:
            raise RuntimeError(f"mock network did not start: {line!r}")
        if serve:
            await self.serve()
        return self

    @property
    def _stdout(self) -> asyncio.StreamReader:
        assert self._process is not None and self._process.stdout is not None
        return self._process.stdout

    async def call(self, cmd: str, **args: Any) -> dict[str, Any]:
        assert self._process is not None and self._process.stdin is not None
        async with self._lock:
            request_id = next(self._ids)
            self._process.stdin.write(json.dumps({"id": request_id, "cmd": cmd, **args}).encode() + b"\n")
            await self._process.stdin.drain()
            reply = json.loads(await asyncio.wait_for(self._stdout.readline(), 30))
        if not reply.get("ok"):
            raise RuntimeError(f"mock network {cmd} failed: {reply.get('error')}")
        return reply["result"]

    async def serve(self) -> None:
        """Start (or restart) zwave-js-server on this network's port."""
        await self.call("server", port=self.port)

    async def drop_server(self) -> None:
        """Stop zwave-js-server: connected clients lose their connection, the network itself keeps running."""
        await self.call("drop_server")

    async def join(self, node: int, kind: str, **options: Any) -> dict[str, str]:
        """Make a node wait for inclusion; returns its S2 `pin` and `dsk`, as printed on a real device's label."""
        return await self.call("join", node=node, kind=kind, **options)

    async def report(self, node: int, kind: str, value: Any) -> None:
        await self.call("report", node=node, kind=kind, value=value)

    async def silence(self, node: int) -> None:
        await self.call("silence", node=node)

    async def reject(self, node: int) -> None:
        """The node refuses the commands it gets (a supervised command is answered with a Fail status)."""
        await self.call("reject", node=node)

    async def fail(self, node: int) -> None:
        await self.call("fail", node=node)

    async def revive(self, node: int) -> None:
        await self.call("revive", node=node)

    async def exclude(self, node: int) -> None:
        await self.call("exclude", node=node)

    async def node_ids(self) -> list[int]:
        return (await self.call("nodes"))["nodes"]

    async def frames(self, node: int) -> list[str]:
        """The CC commands the node received, by class name (e.g. `IndicatorCCSet`)."""
        return (await self.call("frames", node=node))["frames"]

    async def stop(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        with contextlib.suppress(RuntimeError, ConnectionError, TimeoutError, json.JSONDecodeError):
            await self.call("stop")
        try:
            await asyncio.wait_for(self._process.wait(), 10)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()
