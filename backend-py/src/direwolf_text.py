import socket
import sys
import threading
from pathlib import Path

# Ensure `src` is on sys.path so `lib` package imports work
sys.path.insert(0, str(Path(__file__).parent))

from lib.ax25 import AX25FrameBuilder, AX25FrameConfig, is_valid_callsign
from lib.direwolf import kiss_connect, listener, send_frame
from lib.kiss import KISSFrameBuilder, KISSFrameConfig
from lib.terminal import BRIGHT_BLACK, BRIGHT_RED, BRIGHT_YELLOW, GREEN, MAGENTA, RESET, use_color


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
	kiss_config = KISSFrameConfig(0x00)
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
						print(f"{BRIGHT_RED}Invalid callsign in command. Please enter a valid AX.25 callsign.{RESET}")
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
