def ax25_call(callsign: str, ssid: int = 0, last: bool = False) -> bytes:
    callsign = callsign.upper().ljust(6)
    encoded = bytes([(ord(c) << 1) & 0xFE for c in callsign])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    return encoded + bytes([ssid_byte])


def kiss_escape(data: bytes) -> bytes:
    return data.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")


def kiss_unescape(data: bytes) -> bytes:
    return data.replace(b"\xdb\xdd", b"\xdb").replace(b"\xdb\xdc", b"\xc0")


def parse_ax25_addresses(frame: bytes) -> tuple[list[bytes], int]:
    addresses: list[bytes] = []
    idx = 0
    while True:
        if idx + 7 > len(frame):
            raise ValueError("truncated AX.25 address field")
        addr = frame[idx : idx + 7]
        addresses.append(addr)
        idx += 7
        if addr[6] & 0x01:
            break
    return addresses, idx


def decode_call(raw: bytes) -> str:
    call = "".join(chr(b >> 1) for b in raw[:6]).strip()
    ssid = (raw[6] >> 1) & 0x0F
    return f"{call}-{ssid}"


class AX25Config:
    def __init__(self, dest_call: str, dest_ssid: int, src_call: str, src_ssid: int):
        self.dest_call = dest_call
        self.dest_ssid = dest_ssid
        self.src_call = src_call
        self.src_ssid = src_ssid
        self._build_frames()

    def _build_frames(self) -> None:
        self._dest_frame = ax25_call(self.dest_call, self.dest_ssid)
        self._src_frame = ax25_call(self.src_call, self.src_ssid, last=True)

    @property
    def dest_frame(self) -> bytes:
        return self._dest_frame

    @property
    def src_frame(self) -> bytes:
        return self._src_frame


class AX25FrameBuilder:
    def __init__(self, config: AX25Config):
        self.config = config

    def build_ax25_frame(self, payload: bytes) -> bytes:
        CONTROL = b"\x03"
        PID = b"\xf0"
        return self.config.dest_frame + self.config.src_frame + CONTROL + PID + payload

    def build_kiss_frame(self, ax25_frame: bytes) -> bytes:
        """Build a KISS-framed byte sequence for the given AX.25 frame.

        Note: the TNC (Direwolf) appends the 2-byte FCS on-air, so this
        function does not append an FCS. Keep framing simple and let the
        TNC handle FCS.
        """
        return b"\xc0\x00" + kiss_escape(ax25_frame) + b"\xc0"

    def estimate_tx_time(self, ax25_frame: bytes) -> float:
        bits = (len(ax25_frame) + 2) * 8
        return bits / 1200.0 + 0.25

    def decode(self, frame: bytes):
        try:
            if len(frame) < 20:
                return None, None, None

            # Remove KISS framing and unescape
            if frame and frame[0] == 0xC0:
                while frame and frame[0] == 0xC0:
                    frame = frame[1:]
                while frame and frame[-1] == 0xC0:
                    frame = frame[:-1]
                if frame and frame[0] == 0x00:
                    frame = frame[1:]
                frame = kiss_unescape(frame)

            try:
                addresses, idx = parse_ax25_addresses(frame)
            except ValueError:
                return None, None, None
            if len(addresses) < 2:
                return None, None, None
            dest_raw = addresses[0]
            src_raw = addresses[1]
            # Require at least CONTROL and PID bytes after the addresses.
            if len(frame) < idx + 2:
                return None, None, None
            payload = frame[idx + 2 :]

            dest = decode_call(dest_raw)
            src = decode_call(src_raw)

            try:
                text = payload.decode("utf-8", errors="replace")
            except Exception:
                text = "<non-text payload>"

            return dest, src, text
        except Exception:
            return None, None, None
