"""Tests for pi_team tools."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pi_team.runtime import TeamRuntime, clear_team_runtime, configure_team_runtime


@pytest.fixture(autouse=True)
def _clear_team_runtime_fixture() -> None:
    clear_team_runtime()
    yield
    clear_team_runtime()


def _init_team_db(db_path: Path) -> None:
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
        INSERT INTO sessions (id, tenant_id, agent_id, agent_version, agent_snapshot, created_at)
        VALUES ('sess-1', 'default', 'agt-lead', 1, '{}', 0)
        """
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_team_create_tool_persists_and_emits(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
    _init_team_db(db_path)
    append_mock = AsyncMock()
    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
            append_session_events=append_mock,
            enqueue_session_events=AsyncMock(),
        )
    )
    from pi_team.tools import TeamCreateTool

    tool = TeamCreateTool()
    result = await tool.execute("", {"name": "alpha"})
    assert not result.is_error
    text = result.content[0].text
    payload = json.loads(text)
    assert payload["name"] == "alpha"
    assert payload["id"].startswith("team-")
    assert len(payload["members"]) == 1
    lead = payload["members"][0]
    assert lead["display_name"] == "lead"
    assert lead["role"] == "lead"
    assert lead["agent_id"] == "agt-lead"
    assert lead["thread_id"] == "sthr_primary"

    append_mock.assert_awaited()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT name FROM teams WHERE session_id = 'sess-1'"
    ).fetchone()
    member_rows = conn.execute(
        "SELECT display_name, thread_id, role FROM team_members"
    ).fetchall()
    conn.close()
    assert row is not None
    assert row[0] == "alpha"
    assert member_rows == [("lead", "sthr_primary", "lead")]
