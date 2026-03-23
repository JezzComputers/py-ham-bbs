import socket
import sys
import threading
from pathlib import Path

# Ensure `src` is on sys.path so `lib` package imports work
sys.path.insert(0, str(Path(__file__).parent))

from lib.ax25 import (
	AX25FrameBuilder,
	AX25FrameConfig,
	InvalidAX25Error,
	is_valid_callsign,
)
from lib.kiss import InvalidKISSError, KISSFrameBuilder, KISSFrameConfig
from lib.terminal import (
	BLUE,
	BRIGHT_BLACK,
	BRIGHT_RED,
	BRIGHT_YELLOW,
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


def send_frame(sock: socket.socket, text: str, ax25_builder: AX25FrameBuilder, kiss_builder: KISSFrameBuilder) -> None:
	"""Build a KISS frame from `text` then add AX.25 and send it to Direwolf."""
	payload: bytes = text.encode("utf-8")
	frame: bytes = ax25_builder.build_ax25_frame(payload)
	kiss_frame: bytes = kiss_builder.build_kiss_frame(frame)
	sock.sendall(kiss_frame)
	print(f"{GREEN}[TX]{RESET} {text}")


def listener(sock: socket.socket, kiss_builder: KISSFrameBuilder, ax25_builder: AX25FrameBuilder) -> None:
	buffer = bytearray()

	while True:
		try:
			chunk = sock.recv(4096)
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
				frame = buffer[: end + 1]
				del buffer[: end + 1]

				if len(frame) <= 3:
					continue

				print(f"{BLUE}[KISS FRAME]{RESET} {frame.hex()}")

				try:
					ax25_frame: bytes = kiss_builder.decode_kiss_frame(bytes(frame))
					res: tuple[str, str, str] | None = ax25_builder.decode_ax25_frame(ax25_frame)

				except InvalidKISSError as e:
					print(f"{MAGENTA}[DECODED]{RESET} <invalid KISS frame: {e}>")
					continue

				except InvalidAX25Error as e:
					print(f"{MAGENTA}[DECODED]{RESET} <invalid AX.25 frame: {e}>")
					continue

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
		direwolf_socket: socket.socket = kiss_connect()
	except OSError as e:
		print(f"{MAGENTA}KISS connect failed:{RESET} {e}")
		sys.exit(1)

	while True:
		conf_msg: list[str] = input(f"{BRIGHT_BLACK}ENTER: DESTCALL SRCCALL\nENTER:{RESET} ").upper().split()
		if len(conf_msg) == 2 and all(is_valid_callsign(c) for c in conf_msg):
			break
		print(f"{BRIGHT_RED}Invalid response.{RESET}")

	ax25_config = AX25FrameConfig(f"{conf_msg[0]:6.6s}", 0, f"{conf_msg[1]:6.6s}", 0)
	ax25_builder = AX25FrameBuilder(ax25_config)
	kiss_config = KISSFrameConfig(b"\x00")
	kiss_builder = KISSFrameBuilder(kiss_config)

	threading.Thread(target=listener, args=(direwolf_socket, kiss_builder, ax25_builder), daemon=True).start()

	print(f"{GREEN}KISS console ready.{RESET}\n{BRIGHT_BLACK}To show addresses, type /SHOW\nTo change addresses, type /ADDR DESTCALL SRCCALL{RESET}")

	while True:
		try:
			msg: str = input(">>> ")
			if msg.strip().upper().startswith("/ADDR"):
				parts: list[str] = msg.upper().split()
				if len(parts) == 3:
					dest, src = parts[1], parts[2]
					if not (is_valid_callsign(dest) and is_valid_callsign(src)):
						print(f"{BRIGHT_RED}Invalid callsign in command. Callsigns must be 1-6 characters, letters and numbers only.{RESET}")
						continue
					ax25_builder.config = AX25FrameConfig(f"{dest:6.6s}", 0, f"{src:6.6s}", 0)
					print(f"{BRIGHT_YELLOW}Updated addresses:{RESET} DEST={dest}, SRC={src}")
				else:
					print(f"{BRIGHT_BLACK}Usage: /ADDR DESTCALL SRCCALL{RESET}")
			elif msg.strip().upper() == "/SHOW":
				print(f"{BRIGHT_YELLOW}DEST={RESET}{ax25_builder.config.dest_call}{BRIGHT_YELLOW} SRC={RESET}{ax25_builder.config.src_call}")
			elif msg.strip():
				send_frame(direwolf_socket, msg, ax25_builder, kiss_builder)
		except KeyboardInterrupt:
			print("\nExiting.")
			sys.exit(0)


if __name__ == "__main__":
	main()
