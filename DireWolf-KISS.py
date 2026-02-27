import socket
import threading
import sys
import time

KISS_HOST = "127.0.0.1"
KISS_PORT = 8001

RIGCTL_HOST = "127.0.0.1"
RIGCTL_PORT = 4532   # default rigctld port

# ----------------------------------------------------
#  CONNECT TO KISS (Direwolf)
# ----------------------------------------------------
def kiss_connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((KISS_HOST, KISS_PORT))
    return s

# ----------------------------------------------------
#  CONNECT TO rigctld
# ----------------------------------------------------
def rigctl_connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((RIGCTL_HOST, RIGCTL_PORT))
    return s

def rigctl_cmd(cmd: str):
    rig.send((cmd + "\n").encode())
    return rig.recv(128).decode(errors="ignore")

def ptt_on():
    rigctl_cmd("T 1")

def ptt_off():
    rigctl_cmd("T 0")

# ----------------------------------------------------
#  AX.25 ADDRESS ENCODER
# ----------------------------------------------------
def ax25_call(callsign, ssid=0, last=False):
    callsign = callsign.upper().ljust(6)
    encoded = bytes([(ord(c) << 1) & 0xFE for c in callsign])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    encoded += bytes([ssid_byte])
    return encoded

# ----------------------------------------------------
#  CRC-16-CCITT (AX.25 FCS)
# ----------------------------------------------------
def ax25_fcs(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    crc ^= 0xFFFF
    return crc.to_bytes(2, "little")

# ----------------------------------------------------
#  SEND AX.25 FRAME WITH PTT CONTROL
# ----------------------------------------------------
def send_frame(text: str):
    payload = text.encode("utf-8")

    DEST = ax25_call("APRS", 0)
    SRC  = ax25_call("N0CALL", 0, last=True)

    CONTROL = b"\x03"
    PID     = b"\xF0"

    frame = DEST + SRC + CONTROL + PID + payload
    frame += ax25_fcs(frame)

    kiss_frame = b"\xC0\x00" + frame + b"\xC0"

    # ---- Compute TX duration ----
    bits = len(frame) * 8
    tx_time = bits / 1200.0      # 1200 baud AFSK
    tx_time += 0.25              # safety margin

    print(f"[PTT] ON for {tx_time:.2f} sec")
    ptt_on()

    tx_socket.send(kiss_frame)
    print(f"[TX] {text}")

    time.sleep(tx_time)

    ptt_off()
    print("[PTT] OFF")

# ----------------------------------------------------
#  AX.25 FRAME DECODER (UI frames only)
# ----------------------------------------------------
def decode_ax25(frame: bytes):
    """
    Decode a basic AX.25 UI frame:
    DEST(7) + SRC(7) + CONTROL + PID + PAYLOAD + FCS(2)
    """
    try:
        if len(frame) < 20:
            return None, None, None

        # Remove KISS framing if present
        if frame[0] == 0xC0:
            frame = frame[2:-1]   # strip C0 00 ... C0

        # Extract fields
        dest_raw = frame[0:7]
        src_raw  = frame[7:14]
        control  = frame[14]
        pid      = frame[15]
        payload  = frame[16:-2]   # exclude FCS

        # Decode callsigns
        def decode_call(raw):
            call = "".join(chr(b >> 1) for b in raw[:6]).strip()
            ssid = (raw[6] >> 1) & 0x0F
            return f"{call}-{ssid}"

        dest = decode_call(dest_raw)
        src  = decode_call(src_raw)

        # Decode payload as text
        try:
            text = payload.decode("utf-8", errors="replace")
        except:
            text = "<non-text payload>"

        return dest, src, text

    except Exception as e:
        return None, None, None

# ----------------------------------------------------
#  LISTENER THREAD
# ----------------------------------------------------
def listener():
    while True:
        try:
            data = rx_socket.recv(4096)
            if not data:
                print("RX socket closed")
                break

            # Print raw hex
            print(f"\n[RX RAW] {data.hex()}")

            # Try to decode AX.25
            dest, src, text = decode_ax25(data)

            if dest is not None:
                print(f"[DECODED] {src} → {dest} : {text}")

            print(">>> ", end="", flush=True)

        except Exception as e:
            print("RX error:", e)
            break

# ----------------------------------------------------
#  MAIN
# ----------------------------------------------------
tx_socket = kiss_connect()
rx_socket = kiss_connect()
rig = rigctl_connect()

threading.Thread(target=listener, daemon=True).start()

print("KISS + rigctld test console ready.")
print("Type messages and press Enter.\n")

while True:
    try:
        msg = input(">>> ")
        if msg.strip():
            send_frame(msg)
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
