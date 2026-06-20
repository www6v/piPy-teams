"""SQLite persistence for teams (shared oma.db with oma-server)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class SessionRow:
    id: str
    tenant_id: str
    agent_id: str
    status: str


@dataclass(frozen=True)
class TeamRow:
    id: str
    session_id: str
    tenant_id: str
    name: str
    description: str
    lead_thread_id: str
    lead_agent_id: str
    status: str
    created_at: int


@dataclass(frozen=True)
class TeamMemberRow:
    id: str
    team_id: str
    agent_id: str
    display_name: str
    color: str
    thread_id: str
    role: str
    backend_type: str
    status: str
    joined_at: int


@dataclass(frozen=True)
class AgentMessageRow:
    id: str
    team_id: str
    from_member_id: str
    to_member_id: str
    message_type: str
    body: str
    summary: str
    read_at: int | None
    created_at: int


@dataclass(frozen=True)
class TeamTaskRow:
    id: str
    team_id: str
    subject: str
    description: str
    active_form: str
    owner_member_id: str
    status: str
    blocks: list[str]
    blocked_by: list[str]
    metadata: dict[str, Any]
    created_at: int
    updated_at: int


def resolve_database_path(explicit: str | None = None) -> str:
    if explicit:
        path = explicit
    else:
        path = None
        for key in ("OMA_DATABASE_PATH", "DATABASE_PATH"):
            value = os.environ.get(key)
            if value:
                path = value
                break
        if path is None:
            path = "./data/oma.db"
    return os.path.abspath(path)


class TeamStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, tenant_id, agent_id, status
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionRow(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            agent_id=str(row["agent_id"]),
            status=str(row["status"]),
        )

    def get_agent_name(self, tenant_id: str, agent_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT config
                FROM agents
                WHERE id = ? AND tenant_id = ?
                """,
                (agent_id, tenant_id or "default"),
            ).fetchone()
        if row is None:
            return None
        try:
            import json

            config = json.loads(row["config"])
            name = config.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def agent_exists(self, tenant_id: str, agent_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM agents
                WHERE id = ? AND tenant_id = ?
                """,
                (agent_id, tenant_id or "default"),
            ).fetchone()
        return row is not None

    def create_team(self, team: TeamRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO teams (
                    id, session_id, tenant_id, name, description,
                    lead_thread_id, lead_agent_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    team.id,
                    team.session_id,
                    team.tenant_id,
                    team.name,
                    team.description or None,
                    team.lead_thread_id,
                    team.lead_agent_id,
                    team.status,
                    team.created_at,
                ),
            )

    def get_team_by_id(
        self,
        session_id: str,
        team_id: str,
    ) -> TeamRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, tenant_id, name, description,
                       lead_thread_id, lead_agent_id, status, created_at
                FROM teams
                WHERE session_id = ? AND id = ?
                """,
                (session_id, team_id),
            ).fetchone()
        return _scan_team(row)

    def get_team_by_name(
        self,
        session_id: str,
        name: str,
    ) -> TeamRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, tenant_id, name, description,
                       lead_thread_id, lead_agent_id, status, created_at
                FROM teams
                WHERE session_id = ? AND name = ?
                """,
                (session_id, name),
            ).fetchone()
        return _scan_team(row)

    def list_teams_for_session(self, session_id: str) -> list[TeamRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, tenant_id, name, description,
                       lead_thread_id, lead_agent_id, status, created_at
                FROM teams
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_scan_team(row) for row in rows if row is not None]

    def create_member(self, member: TeamMemberRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO team_members (
                    id, team_id, agent_id, display_name, color, thread_id,
                    role, plan_mode_required, backend_type, status, joined_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    member.id,
                    member.team_id,
                    member.agent_id,
                    member.display_name,
                    member.color or None,
                    member.thread_id or None,
                    member.role or None,
                    member.backend_type,
                    member.status,
                    member.joined_at,
                ),
            )

    def get_member_by_id(
        self,
        team_id: str,
        member_id: str,
    ) -> TeamMemberRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, team_id, agent_id, display_name, color, thread_id,
                       role, backend_type, status, joined_at
                FROM team_members
                WHERE team_id = ? AND id = ?
                """,
                (team_id, member_id),
            ).fetchone()
        return _scan_member(row)

    def get_member_by_display_name(
        self,
        team_id: str,
        display_name: str,
    ) -> TeamMemberRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, team_id, agent_id, display_name, color, thread_id,
                       role, backend_type, status, joined_at
                FROM team_members
                WHERE team_id = ? AND display_name = ?
                """,
                (team_id, display_name),
            ).fetchone()
        return _scan_member(row)

    def list_members(self, team_id: str) -> list[TeamMemberRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, team_id, agent_id, display_name, color, thread_id,
                       role, backend_type, status, joined_at
                FROM team_members
                WHERE team_id = ?
                ORDER BY joined_at ASC
                """,
                (team_id,),
            ).fetchall()
        return [_scan_member(row) for row in rows if row is not None]

    def update_member_status(self, member_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE team_members SET status = ? WHERE id = ?",
                (status, member_id),
            )

    def create_message(self, msg: AgentMessageRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_messages (
                    id, team_id, from_member_id, to_member_id, message_type,
                    body, summary, read_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.team_id,
                    msg.from_member_id,
                    msg.to_member_id or None,
                    msg.message_type,
                    msg.body,
                    msg.summary or None,
                    msg.read_at,
                    msg.created_at,
                ),
            )

    def list_unread_messages(
        self,
        team_id: str,
        recipient_member_id: str,
        limit: int = 100,
    ) -> list[AgentMessageRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, team_id, from_member_id, to_member_id, message_type,
                       body, summary, read_at, created_at
                FROM agent_messages
                WHERE team_id = ?
                  AND read_at IS NULL
                  AND (
                    to_member_id = ?
                    OR to_member_id IS NULL
                    OR to_member_id = ''
                  )
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (team_id, recipient_member_id, limit),
            ).fetchall()
        return [_scan_message(row) for row in rows if row is not None]

    def mark_messages_read(
        self,
        team_id: str,
        recipient_member_id: str,
        message_ids: list[str],
    ) -> int:
        if not message_ids:
            return 0
        now = int(time.time() * 1000)
        placeholders = ", ".join("?" for _ in message_ids)
        query = f"""
            UPDATE agent_messages SET read_at = ?
            WHERE team_id = ?
              AND (
                to_member_id = ?
                OR to_member_id IS NULL
                OR to_member_id = ''
              )
              AND id IN ({placeholders})
        """
        params: list[Any] = [now, team_id, recipient_member_id, *message_ids]
        with self._conn() as conn:
            cur = conn.execute(query, params)
            return int(cur.rowcount)

    # ── team tasks ────────────────────────────────────────────────────────────

    def create_task(self, task: TeamTaskRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO team_tasks (
                    id, team_id, subject, description, active_form,
                    owner_member_id, status, blocks_json, blocked_by_json,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.team_id,
                    task.subject,
                    task.description or None,
                    task.active_form or None,
                    task.owner_member_id or None,
                    task.status,
                    json.dumps(task.blocks),
                    json.dumps(task.blocked_by),
                    json.dumps(task.metadata) if task.metadata else None,
                    task.created_at,
                    task.updated_at,
                ),
            )

    def get_task(self, team_id: str, task_id: str) -> TeamTaskRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, team_id, subject, description, active_form,
                       owner_member_id, status, blocks_json, blocked_by_json,
                       metadata_json, created_at, updated_at
                FROM team_tasks
                WHERE team_id = ? AND id = ?
                """,
                (team_id, task_id),
            ).fetchone()
        return _scan_task(row)

    def list_tasks(self, team_id: str) -> list[TeamTaskRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, team_id, subject, description, active_form,
                       owner_member_id, status, blocks_json, blocked_by_json,
                       metadata_json, created_at, updated_at
                FROM team_tasks
                WHERE team_id = ?
                ORDER BY created_at ASC
                """,
                (team_id,),
            ).fetchall()
        return [t for row in rows if (t := _scan_task(row)) is not None]

    def update_task(
        self,
        team_id: str,
        task_id: str,
        updates: dict[str, Any],
    ) -> bool:
        if not updates:
            return False
        now = int(time.time() * 1000)
        cols: list[str] = []
        params: list[Any] = []
        for col, val in updates.items():
            cols.append(f"{col} = ?")
            params.append(val)
        cols.append("updated_at = ?")
        params.append(now)
        params.extend([team_id, task_id])
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE team_tasks SET {', '.join(cols)} WHERE team_id = ? AND id = ?",
                params,
            )
            return int(cur.rowcount) > 0

    def delete_task(self, team_id: str, task_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM team_tasks WHERE team_id = ? AND id = ?",
                (team_id, task_id),
            )
            return int(cur.rowcount) > 0


