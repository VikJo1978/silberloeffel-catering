"""SQLite persistence for internal employee chat."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from catering_system.domain.chat import (
    ChatMessage,
    ChatMessageBundle,
    ChatMessageMention,
    ChatMessageReference,
    ChatParticipant,
    ChatThread,
    ChatThreadSummary,
    validate_chat_reference_type,
    validate_chat_thread_type,
)
from catering_system.repositories.sqlite_migrations import apply_migrations

_CREATE_THREADS = """
CREATE TABLE IF NOT EXISTS chat_threads (
    thread_id TEXT PRIMARY KEY,
    thread_type TEXT NOT NULL CHECK(thread_type IN ('DIRECT', 'GROUP')),
    title TEXT,
    created_by_employee_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (thread_type = 'DIRECT' AND title IS NULL)
        OR (thread_type = 'GROUP' AND title IS NOT NULL AND length(title) > 0)
    ),
    FOREIGN KEY (created_by_employee_id) REFERENCES employee_accounts(account_id)
)
"""

_CREATE_DIRECT_THREADS = """
CREATE TABLE IF NOT EXISTS chat_direct_threads (
    thread_id TEXT PRIMARY KEY,
    employee_low_id TEXT NOT NULL,
    employee_high_id TEXT NOT NULL,
    CHECK(employee_low_id < employee_high_id),
    UNIQUE(employee_low_id, employee_high_id),
    FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id),
    FOREIGN KEY (employee_low_id) REFERENCES employee_accounts(account_id),
    FOREIGN KEY (employee_high_id) REFERENCES employee_accounts(account_id)
)
"""

_CREATE_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS chat_participants (
    thread_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    last_read_message_id TEXT,
    PRIMARY KEY (thread_id, employee_id),
    FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id),
    FOREIGN KEY (employee_id) REFERENCES employee_accounts(account_id),
    FOREIGN KEY (last_read_message_id) REFERENCES chat_messages(message_id)
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    author_employee_id TEXT NOT NULL,
    body TEXT NOT NULL,
    reply_to_message_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id),
    FOREIGN KEY (thread_id, author_employee_id)
        REFERENCES chat_participants(thread_id, employee_id),
    FOREIGN KEY (reply_to_message_id) REFERENCES chat_messages(message_id)
)
"""

_CREATE_MENTIONS = """
CREATE TABLE IF NOT EXISTS chat_message_mentions (
    message_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    PRIMARY KEY (message_id, employee_id),
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id),
    FOREIGN KEY (employee_id) REFERENCES employee_accounts(account_id)
)
"""

_CREATE_REFERENCES = """
CREATE TABLE IF NOT EXISTS chat_message_references (
    message_id TEXT NOT NULL,
    reference_type TEXT NOT NULL CHECK(reference_type IN ('ORDER', 'INQUIRY', 'CONTACT')),
    reference_id TEXT NOT NULL,
    PRIMARY KEY (message_id, reference_type, reference_id),
    FOREIGN KEY (message_id) REFERENCES chat_messages(message_id)
)
"""

_INDEXES = (
    """
    CREATE INDEX IF NOT EXISTS idx_chat_participants_employee
    ON chat_participants(employee_id, thread_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
    ON chat_messages(thread_id, created_at, message_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_messages_author_created
    ON chat_messages(author_employee_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_mentions_employee
    ON chat_message_mentions(employee_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_refs_type_id
    ON chat_message_references(reference_type, reference_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_threads_title
    ON chat_threads(title)
    """,
)

