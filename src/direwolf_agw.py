import contextlib
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

# Ensure `src` is on sys.path so `lib` package imports work
sys.path.insert(0, str(Path(__file__).parent))

from lib.agw import AGWClient, AGWFrame, InvalidAGWError, normalize_call, parse_port_info
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


DEFAULT_AGW_HOST = "127.0.0.1"
DEFAULT_AGW_PORT = 8000
DEFAULT_AUTO_CONNECT = False


@dataclass(slots=True)
class SessionState:
	connected: bool
	connect_pending: bool
	disconnect_pending: bool
	remote_call: str


def _status_text(state: SessionState) -> str:
	if state.disconnect_pending:
		return "disconnecting"
	if state.connected:
		return "connected"
	if state.connect_pending:
		return "connecting"
	return "idle"


def _print_prompt() -> None:
	print(">>> ", end="", flush=True)


def listener(client: AGWClient, state: SessionState, state_lock: threading.Lock) -> None:
	while True:
		try:
			frame: AGWFrame = client.recv_frame()
		except ConnectionError as e:
			with state_lock:
				state.connected = False
				state.connect_pending = False
				state.disconnect_pending = False
			print(f"\n{MAGENTA}AGW socket closed:{RESET} {e}")
			break
		except OSError as e:
			with state_lock:
				state.connected = False
				state.connect_pending = False
				state.disconnect_pending = False
			print(f"\n{MAGENTA}AGW receive error:{RESET} {e}")
			break
		except InvalidAGWError as e:
			print(f"\n{MAGENTA}AGW decode error:{RESET} {e}")
			continue

		header = frame.header
		kind = header.datakind

		if kind == "R":
			if len(frame.data) >= 8:
				major = int.from_bytes(frame.data[:4], "little", signed=False)
				minor = int.from_bytes(frame.data[4:8], "little", signed=False)
				print(f"\n{BLUE}[AGW VERSION]{RESET} {major}.{minor}")
			else:
				print(f"\n{BLUE}[AGW VERSION]{RESET} raw={frame.data.hex()}")

		elif kind == "G":
			ports = parse_port_info(frame.data)
			if ports:
				print(f"\n{BLUE}[AGW PORTS]{RESET}")
				for port_desc in ports:
					print(f"  - {port_desc}")
			else:
				decoded = frame.data.decode("ascii", errors="replace").strip(chr(0))
				print(f"\n{BLUE}[AGW PORTS]{RESET} {decoded}")

		elif kind == "X":
			ok = frame.data[:1] == b"\x01"
			status = "registered" if ok else "registration failed"
			print(f"\n{BLUE}[AGW REGISTER]{RESET} {status} for {header.call_from}")

		elif kind == "C":
			with state_lock:
				state.connected = True
				state.connect_pending = False
				state.disconnect_pending = False
				state.remote_call = header.call_from
			info = frame.data.decode("utf-8", errors="replace").strip("\x00\r\n")
			print(f"\n{GREEN}[CONNECTED]{RESET} {info or f'{header.call_from} <-> {header.call_to}'}")

		elif kind == "D":
			text = frame.data.decode("utf-8", errors="replace")
			print(f"\n{CYAN}[RX]{RESET} {header.call_from} : {text}")

		elif kind == "d":
			with state_lock:
				state.connected = False
				state.connect_pending = False
				state.disconnect_pending = False
				if header.call_from:
					state.remote_call = header.call_from
			info = frame.data.decode("utf-8", errors="replace").strip("\x00\r\n")
			print(f"\n{MAGENTA}[DISCONNECTED]{RESET} {info or f'{header.call_from} <-> {header.call_to}'}")

		elif kind in {"I", "S", "T", "U", "K", "Y", "y", "g"}:
			decoded = frame.data.decode("utf-8", errors="replace").strip("\x00")
			print(f"\n{BRIGHT_BLACK}[AGW {kind}]{RESET} {decoded or frame.data.hex()}")

		else:
			print(f"\n{BRIGHT_BLACK}[AGW {kind}]{RESET} {frame.data.hex()}")

		_print_prompt()


