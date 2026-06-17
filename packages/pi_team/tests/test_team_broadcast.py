"""Broadcast fan-out for send_team_message (to=\"*\")."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi_team.runtime import TeamRuntime, clear_team_runtime, configure_team_runtime
from pi_team.service import (
    create_team,
    read_team_messages,
    send_team_message,
    spawn_teammate,
)


@pytest.fixture(autouse=True)
def _clear_team_runtime_fixture() -> None:
    clear_team_runtime()
    yield
    clear_team_runtime()


@pytest.fixture
def mock_team_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_events: list[object]) -> None:
        return None

    monkeypatch.setattr("pi_team.service.append_session_events", _noop)
    monkeypatch.setattr("pi_team.service.enqueue_session_events", _noop)


def _init_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL DEFAULT 'default',
          agent_id TEXT NOT NULL,
          agent_version INTEGER NOT NULL DEFAULT 1,
          agent_snapshot TEXT NOT NULL DEFAULT '{}',
          title TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'idle',
          turn_id TEXT,
          created_at INTEGER NOT NULL DEFAULT 0,
          updated_at INTEGER
        );
        CREATE TABLE agents (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL DEFAULT 'default',
          config TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1,
          created_at INTEGER NOT NULL DEFAULT 0,
          updated_at INTEGER,
          archived_at INTEGER
        );
        CREATE TABLE teams (
          id TEXT PRIMARY KEY NOT NULL,
          session_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT,
          lead_thread_id TEXT NOT NULL DEFAULT 'sthr_primary',
          lead_agent_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at INTEGER NOT NULL,
          UNIQUE(session_id, name)
        );
        CREATE TABLE team_members (
          id TEXT PRIMARY KEY NOT NULL,
          team_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          color TEXT,
          thread_id TEXT,
          role TEXT,
          plan_mode_required INTEGER NOT NULL DEFAULT 0,
          backend_type TEXT NOT NULL DEFAULT 'in_process',
          status TEXT NOT NULL DEFAULT 'idle',
          joined_at INTEGER NOT NULL,
          UNIQUE(team_id, display_name)
        );
        CREATE TABLE agent_messages (
          id TEXT PRIMARY KEY NOT NULL,
          team_id TEXT NOT NULL,
          from_member_id TEXT NOT NULL,
          to_member_id TEXT,
          message_type TEXT NOT NULL DEFAULT 'text',
          body TEXT NOT NULL,
          summary TEXT,
          read_at INTEGER,
          created_at INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO agents (id, tenant_id, config, created_at)
        VALUES
          ('agt-lead', 'default', '{}', 0),
          ('agt-w1', 'default', '{}', 0),
          ('agt-w2', 'default', '{}', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO sessions (id, tenant_id, agent_id, agent_version, agent_snapshot, created_at)
        VALUES ('sess-1', 'default', 'agt-lead', 1, '{}', 0)
        """
    )
    conn.commit()
    conn.close()


def _configure(db_path: Path) -> None:
    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            platform_base="http://127.0.0.1:8787",
            internal_secret="secret",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
        )
    )


@pytest.mark.asyncio
async def test_broadcast_fan_out_per_recipient(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "crew", "start_poll_loop": False},
    )
    team_id = team["id"]
    lead_id = team["members"][0]["id"]

    w1 = await spawn_teammate(
        "sess-1",
        {
            "team_id": team_id,
            "agent_id": "agt-w1",
            "display_name": "coder-1",
            "start_poll_loop": False,
        },
    )
    w2 = await spawn_teammate(
        "sess-1",
        {
            "team_id": team_id,
            "agent_id": "agt-w2",
            "display_name": "coder-2",
            "start_poll_loop": False,
        },
    )

    result = await send_team_message(
        "sess-1",
        {
            "team_id": team_id,
            "from_member_id": lead_id,
            "to": "*",
            "body": "All hands",
            "run_target_turn": False,
        },
    )
    assert result["broadcast"] is True
    assert result["recipient_count"] == 2
    assert len(result["message_ids"]) == 2

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT to_member_id, body FROM agent_messages
        WHERE team_id = ?
        ORDER BY to_member_id
        """,
        (team_id,),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[0] for r in rows} == {w1["id"], w2["id"]}
    assert all(r[1] == "All hands" for r in rows)

    unread_w1 = await read_team_messages(
        "sess-1",
        {"team_id": team_id, "recipient_member_id": w1["id"]},
    )
    unread_w2 = await read_team_messages(
        "sess-1",
        {"team_id": team_id, "recipient_member_id": w2["id"]},
    )
    assert len(unread_w1["messages"]) == 1
    assert len(unread_w2["messages"]) == 1

    marked = await read_team_messages(
        "sess-1",
        {
            "team_id": team_id,
            "recipient_member_id": w1["id"],
            "mark_read": True,
        },
    )
    assert len(marked["messages"]) == 1

    still_unread_w2 = await read_team_messages(
        "sess-1",
        {"team_id": team_id, "recipient_member_id": w2["id"]},
    )
    assert len(still_unread_w2["messages"]) == 1

    conn = sqlite3.connect(db_path)
    read_count = conn.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE read_at IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert read_count == 1


@pytest.mark.asyncio
async def test_broadcast_excludes_sender(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "solo", "start_poll_loop": False},
    )
    lead_id = team["members"][0]["id"]

    result = await send_team_message(
        "sess-1",
        {
            "team_id": team["id"],
            "from_member_id": lead_id,
            "to": "*",
            "body": "Nobody else",
            "run_target_turn": False,
        },
    )
    assert result["recipient_count"] == 0
    assert result["message_ids"] == []

    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM agent_messages"
    ).fetchone()[0]
    conn.close()
    assert count == 0
