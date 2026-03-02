def ax25_call(callsign: str, ssid: int = 0, last: bool = False) -> bytes:
    callsign = callsign.upper().ljust(6)
    encoded = bytes([(ord(c) << 1) & 0xFE for c in callsign])
    ssid_byte: int = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    return encoded + bytes([ssid_byte])


def kiss_escape(data: bytes) -> bytes:
    return data.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")


def kiss_unescape(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    length: int = len(data)
    while i < length:
        byte: int = data[i]
        if byte != 0xDB:
            out.append(byte)
            i += 1
            continue

        # Saw FESC (0xDB). Try to interpret an escape sequence.
        if i + 1 >= length:
            # Dangling FESC at end: treat as literal 0xDB.
            out.append(0xDB)
            i += 1
            continue

        next_byte: int = data[i + 1]
        if next_byte == 0xDC:
            # FESC TFEND -> FEND (0xC0)
            out.append(0xC0)
            i += 2
        elif next_byte == 0xDD:
            # FESC TFESC -> FESC (0xDB)
            out.append(0xDB)
            i += 2
        else:
            # Non-standard sequence: keep literal 0xDB and process next normally.
            out.append(0xDB)
            i += 1

    return bytes(out)


def parse_ax25_addresses(frame: bytes) -> tuple[list[bytes], int]:
    addresses: list[bytes] = []
    idx = 0
    while True:
        if idx + 7 > len(frame):
            raise ValueError("truncated AX.25 address field")
        addr: bytes = frame[idx : idx + 7]
        addresses.append(addr)
        idx += 7
        if addr[6] & 0x01:
            break
    return addresses, idx


def decode_call(raw: bytes) -> str:
    call: str = "".join(chr(b >> 1) for b in raw[:6]).strip()
    ssid: int = (raw[6] >> 1) & 0x0F
    return f"{call}-{ssid}"


class AX25Config:
    def __init__(self, dest_call: str, dest_ssid: int, src_call: str, src_ssid: int) -> None:
        self.dest_call: str = dest_call
        self.dest_ssid: int = dest_ssid
        self.src_call: str = src_call
        self.src_ssid: int = src_ssid
        self._build_frames()

    def _build_frames(self) -> None:
        self._dest_frame: bytes = ax25_call(self.dest_call, self.dest_ssid)
        self._src_frame: bytes = ax25_call(self.src_call, self.src_ssid, last=True)

    @property
    def dest_frame(self) -> bytes:
        return self._dest_frame

    @property
    def src_frame(self) -> bytes:
        return self._src_frame


class AX25FrameBuilder:
    def __init__(self, config: AX25Config) -> None:
        self.config: AX25Config = config

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

    def estimate_tx_time(self, ax25_frame: bytes, baud: int = 1200, overhead: float = 0.25) -> float:
        """Estimate transmit time for an AX.25 frame.

        Parameters:
        - ax25_frame: raw AX.25 frame bytes (does not include KISS framing)
        - baud: nominal bit rate (default 1200)
        - overhead: additional seconds to add for PTT/keying/etc.
        """
        bits: int = (len(ax25_frame) + 2) * 8
        return bits / float(baud) + float(overhead)

    def decode(self, frame: bytes) -> tuple[str | None, str | None, str | None]:
        try:
            if not frame:
                return None, None, None

            # If KISS framing (FEND 0xC0) is present, extract the first
            # non-empty chunk between FEND bytes. This handles multiple
            # concatenated frames more robustly than stripping all FENDs.
            if 0xC0 in frame:
                chunks: list[bytes] = frame.split(b"\xc0")
                # Pick the first non-empty chunk (if any)
                frame = next((c for c in chunks if c), b"")

            # Remove optional KISS command byte (0x00) if present
            if frame and frame[0] == 0x00:
                frame = frame[1:]

            # Unescape KISS special sequences
            frame = kiss_unescape(frame)

            # Minimal AX.25 length: two 7-byte addresses + CONTROL + PID = 16
            if len(frame) < 16:
                return None, None, None

            try:
                addresses, idx = parse_ax25_addresses(frame)
            except ValueError:
                return None, None, None
            if len(addresses) < 2:
                return None, None, None
            dest_raw: bytes = addresses[0]
            src_raw: bytes = addresses[1]
            # Require at least CONTROL and PID bytes after the addresses.
            if len(frame) < idx + 2:
                return None, None, None
            payload: bytes = frame[idx + 2 :]

            dest: str = decode_call(dest_raw)
            src: str = decode_call(src_raw)

            try:
                text: str = payload.decode("utf-8", errors="replace")
            except Exception:
                text = "<non-text payload>"

            return dest, src, text
        except Exception:
            return None, None, None
