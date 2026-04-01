import asyncio
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from websockets.asyncio.server import serve, ServerConnection


async def handler(websocket: ServerConnection) -> None:
	"""Handles a single client connection."""
	while True:
		now = datetime.now(UTC).isoformat()
		now_local = datetime.now(ZoneInfo("Australia/Melbourne")).isoformat()
		print(f"U-NOW: {now}\nL-NOW: {now_local}")
		await websocket.send(now_local)
		await asyncio.sleep(1)


async def main() -> None:
	async with serve(handler, "0.0.0.0", 8888) as server:  # noqa: S104
		print("Time server started on ws://0.0.0.0:8888")
		await server.serve_forever()


if __name__ == "__main__":
	asyncio.run(main())