_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_messages_reply_same_thread
    BEFORE INSERT ON chat_messages
    WHEN NEW.reply_to_message_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM chat_messages original
          WHERE original.message_id = NEW.reply_to_message_id
            AND original.thread_id = NEW.thread_id
      )
    BEGIN SELECT RAISE(ABORT, 'reply target is not in thread'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_messages_no_update
    BEFORE UPDATE ON chat_messages
    BEGIN SELECT RAISE(ABORT, 'chat messages are immutable'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_messages_no_delete
    BEFORE DELETE ON chat_messages
    BEGIN SELECT RAISE(ABORT, 'chat messages are immutable'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_mentions_employee_is_participant
    BEFORE INSERT ON chat_message_mentions
    WHEN NOT EXISTS (
        SELECT 1
        FROM chat_messages message
        JOIN chat_participants participant
          ON participant.thread_id = message.thread_id
         AND participant.employee_id = NEW.employee_id
        WHERE message.message_id = NEW.message_id
    )
    BEGIN SELECT RAISE(ABORT, 'mention target is not a participant'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_participants_last_read_same_thread_insert
    BEFORE INSERT ON chat_participants
    WHEN NEW.last_read_message_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM chat_messages message
          WHERE message.message_id = NEW.last_read_message_id
            AND message.thread_id = NEW.thread_id
      )
    BEGIN SELECT RAISE(ABORT, 'last read message is not in thread'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_participants_last_read_same_thread_update
    BEFORE UPDATE OF last_read_message_id ON chat_participants
    WHEN NEW.last_read_message_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM chat_messages message
          WHERE message.message_id = NEW.last_read_message_id
            AND message.thread_id = NEW.thread_id
      )
    BEGIN SELECT RAISE(ABORT, 'last read message is not in thread'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_chat_threads_no_delete
    BEFORE DELETE ON chat_threads
    BEGIN SELECT RAISE(ABORT, 'chat threads are not deleted in MVP'); END
    """,
)


def _migration_1_create_chat_tables(connection: sqlite3.Connection) -> None:
    connection.execute(_CREATE_THREADS)
    connection.execute(_CREATE_DIRECT_THREADS)
    connection.execute(_CREATE_PARTICIPANTS)
    connection.execute(_CREATE_MESSAGES)
    connection.execute(_CREATE_MENTIONS)
    connection.execute(_CREATE_REFERENCES)
    for statement in _INDEXES:
        connection.execute(statement)
    for statement in _TRIGGERS:
        connection.execute(statement)


_MIGRATIONS = ((1, "create_chat_tables", _migration_1_create_chat_tables),)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _direct_pair(employee_a_id: str, employee_b_id: str) -> tuple[str, str]:
    if employee_a_id == employee_b_id:
        raise ValueError("DIRECT chat requires two distinct employees")
    return tuple(sorted((employee_a_id, employee_b_id)))  # type: ignore[return-value]


class SQLiteChatRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._manage_transactions = True
        self._transaction_depth = 0
        try:
            apply_migrations(self._conn, "chat", _MIGRATIONS)
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> SQLiteChatRepository:
        repo = cls.__new__(cls)
        repo._conn = connection
        repo._conn.execute("PRAGMA foreign_keys = ON")
        repo._manage_transactions = False
        repo._transaction_depth = 0
        apply_migrations(connection, "chat", _MIGRATIONS)
        return repo

    @contextmanager
    def immediate_transaction(self) -> Iterator[sqlite3.Connection]:
        if not self._manage_transactions:
            yield self._conn
            return
        self._transaction_depth += 1
        if self._transaction_depth == 1:
            self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            if self._transaction_depth == 1:
                self._conn.commit()
        except Exception:
            if self._transaction_depth == 1:
                self._conn.rollback()
            raise
        finally:
            self._transaction_depth -= 1

    def _write_scope(self):
        return self.immediate_transaction()

    def close(self) -> None:
        self._conn.close()

    def create_thread(
        self,
        thread: ChatThread,
        participants: tuple[ChatParticipant, ...],
        *,
        direct_pair: tuple[str, str] | None = None,
    ) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO chat_threads (
                    thread_id, thread_type, title, created_by_employee_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    thread.thread_id,
                    thread.thread_type,
                    thread.title,
                    thread.created_by_employee_id,
                    thread.created_at.isoformat(),
                ),
            )
            if direct_pair is not None:
                low, high = _direct_pair(*direct_pair)
                self._conn.execute(
                    """
                    INSERT INTO chat_direct_threads (
                        thread_id, employee_low_id, employee_high_id
                    ) VALUES (?, ?, ?)
                    """,
                    (thread.thread_id, low, high),
                )
            self._conn.executemany(
                """
                INSERT INTO chat_participants (
                    thread_id, employee_id, joined_at, last_read_message_id
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        participant.thread_id,
                        participant.employee_id,
                        participant.joined_at.isoformat(),
                        participant.last_read_message_id,
                    )
                    for participant in participants
                ],
            )

    def get_thread(self, thread_id: str) -> ChatThread | None:
        row = self._conn.execute(
            """
            SELECT thread_id, thread_type, title, created_by_employee_id, created_at
            FROM chat_threads WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()
        return _row_to_thread(row) if row else None

    def find_direct_thread(
        self, employee_a_id: str, employee_b_id: str
    ) -> ChatThread | None:
        low, high = _direct_pair(employee_a_id, employee_b_id)
        row = self._conn.execute(
            """
            SELECT t.thread_id, t.thread_type, t.title,
                   t.created_by_employee_id, t.created_at
            FROM chat_direct_threads direct
            JOIN chat_threads t ON t.thread_id = direct.thread_id
            WHERE direct.employee_low_id = ? AND direct.employee_high_id = ?
            """,
            (low, high),
        ).fetchone()
        return _row_to_thread(row) if row else None

    def list_participants(self, thread_id: str) -> tuple[ChatParticipant, ...]:
        rows = self._conn.execute(
            """
            SELECT thread_id, employee_id, joined_at, last_read_message_id
            FROM chat_participants
            WHERE thread_id = ?
            ORDER BY joined_at, employee_id
            """,
            (thread_id,),
        ).fetchall()
        return tuple(_row_to_participant(row) for row in rows)

    def is_participant(self, thread_id: str, employee_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM chat_participants
            WHERE thread_id = ? AND employee_id = ?
            """,
            (thread_id, employee_id),
        ).fetchone()
        return row is not None

    def add_message(
        self,
        message: ChatMessage,
        *,
        mentions: tuple[ChatMessageMention, ...] = (),
        references: tuple[ChatMessageReference, ...] = (),
    ) -> None:
        with self._write_scope():
            self._conn.execute(
                """
                INSERT INTO chat_messages (
                    message_id, thread_id, author_employee_id,
                    body, reply_to_message_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.thread_id,
                    message.author_employee_id,
                    message.body,
                    message.reply_to_message_id,
                    message.created_at.isoformat(),
                ),
            )
            self._conn.executemany(
                """
                INSERT INTO chat_message_mentions (message_id, employee_id)
                VALUES (?, ?)
                """,
                [(mention.message_id, mention.employee_id) for mention in mentions],
            )
            self._conn.executemany(
                """
                INSERT INTO chat_message_references (
                    message_id, reference_type, reference_id
                ) VALUES (?, ?, ?)
                """,
                [
                    (ref.message_id, ref.reference_type, ref.reference_id)
                    for ref in references
                ],
            )

    def get_message(self, message_id: str) -> ChatMessage | None:
        row = self._conn.execute(
            """
            SELECT message_id, thread_id, author_employee_id,
                   body, reply_to_message_id, created_at
            FROM chat_messages WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def list_messages(
        self, thread_id: str, *, limit: int = 100
    ) -> tuple[ChatMessageBundle, ...]:
        rows = self._conn.execute(
            """
            SELECT message_id, thread_id, author_employee_id,
                   body, reply_to_message_id, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY created_at, message_id
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        return tuple(self._message_bundle(_row_to_message(row)) for row in rows)

    def mark_read(
        self, thread_id: str, employee_id: str, last_read_message_id: str | None
    ) -> None:
        with self._write_scope():
            updated = self._conn.execute(
                """
                UPDATE chat_participants
                SET last_read_message_id = ?
                WHERE thread_id = ? AND employee_id = ?
                """,
                (last_read_message_id, thread_id, employee_id),
            ).rowcount
            if updated != 1:
                raise KeyError((thread_id, employee_id))

    def list_thread_summaries_for_employee(
        self, employee_id: str
    ) -> tuple[ChatThreadSummary, ...]:
        rows = self._conn.execute(
            """
            SELECT t.thread_id, t.thread_type, t.title,
                   t.created_by_employee_id, t.created_at
            FROM chat_threads t
            JOIN chat_participants p ON p.thread_id = t.thread_id
            WHERE p.employee_id = ?
            ORDER BY t.created_at DESC, t.thread_id DESC
            """,
            (employee_id,),
        ).fetchall()
        return tuple(
            ChatThreadSummary(
                thread=_row_to_thread(row),
                participants=self.list_participants(str(row[0])),
                latest_message=self._latest_message(str(row[0])),
                unread_count=self.unread_count_for_thread(str(row[0]), employee_id),
            )
            for row in rows
        )

    def unread_count_for_thread(self, thread_id: str, employee_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_participants participant
            JOIN chat_messages message ON message.thread_id = participant.thread_id
            LEFT JOIN chat_messages read_marker
              ON read_marker.message_id = participant.last_read_message_id
            WHERE participant.thread_id = ?
              AND participant.employee_id = ?
              AND message.author_employee_id <> participant.employee_id
              AND (
                  (
                      participant.last_read_message_id IS NULL
                      AND (
                          message.created_at > participant.joined_at
                          OR (
                              message.created_at = participant.joined_at
                              AND message.message_id > ''
                          )
                      )
                  )
                  OR (
                      participant.last_read_message_id IS NOT NULL
                      AND (
                          message.created_at > read_marker.created_at
                          OR (
                              message.created_at = read_marker.created_at
                              AND message.message_id > read_marker.message_id
                          )
                      )
                  )
              )
            """,
            (thread_id, employee_id),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def total_unread_count(self, employee_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(unread_count), 0)
            FROM (
                SELECT participant.thread_id, COUNT(message.message_id) AS unread_count
                FROM chat_participants participant
                JOIN chat_messages message
                  ON message.thread_id = participant.thread_id
                LEFT JOIN chat_messages read_marker
                  ON read_marker.message_id = participant.last_read_message_id
                WHERE participant.employee_id = ?
                  AND message.author_employee_id <> participant.employee_id
                  AND (
                      (
                          participant.last_read_message_id IS NULL
                          AND (
                              message.created_at > participant.joined_at
                              OR (
                                  message.created_at = participant.joined_at
                                  AND message.message_id > ''
                              )
                          )
                      )
                      OR (
                          participant.last_read_message_id IS NOT NULL
                          AND (
                              message.created_at > read_marker.created_at
                              OR (
                                  message.created_at = read_marker.created_at
                                  AND message.message_id > read_marker.message_id
                              )
                          )
                      )
                  )
                GROUP BY participant.thread_id
            )
            """,
            (employee_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def _latest_message(self, thread_id: str) -> ChatMessage | None:
        row = self._conn.execute(
            """
            SELECT message_id, thread_id, author_employee_id,
                   body, reply_to_message_id, created_at
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY created_at DESC, message_id DESC
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        return _row_to_message(row) if row else None

    def _message_bundle(self, message: ChatMessage) -> ChatMessageBundle:
        mention_rows = self._conn.execute(
            """
            SELECT message_id, employee_id
            FROM chat_message_mentions
            WHERE message_id = ?
            ORDER BY employee_id
            """,
            (message.message_id,),
        ).fetchall()
        reference_rows = self._conn.execute(
            """
            SELECT message_id, reference_type, reference_id
            FROM chat_message_references
            WHERE message_id = ?
            ORDER BY reference_type, reference_id
            """,
            (message.message_id,),
        ).fetchall()
        return ChatMessageBundle(
            message=message,
            mentions=tuple(_row_to_mention(row) for row in mention_rows),
            references=tuple(_row_to_reference(row) for row in reference_rows),
        )


def _row_to_thread(row: tuple[object, ...]) -> ChatThread:
    return ChatThread(
        thread_id=str(row[0]),
        thread_type=validate_chat_thread_type(str(row[1])),
        title=str(row[2]) if row[2] is not None else None,
        created_by_employee_id=str(row[3]),
        created_at=_dt(str(row[4])),
    )


def _row_to_participant(row: tuple[object, ...]) -> ChatParticipant:
    return ChatParticipant(
        thread_id=str(row[0]),
        employee_id=str(row[1]),
        joined_at=_dt(str(row[2])),
        last_read_message_id=str(row[3]) if row[3] is not None else None,
    )


def _row_to_message(row: tuple[object, ...]) -> ChatMessage:
    return ChatMessage(
        message_id=str(row[0]),
        thread_id=str(row[1]),
        author_employee_id=str(row[2]),
        body=str(row[3]),
        reply_to_message_id=str(row[4]) if row[4] is not None else None,
        created_at=_dt(str(row[5])),
    )


def _row_to_mention(row: tuple[object, ...]) -> ChatMessageMention:
    return ChatMessageMention(message_id=str(row[0]), employee_id=str(row[1]))


def _row_to_reference(row: tuple[object, ...]) -> ChatMessageReference:
    return ChatMessageReference(
        message_id=str(row[0]),
        reference_type=validate_chat_reference_type(str(row[1])),
        reference_id=str(row[2]),
    )