def main() -> None:
	use_color()
	agw_host = os.getenv("DW_AGW_HOST", DEFAULT_AGW_HOST)
	agw_port = int(os.getenv("DW_AGW_PORT", str(DEFAULT_AGW_PORT)))
	auto_connect = os.getenv("DW_AUTO_CONNECT", "0").strip().lower() in {"1", "true", "yes", "on"}

	try:
		client = AGWClient.connect(host=agw_host, port=agw_port)
	except OSError as e:
		print(f"{MAGENTA}AGW connect failed ({agw_host}:{agw_port}):{RESET} {e}")
		sys.exit(1)

	while True:
		conf_msg = input(f"{BRIGHT_BLACK}ENTER: MYCALL [REMOTECALL]\nENTER:{RESET} ").upper().split()
		if len(conf_msg) not in {1, 2}:
			print(f"{BRIGHT_RED}Invalid response.{RESET}")
			continue
		try:
			my_call = normalize_call(conf_msg[0])
			remote_call = normalize_call(conf_msg[1]) if len(conf_msg) == 2 else ""
		except InvalidAGWError as e:
			print(f"{BRIGHT_RED}Invalid callsign: {e}{RESET}")
			continue
		break

	state = SessionState(
		connected=False,
		connect_pending=False,
		disconnect_pending=False,
		remote_call=remote_call,
	)
	state_lock = threading.Lock()

	try:
		client.request_version()
		client.request_port_info()
		client.register_callsign(my_call)
		if auto_connect and remote_call:
			with state_lock:
				state.connect_pending = True
				state.disconnect_pending = False
			client.connect_station(my_call, remote_call)
	except (InvalidAGWError, OSError) as e:
		with state_lock:
			state.connect_pending = False
		print(f"{MAGENTA}AGW setup failed:{RESET} {e}")
		client.close()
		sys.exit(1)

	threading.Thread(target=listener, args=(client, state, state_lock), daemon=True).start()

	print(
		f"{GREEN}AGW connected-mode console ready.{RESET}\n"
		f"{BRIGHT_BLACK}AGW endpoint:{RESET} {agw_host}:{agw_port}\n"
		f"{BRIGHT_BLACK}Auto-connect:{RESET} {auto_connect and bool(remote_call)}\n"
		f"{BRIGHT_BLACK}Commands:{RESET} /SHOW /CONNECT [CALL] /SETREMOTE CALL /DISCONNECT /QUIT"
	)

	while True:
		try:
			msg = input(">>> ")
		except KeyboardInterrupt:
			print("\nExiting.")
			break

		clean = msg.strip()
		upper = clean.upper()

		if clean == "":
			continue

		try:
			if upper == "/SHOW":
				with state_lock:
					status = _status_text(state)
					remote_now = state.remote_call
					connected_now = state.connected
				print(
					f"{BRIGHT_YELLOW}MY={RESET}{my_call} "
					f"{BRIGHT_YELLOW}REMOTE={RESET}{remote_now or '(unset)'} "
					f"{BRIGHT_YELLOW}CONNECTED={RESET}{connected_now} "
					f"{BRIGHT_YELLOW}STATE={RESET}{status}"
				)

			elif upper.startswith("/SETREMOTE"):
				parts = clean.split()
				if len(parts) != 2:
					print(f"{BRIGHT_BLACK}Usage: /SETREMOTE CALL[-SSID]{RESET}")
					continue
				new_remote = normalize_call(parts[1])
				with state_lock:
					if state.connected or state.connect_pending or state.disconnect_pending:
						print(f"{BRIGHT_RED}Cannot change remote while session is active or transitioning.{RESET}")
						continue
					state.remote_call = new_remote
				print(f"{BRIGHT_YELLOW}Remote set to {new_remote}.{RESET}")

			elif upper.startswith("/CONNECT"):
				parts = clean.split()
				new_remote: str
				if len(parts) == 1:
					with state_lock:
						new_remote = state.remote_call
					if not new_remote:
						print(f"{BRIGHT_BLACK}Usage: /CONNECT CALL[-SSID]{RESET}")
						continue
				elif len(parts) == 2:
					new_remote = normalize_call(parts[1])
				else:
					print(f"{BRIGHT_BLACK}Usage: /CONNECT CALL[-SSID]{RESET}")
					continue

				reason: str | None = None
				with state_lock:
					if state.disconnect_pending:
						reason = "Disconnect is in progress. Please wait."
					elif state.connected and state.remote_call == new_remote:
						reason = f"Already connected to {new_remote}."
					elif state.connected:
						reason = f"Already connected to {state.remote_call}. Use /DISCONNECT first."
					elif state.connect_pending and state.remote_call == new_remote:
						reason = f"Connection to {new_remote} already in progress."
					elif state.connect_pending:
						reason = f"Connection to {state.remote_call} already in progress. Use /DISCONNECT first."
					else:
						state.remote_call = new_remote
						state.connect_pending = True
						state.disconnect_pending = False

				if reason is not None:
					print(f"{BRIGHT_RED}{reason}{RESET}")
					continue

				try:
					client.connect_station(my_call, new_remote)
				except (InvalidAGWError, OSError):
					with state_lock:
						state.connect_pending = False
					raise

				print(f"{BRIGHT_YELLOW}Connecting to {new_remote}...{RESET}")

			elif upper == "/DISCONNECT":
				with state_lock:
					remote_now = state.remote_call
					connected_now = state.connected
					connect_pending_now = state.connect_pending
					disconnect_pending_now = state.disconnect_pending

				if not remote_now:
					print(f"{BRIGHT_RED}No remote callsign selected.{RESET}")
					continue
				if disconnect_pending_now:
					print(f"{BRIGHT_RED}Disconnect already in progress.{RESET}")
					continue
				if not connected_now and not connect_pending_now:
					print(f"{BRIGHT_RED}Already disconnected.{RESET}")
					continue

				with state_lock:
					state.disconnect_pending = True
					state.connect_pending = False

				try:
					client.disconnect_station(my_call, remote_now)
				except (InvalidAGWError, OSError):
					with state_lock:
						state.disconnect_pending = False
					raise

				print(f"{BRIGHT_YELLOW}Disconnect requested.{RESET}")

			elif upper == "/QUIT":
				break

			else:
				with state_lock:
					connected_now = state.connected
					disconnect_pending_now = state.disconnect_pending
					remote_now = state.remote_call

				if not connected_now or disconnect_pending_now:
					print(f"{BRIGHT_RED}Not connected. Use /CONNECT CALL first.{RESET}")
					continue
				if not remote_now:
					print(f"{BRIGHT_RED}No remote callsign selected.{RESET}")
					continue
				client.send_connected_data(my_call, remote_now, clean.encode("utf-8"))
				print(f"{GREEN}[TX]{RESET} {clean}")

		except (InvalidAGWError, OSError) as e:
			print(f"{MAGENTA}AGW command error:{RESET} {e}")

	try:
		with state_lock:
			remote_now = state.remote_call
			should_disconnect = (state.connected or state.connect_pending) and not state.disconnect_pending
		if remote_now and should_disconnect:
			client.disconnect_station(my_call, remote_now)
		client.unregister_callsign(my_call)
	except (InvalidAGWError, OSError):
		pass
	finally:
		with contextlib.suppress(OSError):
			client.close()


if __name__ == "__main__":
	main()
