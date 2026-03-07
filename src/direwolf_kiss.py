from pathlib import Path
import threading
import socket
import sys


# Ensure `src` is on sys.path so `lib` package imports work
sys.path.insert(0, str(Path(__file__).parent))

from lib.terminal import (
    use_color,
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
    while True:
        try:
            data: bytes = rx_socket.recv(4096)
            if not data:
                print(f"{MAGENTA}RX socket closed{RESET}")
                break

            print(f"\n{CYAN}[RX RAW]{RESET} {data.hex()}")

            res = builder.decode(data)
            if res is None:
                print(f"{MAGENTA}[DECODED]{RESET} <invalid frame>")
            else:
                dest, src, text = res
                print(f"{BLUE}[DECODED]{RESET} {src} → {dest} : {text}")

            print(">>> ", end="", flush=True)

        except Exception as e:
            print(f"{MAGENTA}RX error:{RESET} {e}")
            break


def main() -> None:
    use_color()

    try:
        tx_socket: socket.socket = kiss_connect()
        rx_socket: socket.socket = kiss_connect()
    except Exception as e:
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
