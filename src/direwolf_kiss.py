import os
import sys
import socket
import threading
import sys as _sys
import time


# Ensure `src` is on sys.path so `lib` package imports work when running
# this script directly from the repository root.
sys.path.insert(0, os.path.dirname(__file__))

from lib.terminal import (
    use_color,
    YELLOW,
    GREEN,
    CYAN,
    BLUE,
    MAGENTA,
    RESET,
)
from lib.ax25 import (
    AX25Config,
    AX25FrameBuilder,
)

# Configuration
KISS_HOST = "127.0.0.1"
KISS_PORT = 8001

RIGCTL_HOST = "127.0.0.1"
RIGCTL_PORT = 4532

# When testing, set this to True to use an in-process dummy rig
USE_DUMMY_RIG = False

# Extra PTT hold time (seconds) to keep PTT asserted after estimated TX time.
PTT_EXTRA_HOLD = 0

# FX.25 usage: set this to True if you're transmitting with FX.25 (Direwolf FEC).
# We avoid reading direwolf.conf here; this flag is explicit and simple.
FX25_ENABLED = True

# TX time multiplier: can be overridden with env `TX_TIME_MULTIPLIER`.
# If not set, use 1.5 when FX25 is enabled, otherwise 1.0.
TX_TIME_MULTIPLIER = 3 if FX25_ENABLED else 1.0


def kiss_connect(host: str = KISS_HOST, port: int = KISS_PORT) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s


def rigctl_connect(host: str = RIGCTL_HOST, port: int = RIGCTL_PORT) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s


class DummyRig:
    def __init__(self):
        self._last_cmd = b""

    def send(self, data: bytes):
        self._last_cmd = data

    def recv(self, n: int = 128) -> bytes:
        try:
            cmd = self._last_cmd.decode(errors="ignore").strip()
        except Exception:
            cmd = ""

        if cmd.startswith("T "):
            parts = cmd.split()
            if len(parts) > 1 and parts[1] == "1":
                return b"OK PTT ON\n"
            else:
                return b"OK PTT OFF\n"

        return b"OK\n"


def rigctl_cmd(rig, cmd: str) -> str:
    rig.send((cmd + "\n").encode())
    return rig.recv(128).decode(errors="ignore")


def ptt_on(rig) -> None:
    rigctl_cmd(rig, "T 1")


def ptt_off(rig) -> None:
    rigctl_cmd(rig, "T 0")


def decode_ax25(frame: bytes, builder: AX25FrameBuilder | None = None):
    """Compatibility wrapper that decodes an AX.25/KISS frame.

    If `builder` is provided, delegates to its `decode` method. Otherwise
    uses a temporary builder to perform decoding.
    """
    if builder is not None:
        return builder.decode(frame)

    # Temporary builder; decoding doesn't depend on config, so use simple defaults
    temp_cfg = AX25Config("APRS", 0, "N0CALL", 0)
    return AX25FrameBuilder(temp_cfg).decode(frame)


def send_frame(tx_socket: socket.socket, rig, text: str, builder: AX25FrameBuilder) -> None:
    payload = text.encode("utf-8")

    frame = builder.build_ax25_frame(payload)
    tx_time = builder.estimate_tx_time(frame) * TX_TIME_MULTIPLIER

    kiss_frame = builder.build_kiss_frame(frame)

    print(f"{YELLOW}[PTT] ON for {tx_time:.2f} sec{RESET}")
    ptt_on(rig)

    tx_socket.send(kiss_frame)
    print(f"{GREEN}[TX]{RESET} {text}")

    # Keep PTT asserted for estimated tx time plus optional extra hold
    time.sleep(tx_time + PTT_EXTRA_HOLD)

    ptt_off(rig)
    print(f"{YELLOW}[PTT] OFF{RESET}")


def listener(rx_socket: socket.socket, builder: AX25FrameBuilder) -> None:
    while True:
        try:
            data = rx_socket.recv(4096)
            if not data:
                print(f"{MAGENTA}RX socket closed{RESET}")
                break

            print(f"\n{CYAN}[RX RAW]{RESET} {data.hex()}")

            dest, src, text = decode_ax25(data, builder)

            if dest is not None:
                print(f"{BLUE}[DECODED]{RESET} {src} → {dest} : {text}")

            print(">>> ", end="", flush=True)

        except Exception as e:
            print(f"{MAGENTA}RX error:{RESET} {e}")
            break


def main() -> None:
    use_color()

    try:
        tx_socket = kiss_connect()
        rx_socket = kiss_connect()
    except Exception as e:
        print(f"{MAGENTA}KISS connect failed:{RESET} {e}")
        _sys.exit(1)

    rig = DummyRig() if USE_DUMMY_RIG else rigctl_connect()

    # Configure addresses here
    config = AX25Config("VK3ETH", 0, "VK3JEZ", 0)
    builder = AX25FrameBuilder(config)

    threading.Thread(target=listener, args=(rx_socket, builder), daemon=True).start()

    print(f"{GREEN}KISS + rigctld test console ready.{RESET}")
    print("Type messages and press Enter.\n")

    while True:
        try:
            msg = input(">>> ")
            if msg.strip():
                send_frame(tx_socket, rig, msg, builder)
        except KeyboardInterrupt:
            print("\nExiting.")
            _sys.exit(0)


if __name__ == "__main__":
    main()
