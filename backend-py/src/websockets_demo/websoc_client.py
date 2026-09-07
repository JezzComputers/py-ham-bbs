import asyncio

from websockets.asyncio.client import connect


async def listen_sock() -> None:
	async with connect("ws://localhost:8765") as websocket:
		print("Connected to ws://localhost:8765")

		async for message in websocket:
			print(f"The server says: {message}")


if __name__ == "__main__":
	try:
		asyncio.run(listen_sock())
	except KeyboardInterrupt:
		print("\nClient stopped.")
