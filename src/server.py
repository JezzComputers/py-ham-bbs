import asyncio
from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosed
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import logging

from platform import python_version_tuple
if int(python_version_tuple()[1]) < 14:
	from uuid6 import uuid7  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
else:
	from uuid import uuid7


logger = logging.getLogger(__name__)


async def handler(websocket: ServerConnection) -> None:
	logger.info("Client connected: %s", websocket.remote_address)
	try:
		while True:
			await websocket.send(json.dumps({"timestamp": datetime.now(ZoneInfo("Australia/Melbourne")).isoformat(), "uuid": str(uuid7())}))  # pyright: ignore[reportUnknownArgumentType]
			await asyncio.sleep(1)
	except ConnectionClosed as e:
		logger.info("Connection closed: %s", e)
	finally:
		logger.info("Client disconnected: %s", websocket.remote_address)


async def main() -> None:
	async with serve(handler, "0.0.0.0", 8765) as server:  # noqa: S104
		print("Time server started on ws://0.0.0.0:8765")
		await server.serve_forever()


if __name__ == "__main__":
	asyncio.run(main())
