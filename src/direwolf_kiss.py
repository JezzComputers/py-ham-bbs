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

config = AX25Config("NOCALL", 0, "VK3ETH", 0)
builder = AX25FrameBuilder(config)

def setuser():
    while True:
        mainuser = input("WHO ARE YOU >>> ").upper()
        if mainuser == "EXIT":
            sys.exit(0)
        print()
        if not (mainuser.startswith("VK3") and len(mainuser) == 6):
                print("Invalid user try again")
                continue
        return mainuser

def setdestination():
    while True:
        print("Who would you like to message")
        user = input("CALLSIGN >>> ").strip().upper()
        if user == "EXIT":
            sys.exit(0)
        if not (user.startswith("VK3") and len(user) == 6):
                print("Invalid user try again")
                continue
        return user


def main() -> None:
    use_color()

    try:
        tx_socket: socket.socket = kiss_connect()
        rx_socket: socket.socket = kiss_connect()
    except Exception as e:
        print(f"{MAGENTA}KISS connect failed:{RESET} {e}")
        sys.exit(1)

    # default builder so listener can start
    config = AX25Config("NOCALL", 0, "VK3ETH", 0)
    builder = AX25FrameBuilder(config)

    threading.Thread(target=listener, args=(rx_socket, builder), daemon=True).start()

    print(f"{GREEN}KISS console ready (PTT handled by Direwolf).{RESET}")
    
    mainuser = setuser()
    user = setdestination()
    while True:
        try:
            print()
            print(f"{BLUE}type (differnt) to change to a differnt user{RESET}")
            print()
            print("Type your message and press Enter.")
            msg = input("MESSAGE >>> ").strip()
            print()

            if msg == "differnt":
                user = setdestination()
            elif msg == "exit":
                sys.exit(0)
            elif msg == "EXIT":
                sys.exit(0)
            else:
                config = AX25Config(user, 0, mainuser, 0)
                builder = AX25FrameBuilder(config)

                send_frame(tx_socket, msg, builder)
                
             
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)


            
if __name__ == "__main__":
    main()