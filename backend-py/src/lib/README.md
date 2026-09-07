Library Reference Documentation
===============================

AX.25 (ax25.py)
-------------------------------

This file lists common AX.25 CONTROL and PID byte values referenced by
the `FrameBuilder` in this library.

| Field | Hex | Decimal | Meaning/Notes |
| ----- | ---: | -------: | --------------- |
| CONTROL UI | 0x03 | 3 | Unnumbered Information (UI) frame — common for connectionless packets |
| CONTROL I | 0x00 | 0 | Information (I) frame — used for connected mode |
| CONTROL S | 0x01 | 1 | Supervisory (S) frame — acknowledgements/flow control |
| PID APRS (no layer‑3) | 0xF0 | 240 | APRS/UI convention: payload is APRS data (Dire Wolf will attempt APRS parsing) |
| PID No Layer‑3 (non‑APRS) | 0x01 | 1 | Common value for unstructured payloads; avoids APRS-specific parsing in some TNCs |
| PID IP over AX.25 | 0xCC | 204 | Example: IP packet encapsulation (rare) |

Notes

- If you are not using APRS formats, prefer a non-0xF0 PID (for example `0x01`) to avoid TNC software attempting APRS parsing.
- The `CONTROL` byte is selected based on whether you're sending UI (connectionless) packets or participating in a connected session.
- This is a short reference, not a complete registry. See AX.25 and APRS specifications for exhaustive PID lists.

Terminal Colouring (terminal.py)
--------------------------------

This module provides functions to print colored warnings in the terminal. It uses ANSI escape codes to set the text color to red for warnings and resets it back to default after printing.
