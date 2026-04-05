import asyncio
from datetime import datetime, UTC
from websockets.asyncio.server import serve, ServerConnection
import logging
from uuid import uuid7
import json

logger = logging.getLogger(__name__)

async def handler(websocket: ServerConnection) -> None:
    logger.log(logging.INFO, "Client connected: %s", websocket.remote_address)
    
    try:
        while True:
            await websocket.send(json.dumps({
                "timestamp": datetime.now(UTC).isoformat(),
                "uuid": str(uuid7())
            }))
            await asyncio.sleep(1)
    
    
    except Exception as e:
        logger.log(logging.ERROR, "Error in handler: %s", e)
    finally:
        logger.log(logging.INFO, "Client disconnected: %s", websocket.remote_address)


async def main() -> None:
    async with serve(handler, 'localhost', 8765) as server:
        print("Server started on ws://localhost:8765")
        await server.serve_forever()

asyncio.run(main())