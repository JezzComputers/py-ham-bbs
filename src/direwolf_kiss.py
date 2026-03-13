import socket
import sys
import threading
from pathlib import Path

# Ensure `src` is on sys.path so `lib` package imports work
sys.path.insert(0, str(Path(__file__).parent))

from lib.ax25 import (
	AX25Config,
	AX25FrameBuilder,
)
from lib.terminal import (
	BLUE,
	CYAN,
	GREEN,
	MAGENTA,
	RESET,
	use_color,
)


def kiss_connect(host: str = "127.0.0.1", port: int = 8001) -> socket.socket:
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect((host, port))
	return s


def send_frame(tx_socket: socket.socket, text: str, builder: AX25FrameBuilder) -> None:
	"""Build a KISS frame from `text` and send it to Direwolf."""
	payload: bytes = text.encode("utf-8")
	frame: bytes = builder.build_ax25_frame(payload)
	kiss_frame: bytes = builder.build_kiss_frame(frame)

	tx_socket.sendall(kiss_frame)
	print(f"{GREEN}[TX]{RESET} {text}")


def listener(rx_socket: socket.socket, builder: AX25FrameBuilder) -> None:
	buffer = bytearray()

	while True:
		try:
			chunk = rx_socket.recv(4096)
			if not chunk:
				print(f"{MAGENTA}RX socket closed{RESET}")
				break

			print(f"\n{CYAN}[RX RAW]{RESET} {chunk.hex()}")
			buffer.extend(chunk)

			while True:
				# Find first FEND
				try:
					start = buffer.index(0xC0)
				except ValueError:
					# No FEND at all → drop everything
					buffer.clear()
					break

				# Drop garbage before FEND
				if start > 0:
					del buffer[:start]

				# Look for closing FEND
				try:
					end = buffer.index(0xC0, 1)
				except ValueError:
					# No complete frame yet
					break

				# Extract full frame
				frame = buffer[:end + 1]
				del buffer[:end + 1]

				if len(frame) <= 3:
					continue

				print(f"{BLUE}[KISS FRAME]{RESET} {frame.hex()}")

				res = builder.decode(bytes(frame))
				if res is None:
					print(f"{MAGENTA}[DECODED]{RESET} <invalid frame>")
				else:
					dest, src, text = res
					print(f"{BLUE}[DECODED]{RESET} {src} → {dest} : {text}")

			print(">>> ", end="", flush=True)

		except OSError as e:
			print(f"{MAGENTA}RX error:{RESET} {e}")
			break


def main() -> None:
	use_color()

	try:
		tx_socket: socket.socket = kiss_connect()
		rx_socket: socket.socket = kiss_connect()
	except OSError as e:
		print(f"{MAGENTA}KISS connect failed:{RESET} {e}")
		sys.exit(1)

	# Configure addresses here
	config = AX25Config("VK3ETH", 0, "VK3JEZ", 0)
	builder = AX25FrameBuilder(config)

	threading.Thread(target=listener, args=(rx_socket, builder), daemon=True).start()

	print(f"{GREEN}KISS console ready (PTT handled by Direwolf).{RESET}")
	print("Type messages and press Enter.\n")

	while True:
		try:
			msg = input(">>> ")
			if msg.strip():
				send_frame(tx_socket, msg, builder)
		except KeyboardInterrupt:
			print("\nExiting.")
			sys.exit(0)


if __name__ == "__main__":
	main()
