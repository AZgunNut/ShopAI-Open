#!/usr/bin/env python3
"""
Shared ShopAI conversation registry.

Stores complete conversation threads locally in SQLite.  Model-facing
context windows are a later concern; this registry never truncates or
deletes the stored transcript.
"""

import argparse
import json
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def clean_title(value):
    value = " ".join(str(value or "").split())
    return (value[:160] or "Untitled ShopAI Conversation")


def excerpt(value, limit=120):
    value = " ".join(str(value or "").split())
    return value[:limit]


class ConversationRegistry:
    def __init__(self, root=None):
        self.root = Path(root or Path.home() / "ShopAI")
        self.state_dir = self.root / "state"
        self.db_path = self.state_dir / "conversations.sqlite3"
        self._initialize()

    def _connect(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize(self):
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    preview TEXT NOT NULL DEFAULT '',
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    role TEXT NOT NULL,
                    route TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS messages_by_conversation
                    ON messages(conversation_id, created_at);

                CREATE INDEX IF NOT EXISTS conversations_by_updated
                    ON conversations(archived, updated_at DESC);
            """)
            conn.commit()
        finally:
            conn.close()

    def _create_in(self, conn, title):
        conversation_id = uuid.uuid4().hex
        timestamp = now()

        conn.execute(
            """
            INSERT INTO conversations
                (id, title, created_at, updated_at, preview, archived)
            VALUES (?, ?, ?, ?, '', 0)
            """,
            (conversation_id, clean_title(title), timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO settings(key, value)
            VALUES('current_conversation_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (conversation_id,),
        )
        return conversation_id

    def current_id(self):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'current_conversation_id'"
            ).fetchone()

            if row:
                exists = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ?",
                    (row["value"],),
                ).fetchone()
                if exists:
                    return row["value"]

            conversation_id = self._create_in(
                conn,
                "ShopAI Conversation " + datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
            )
            conn.commit()
            return conversation_id
        finally:
            conn.close()

    def create(self, title):
        conn = self._connect()
        try:
            conversation_id = self._create_in(conn, title)
            conn.commit()
            return conversation_id
        finally:
            conn.close()

    def select(self, conversation_id):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND archived = 0",
                (conversation_id,),
            ).fetchone()

            if not row:
                raise KeyError(f"Conversation not found: {conversation_id}")

            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES('current_conversation_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (conversation_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def rename(self, conversation_id, title):
        conn = self._connect()
        try:
            changed = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (clean_title(title), now(), conversation_id),
            ).rowcount

            if not changed:
                raise KeyError(f"Conversation not found: {conversation_id}")

            conn.commit()
        finally:
            conn.close()

    def append(self, conversation_id, role, content, route, model="", metadata=None):
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError(f"Unsupported message role: {role}")

        if not isinstance(content, str):
            raise TypeError("Conversation content must be plain text.")

        metadata = metadata or {}
        timestamp = now()
        message_id = uuid.uuid4().hex

        conn = self._connect()
        try:
            found = conn.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

            if not found:
                raise KeyError(f"Conversation not found: {conversation_id}")

            conn.execute(
                """
                INSERT INTO messages
                    (id, conversation_id, created_at, role, route, model, content, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    timestamp,
                    role,
                    str(route),
                    str(model),
                    content,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?, preview = ?
                WHERE id = ?
                """,
                (timestamp, excerpt(content), conversation_id),
            )

            conn.commit()
            return message_id
        finally:
            conn.close()

    def recent(self, limit=12):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at, c.preview,
                       COUNT(m.id) AS message_count
                FROM conversations AS c
                LEFT JOIN messages AS m ON m.conversation_id = c.id
                WHERE c.archived = 0
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def messages(self, conversation_id):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, conversation_id, created_at, role, route, model,
                       content, metadata_json
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()

            result = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json"))
                result.append(item)

            return result
        finally:
            conn.close()

    def search(self, query, limit=20):
        query = str(query).strip()
        if not query:
            return []

        pattern = "%" + query.lower() + "%"
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT m.id AS message_id, m.conversation_id, m.created_at,
                       m.role, m.route, m.model, m.content,
                       c.title
                FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                WHERE c.archived = 0
                  AND (
                      lower(m.content) LIKE ?
                      OR lower(c.title) LIKE ?
                  )
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, max(1, int(limit))),
            ).fetchall()

            return [
                {
                    **dict(row),
                    "excerpt": excerpt(row["content"], 280),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def model_window(self, conversation_id, max_chars):
        """Newest chronological text that fits a model's prompt window.

        This never changes stored messages.  Older material remains in the
        registry and is searchable/retrievable when needed.
        """
        rows = self.messages(conversation_id)
        chosen = []
        used = 0

        for row in reversed(rows):
            size = len(row["content"])

            if chosen and used + size > max_chars:
                break

            chosen.append(row)
            used += size

        chosen.reverse()
        return chosen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=str(Path.home() / "ShopAI"),
        help="ShopAI root directory",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("current")
    sub.add_parser("self-test")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=12)

    new_parser = sub.add_parser("new")
    new_parser.add_argument("title", nargs="*", default=["Untitled ShopAI Conversation"])

    select_parser = sub.add_parser("select")
    select_parser.add_argument("conversation_id")

    rename_parser = sub.add_parser("rename")
    rename_parser.add_argument("conversation_id")
    rename_parser.add_argument("title", nargs="+")

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query", nargs="+")

    read_parser = sub.add_parser("read")
    read_parser.add_argument("conversation_id")

    args = parser.parse_args()

    if args.command == "self-test":
        with tempfile.TemporaryDirectory(prefix="shopai-registry-") as temporary:
            registry = ConversationRegistry(temporary)
            first = registry.current_id()
            registry.append(first, "user", "Remember cobalt-47.", "user")
            registry.append(first, "assistant", "I will remember cobalt-47.", "local", "test-model")

            second = registry.create("Second test conversation")
            registry.append(second, "user", "Discuss quill drive.", "user")

            found = registry.search("cobalt-47")
            assert found and found[0]["conversation_id"] == first

            registry.select(first)
            assert registry.current_id() == first
            assert len(registry.messages(first)) == 2

        print("ShopAI conversation registry self-test: PASS")
        return 0

    registry = ConversationRegistry(args.root)

    if args.command == "current":
        print(registry.current_id())
        return 0

    if args.command == "list":
        print(json.dumps(registry.recent(args.limit), indent=2))
        return 0

    if args.command == "new":
        print(registry.create(" ".join(args.title)))
        return 0

    if args.command == "select":
        registry.select(args.conversation_id)
        print(f"Current conversation: {args.conversation_id}")
        return 0

    if args.command == "rename":
        registry.rename(args.conversation_id, " ".join(args.title))
        print(f"Renamed: {args.conversation_id}")
        return 0

    if args.command == "search":
        print(json.dumps(registry.search(" ".join(args.query)), indent=2))
        return 0

    if args.command == "read":
        print(json.dumps(registry.messages(args.conversation_id), indent=2))
        return 0

    raise SystemExit("Unknown command.")


if __name__ == "__main__":
    raise SystemExit(main())
