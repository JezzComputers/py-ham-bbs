import asyncio
from websockets.asyncio.client import connect


async def listen_for_time() -> None:
	# Explicitly using the rework's 'connect'
	async with connect("ws://localhost:8888") as websocket:
		print("Connected to ws://localhost:8888")

		async for message in websocket:
			print(f"The server says the time is: {message}")


if __name__ == "__main__":
	try:
		asyncio.run(listen_for_time())
	except KeyboardInterrupt:
		print("\nClient stopped.")
