# py-ham-bbs

[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads) [![Wiki Docs](https://img.shields.io/badge/wiki-docs-4a7ebb?logo=wikipedia&logoColor=white&style=flat)](https://github.com/jezza5400-org/py-ham-bbs/wiki) [![CI](https://github.com/JezzComputers/py-ham-bbs/actions/workflows/ci.yml/badge.svg)](https://github.com/JezzComputers/py-ham-bbs/actions/workflows/ci.yml)

Tools and configuration files for building a lightweight ham radio packet BBS made with Python using software TNCs and AX.25

## Documentation

WebSocket Message Protocol can be found at the [WebSocket-Message-Protocol wiki](https://github.com/jezza5400-org/py-ham-bbs/wiki/08%E2%80%90WebSocket-Message-Protocol) page.

If possible the radio should be in FM-D (FM Data) mode as audio goes through the DATA path (USB soundcard or ACC connector) which is flat, wide, and unprocessed (what AX.25 wants)

## Implemented Protocol Subset

The current server implementation in `src/server.py` supports a practical subset of the protocol for bidirectional exchange:

- Accepts and validates JSON text frames for `message`, `ack`, `control`, and `error` types.
- Assigns authoritative server-side `id` (UUIDv7) and `timestamp` (ISO-8601 with timezone) for accepted inbound frames.
- Validates `source` and `destination` in `CALL-SSID` format and soft-binds `source` to each WebSocket session.
- Validates `message` payload as KISS hex and verifies it can decode as a KISS-wrapped AX.25 frame.
- Supports `ack_required` values `0`, `1`, and `2` (unknown numeric values are treated as `0`).
- Persists idempotency mapping in SQLite (`client_msg_id -> server_id`) so retries can be deduplicated safely.
- Returns protocol `error` frames on malformed payloads and includes original identifiers when available.

### Runtime Environment

- `PY_HAM_BBS_DB_PATH`: SQLite file path for protocol message/idempotency storage (default: `py_ham_bbs_protocol.db`).
- `PY_HAM_BBS_SERVER_SOURCE`: Server source station id used for generated ACK/error frames (default: `SERVER-0`).
- `PY_HAM_BBS_DIREWOLF_ENABLED`: Enable Direwolf KISS forwarding (default: `1`, set to `0`/`false` to disable).
- `PY_HAM_BBS_DIREWOLF_HOST`: Direwolf KISS host (default: `127.0.0.1`).
- `PY_HAM_BBS_DIREWOLF_PORT`: Direwolf KISS port (default: `8001`).

### Server binding and public reachability

Default binding: `0.0.0.0:8765` — the protocol server listens on all network interfaces and is intended to be publicly reachable from the host's network addresses. This design makes the server accessible to remote clients (LAN or internet).

## GitHub Actions

- **Badge**: The CI badge at the top links to the `python-tests.yml` workflow and shows the current status for the `main` branch.
- **Workflow file**: `.github/workflows/python-tests.yml`
- **What it runs**: Executes the test suite (via `pytest`) on pushes and pull requests across supported Python versions.
- **How to view runs**: Open the repository's Actions tab or click the badge to inspect recent runs, logs, and artifacts.
- **Local testing**: Run the test suite locally with `pytest` (or `pytest -q` for quiet) and verify lint/format with your chosen tools (e.g., `ruff`, `black`).

## Conventions

This project follows a set of development conventions to keep the codebase consistent, predictable, and easy to maintain.

### Commit Message Format - Conventional Commits

All commits should follow the **Conventional Commits** specification.  
This helps maintain readable history, enables automated tooling, and clarifies intent.

Common prefixes include:

- `feat:` — new features  
- `fix:` — bug fixes
- `refactor:` — code restructuring without behavior changes  
- `chore:` — maintenance tasks  
- `test:` — adding or updating tests  

More details: [https://www.conventionalcommits.org/](https://www.conventionalcommits.org/en/v1.0.0/#summary)

### Python Naming & Style — PEP 8

Python code in this repository should follow **PEP 8** conventions, including:

- `snake_case` for file names (all lowercase, underscore separator)
- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_CASE` for constants
- 4‑space indentation (One TAB)
- Clear, descriptive names
- Avoiding overly long lines where practical

Tools like `flake8`, `ruff` (what I use), or `black` are recommended for automated checking and formatting.

### Python Warnings Usage

Warnings should be issued using the standard library’s `warnings` module:

```python
import warnings
warnings.warn("message", category=UserWarning)
```

A dedicated formatting/colouring helper is included in the project at ./src/lib/terminal.py and can be imported with `import lib.terminal`; use it for consistent output styling across modules. It adds ANSI colouring and automatic warning colouring based on warning type:

```python
import warnings
from lib.terminal import use_color

use_color()
# Warnings will now be colored
warnings.warn("message", category=UserWarning)
```

Warning colors:

- `UserWarning`: Yellow
- `RuntimeWarning`: Red
- `DeprecationWarning`: Magenta

### Branching & Commit Discipline

To keep the repository clean and reviewable:

- Each **branch** should focus on a single feature, fix, or task.  
- Each **commit** should represent one logical change.  
- Avoid mixing unrelated changes in the same commit or branch.  
- Use descriptive branch names such as:
  - `feature/pybbs-routing`
  - `fix/direwolf-config-path`
  - `refactor/ax25-handler`

This structure makes code review and management easier.
