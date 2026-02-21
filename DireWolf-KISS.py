import socket
import threading
import sys

KISS_HOST = "127.0.0.1"
KISS_PORT = 8001

def kiss_connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((KISS_HOST, KISS_PORT))
    return s

# -------------------------
#  AX.25 ADDRESS ENCODER
# -------------------------
def ax25_call(callsign, ssid=0, last=False):
    callsign = callsign.upper().ljust(6)
    encoded = bytes([(ord(c) << 1) & 0xFE for c in callsign])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    encoded += bytes([ssid_byte])
    return encoded

# -------------------------
#  SEND AX.25 FRAME
# -------------------------
def send_frame(text: str):
    payload = text.encode("utf-8")

    DEST = ax25_call("APRS", 0)
    SRC  = ax25_call("N0CALL", 0, last=True)

    CONTROL = b"\x03"
    PID     = b"\xF0"

    frame = DEST + SRC + CONTROL + PID + payload
    kiss_frame = b"\xC0\x00" + frame + b"\xC0"

    try:
        tx_socket.send(kiss_frame)
        print(f"[TX] {text}")
    except Exception as e:
        print("TX error:", e)

# -------------------------
#  LISTENER THREAD
# -------------------------
def listener():
    while True:
        try:
            data = rx_socket.recv(4096)
            if not data:
                print("RX socket closed")
                break
            print(f"\n[RX] {data.hex()}\n>>> ", end="", flush=True)
        except Exception as e:
            print("RX error:", e)
            break

# -------------------------
#  MAIN
# -------------------------
tx_socket = kiss_connect()
rx_socket = kiss_connect()

threading.Thread(target=listener, daemon=True).start()

print("KISS console ready. Type messages and press Enter.")
print("Ctrl+C to exit.\n")

while True:
    try:
        msg = input(">>> ")
        if msg.strip():
            send_frame(msg)
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
