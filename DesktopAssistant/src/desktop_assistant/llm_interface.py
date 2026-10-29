from __future__ import annotations

import asyncio
from concurrent.futures import Future
from pathlib import Path
from threading import Thread
from typing import Callable

from .client import MCPClient


class MessageSink:
    def __init__(self, excute_path: str = "serve.py") -> None:
        self.client = MCPClient()
        self.excute_path = self._resolve_server_path(excute_path)
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        self._connect_future: Future[None] = asyncio.run_coroutine_threadsafe(
            self.client.connect_to_server(self.excute_path),
            self._loop,
        )

    @staticmethod
    def _resolve_server_path(excute_path: str) -> str:
        candidate = Path(excute_path)
        if candidate.is_absolute():
            return str(candidate)

        local_candidate = Path(__file__).resolve().parent / excute_path
        if local_candidate.exists():
            return str(local_candidate)

        return str(candidate)

    def _run_event_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _submit_async(
        self, query: str, on_status: Callable[[str], None] | None = None,
        conversation_id: int | None = None,
    ) -> str:
        await asyncio.wrap_future(self._connect_future)
        if conversation_id is None:
            return await self.client.process_query(query, on_status=on_status)
        return await self.client.process_query(
            query, on_status=on_status, conversation_id=conversation_id
        )

    def submit(
        self, query: str, on_status: Callable[[str], None] | None = None,
        conversation_id: int | None = None,
    ) -> Future[str]:
        return asyncio.run_coroutine_threadsafe(
            self._submit_async(query, on_status, conversation_id), self._loop
        )
