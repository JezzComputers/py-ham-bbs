import logging
import os
import sqlite3
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Final[str] = "py_ham_bbs_protocol.db"


class MessageRepository:
	"""Handles storage and retrieval of messages using SQLite."""

	__slots__ = ("_connection",)

	def __init__(self, db_path: Path) -> None:
		"""Initialize the message repository, creating the database file and schema if necessary."""

		db_path.parent.mkdir(parents=True, exist_ok=True)
		self._connection = sqlite3.connect(db_path, check_same_thread=False)
		self._connection.row_factory = sqlite3.Row
		self._create_schema()

	def _create_schema(self) -> None:
		with self._connection:
			self._connection.execute("DROP INDEX IF EXISTS idx_source_client_msg")
			self._connection.execute(
				"""
				CREATE TABLE IF NOT EXISTS messages (
					server_id TEXT PRIMARY KEY,
					timestamp TEXT NOT NULL,
					type TEXT NOT NULL,
					source TEXT NOT NULL,
					destination TEXT NOT NULL,
					ack_required INTEGER NOT NULL,
					payload TEXT NOT NULL,
					client_msg_id TEXT
				)
				""",
			)
			self._connection.execute(
				"""
				CREATE UNIQUE INDEX IF NOT EXISTS idx_source_client_msg
				ON messages(source, client_msg_id)
				WHERE client_msg_id IS NOT NULL AND type = 'message'
				""",
			)

	def close(self) -> None:
		"""Close the database connection."""

		self._connection.close()

	def get_server_id(self, source: str, client_msg_id: str) -> str | None:
		"""Retrieve the server_id for a message frame with a given source and client_msg_id, or None if not found."""

		row = self._connection.execute(
			"""
			SELECT server_id
			FROM messages
			WHERE source = ? AND client_msg_id = ? AND type = 'message'
			LIMIT 1
			""",
			(source, client_msg_id),
		).fetchone()
		if row is None:
			return None
		server_id = row["server_id"]
		if isinstance(server_id, str):
			return server_id
		return None

	def save_frame(
		self,
		server_id: str,
		timestamp: str,
		frame_type: str,
		source: str,
		destination: str,
		ack_required: int,
		payload: str,
		client_msg_id: str | None,
	) -> str:
		"""Save a message frame to the database and return the persisted server_id.

		Uses INSERT OR IGNORE to prevent duplicate entries for the same source/client_msg_id among message frames.
		If the insert is ignored, returns the existing server_id already stored for that key.
		"""

		with self._connection:
			self._connection.execute(
				"""
				INSERT OR IGNORE INTO messages
				(server_id, timestamp, type, source, destination, ack_required, payload, client_msg_id)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(server_id, timestamp, frame_type, source, destination, ack_required, payload, client_msg_id),
			)

		if client_msg_id is None:
			return str(server_id)

		stored_server_id = self.get_server_id(source, client_msg_id)
		if stored_server_id is not None:
			return stored_server_id
		return str(server_id)


def resolve_db_path() -> Path:
	"""Resolve the database path from environment variables or use the default."""
	raw_path = os.getenv("PY_HAM_BBS_DB_PATH", DEFAULT_DB_PATH)
	return Path(raw_path).expanduser().resolve()