def _scan_team(row: sqlite3.Row | None) -> TeamRow | None:
    if row is None:
        return None
    return TeamRow(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        tenant_id=str(row["tenant_id"]),
        name=str(row["name"]),
        description=str(row["description"] or ""),
        lead_thread_id=str(row["lead_thread_id"]),
        lead_agent_id=str(row["lead_agent_id"]),
        status=str(row["status"]),
        created_at=int(row["created_at"]),
    )


def _scan_member(row: sqlite3.Row | None) -> TeamMemberRow | None:
    if row is None:
        return None
    return TeamMemberRow(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        agent_id=str(row["agent_id"]),
        display_name=str(row["display_name"]),
        color=str(row["color"] or ""),
        thread_id=str(row["thread_id"] or ""),
        role=str(row["role"] or ""),
        backend_type=str(row["backend_type"]),
        status=str(row["status"]),
        joined_at=int(row["joined_at"]),
    )


def _scan_message(row: sqlite3.Row | None) -> AgentMessageRow | None:
    if row is None:
        return None
    read_at = row["read_at"]
    return AgentMessageRow(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        from_member_id=str(row["from_member_id"]),
        to_member_id=str(row["to_member_id"] or ""),
        message_type=str(row["message_type"]),
        body=str(row["body"]),
        summary=str(row["summary"] or ""),
        read_at=int(read_at) if read_at is not None else None,
        created_at=int(row["created_at"]),
    )


def _scan_task(row: sqlite3.Row | None) -> TeamTaskRow | None:
    if row is None:
        return None

    def _json_list(val: Any) -> list[str]:
        try:
            parsed = json.loads(val or "[]")
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def _json_dict(val: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(val or "{}")
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    return TeamTaskRow(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        subject=str(row["subject"]),
        description=str(row["description"] or ""),
        active_form=str(row["active_form"] or ""),
        owner_member_id=str(row["owner_member_id"] or ""),
        status=str(row["status"]),
        blocks=_json_list(row["blocks_json"]),
        blocked_by=_json_list(row["blocked_by_json"]),
        metadata=_json_dict(row["metadata_json"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )
