import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Final, Self, cast

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Final[str] = "py_ham_bbs_protocol.db"
CALLSIGN_WITH_OPTIONAL_SSID_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Z0-9]{1,6})(?:-(\d{1,2}))?$")


class SaveFrameResult(str):
	"""String-like save result that also reports whether the row was newly inserted."""

	__slots__ = ("inserted",)

	inserted: bool

	def __new__(cls, server_id: str, inserted: bool) -> Self:
		result = str.__new__(cls, server_id)
		result.inserted = inserted
		return result

	@property
	def server_id(self) -> str:
		return str(self)


def _normalize_sql(sql: str) -> str:
	return " ".join(sql.split()).casefold()


def _normalize_station_id(raw_value: str) -> str | None:
	match = CALLSIGN_WITH_OPTIONAL_SSID_RE.fullmatch(raw_value.strip().upper())
	if match is None:
		return None

	callsign = match.group(1)
	ssid_text = match.group(2)
	ssid = int(ssid_text) if ssid_text is not None else 0
	if ssid < 0 or ssid > 15:
		return None

	return f"{callsign}-{ssid}"


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
			allowed_student_columns = [cast(str, row["name"]) for row in self._connection.execute("PRAGMA table_info(allowed_students)").fetchall() if isinstance(row["name"], str)]
			desired_allowed_students_sql = """
			CREATE TABLE allowed_students (
				id TEXT NOT NULL COLLATE NOCASE,
				student_name TEXT NOT NULL COLLATE NOCASE,
				PRIMARY KEY(id)
			)
			"""
			if not allowed_student_columns:
				self._connection.execute(desired_allowed_students_sql)
			elif allowed_student_columns != ["id", "student_name"]:
				self._connection.execute("ALTER TABLE allowed_students RENAME TO allowed_students_legacy")
				self._connection.execute(desired_allowed_students_sql)
				legacy_columns = [cast(str, row["name"]) for row in self._connection.execute("PRAGMA table_info(allowed_students_legacy)").fetchall() if isinstance(row["name"], str)]
				if "student_name" in legacy_columns and "student_id" in legacy_columns:
					self._connection.execute(
						"""
						INSERT INTO allowed_students (id, student_name)
						SELECT student_id, COALESCE(NULLIF(student_name, ''), student_id)
						FROM allowed_students_legacy
						""",
					)
				else:
					self._connection.execute(
						"""
						INSERT INTO allowed_students (id, student_name)
						SELECT student_id, student_id
						FROM allowed_students_legacy
						""",
					)
				self._connection.execute("DROP TABLE allowed_students_legacy")
			desired_index_sql = """
			CREATE UNIQUE INDEX idx_source_client_msg
			ON messages(source, client_msg_id)
			WHERE client_msg_id IS NOT NULL AND type = 'message'
			"""
			existing_index = self._connection.execute(
				"SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
				("idx_source_client_msg",),
			).fetchone()
			if existing_index is None:
				self._connection.execute(desired_index_sql)
			else:
				existing_sql = existing_index["sql"]
				if not isinstance(existing_sql, str) or _normalize_sql(existing_sql) != _normalize_sql(desired_index_sql):
					self._connection.execute("DROP INDEX IF EXISTS idx_source_client_msg")
					self._connection.execute(desired_index_sql)
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

	def get_allowed_student_name(self, student_id: str) -> str | None:
		"""Return the display name assigned to a student id, or None if it is not allowed."""

		normalized_student_id = _normalize_station_id(student_id)
		if normalized_student_id is None:
			return None

		lookup_ids = [normalized_student_id]
		if normalized_student_id.endswith("-0"):
			lookup_ids.append(normalized_student_id[:-2])

		row = None
		for lookup_id in lookup_ids:
			row = self._connection.execute(
				"""
				SELECT student_name
				FROM allowed_students
				WHERE id = ?
				LIMIT 1
				""",
				(lookup_id,),
			).fetchone()
			if row is not None:
				break
		if row is None:
			return None
		student_name = row["student_name"]
		if isinstance(student_name, str):
			return student_name
		return None

	def save_allowed_student(self, student_id: str, student_name: str) -> None:
		"""Insert or replace an allowed student mapping."""

		normalized_student_id = _normalize_station_id(student_id)
		stored_student_id = normalized_student_id if normalized_student_id is not None else student_id.strip().upper()

		with self._connection:
			self._connection.execute(
				"""
				INSERT OR REPLACE INTO allowed_students (id, student_name)
				VALUES (?, ?)
				""",
				(stored_student_id, student_name.strip()),
			)

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
	) -> SaveFrameResult:
		"""Save a message frame to the database and return the persisted server_id.

		Uses INSERT OR IGNORE to prevent duplicate entries for the same source/client_msg_id among message frames.
		If the insert is ignored, returns the existing server_id already stored for that key.
		"""

		with self._connection:
			cursor = self._connection.execute(
				"""
				INSERT OR IGNORE INTO messages
				(server_id, timestamp, type, source, destination, ack_required, payload, client_msg_id)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(server_id, timestamp, frame_type, source, destination, ack_required, payload, client_msg_id),
			)
		inserted = cursor.rowcount > 0

		if frame_type != "message" or client_msg_id is None:
			return SaveFrameResult(str(server_id), inserted)

		stored_server_id = self.get_server_id(source, client_msg_id)
		if stored_server_id is not None:
			return SaveFrameResult(stored_server_id, inserted)
		return SaveFrameResult(str(server_id), inserted)


def resolve_db_path() -> Path:
	"""Resolve the database path from environment variables or use the default."""
	raw_path = os.getenv("PY_HAM_BBS_DB_PATH", DEFAULT_DB_PATH)
	return Path(raw_path).expanduser().resolve()
