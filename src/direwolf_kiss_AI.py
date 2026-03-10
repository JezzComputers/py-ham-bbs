from pathlib import Path
import threading
import socket
import sys
import json
import getpass
import time

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

USER_DB = Path("users.json")


def load_users():
    if not USER_DB.exists():
        return {}
    with open(USER_DB, "r") as f:
        return json.load(f)


def save_users(users):
    with open(USER_DB, "w") as f:
        json.dump(users, f, indent=4)


def valid_callsign(name: str):
    name = name.upper()
    if not name.startswith("VK3"):
        return False
    return len(name) > 3


def kiss_connect(host: str = "127.0.0.1", port: int = 8001) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    return s


def send_frame(tx_socket: socket.socket, text: str, builder: AX25FrameBuilder):
    payload = text.encode("utf-8")
    frame = builder.build_ax25_frame(payload)
    kiss_frame = builder.build_kiss_frame(frame)

    tx_socket.sendall(kiss_frame)
    print(f"{GREEN}[TX]{RESET} {text}")


approval_received = False


def listener(rx_socket, builder):
    global approval_received

    while True:
        try:
            data = rx_socket.recv(4096)
            if not data:
                break

            print(f"\n{CYAN}[RX RAW]{RESET} {data.hex()}")

            res = builder.decode(data)
            if res:
                dest, src, text = res
                print(f"{BLUE}[DECODED]{RESET} {src} → {dest} : {text}")

                if text.strip().lower() == "/yes":
                    approval_received = True

            else:
                print(f"{MAGENTA}[DECODED]{RESET} <invalid frame>")

            print(">>> ", end="", flush=True)

        except Exception as e:
            print("RX error:", e)
            break


def login(tx_socket, builder):

    users = load_users()

    while True:

        user = input("Who are you >>> ").upper()

        if user in users:

            pw = getpass.getpass("Password >>> ")

            if pw == users[user]:
                print(f"{GREEN}Login successful.{RESET}")
                return user
            else:
                print(f"{MAGENTA}Incorrect password.{RESET}")

        else:

            print("User not found.")
            choice = input("Did you misspell or create new? (new/retry) >>> ")

            if choice.lower() != "new":
                continue

            if not valid_callsign(user):
                print("Username must start with VK3***")
                continue

            pw = getpass.getpass("Set password >>> ")

            print("Requesting approval from network...")

            send_frame(tx_socket, f"New user request: {user}. Reply /yes to approve.", builder)

            global approval_received
            approval_received = False

            start = time.time()

            while time.time() - start < 60:
                if approval_received:
                    users[user] = pw
                    save_users(users)
                    print(f"{GREEN}User approved and created!{RESET}")
                    return user
                time.sleep(1)

            print("No approval received. User not created.")


def main():
    use_color()

    try:
        tx_socket = kiss_connect()
        rx_socket = kiss_connect()
    except Exception as e:
        print("KISS connect failed:", e)
        sys.exit(1)

    config = AX25Config("VK3JEZ", 0, "VK3ETH", 0)
    builder = AX25FrameBuilder(config)

    threading.Thread(target=listener, args=(rx_socket, builder), daemon=True).start()

    print(f"{GREEN}KISS console ready (PTT handled by Direwolf).{RESET}")

    user = login(tx_socket, builder)

    print(f"Logged in as {user}")
    print("Type messages and press Enter.\n")

    while True:
        try:
            msg = input(">>> ")

            if msg.strip():
                send_frame(tx_socket, f"{user}: {msg}", builder)

        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)


if __name__ == "__main__":
    main()
