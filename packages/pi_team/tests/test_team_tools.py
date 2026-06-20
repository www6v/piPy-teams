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
        CREATE TABLE team_tasks (
          id TEXT PRIMARY KEY NOT NULL,
          team_id TEXT NOT NULL,
          subject TEXT NOT NULL,
          description TEXT,
          active_form TEXT,
          owner_member_id TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          blocks_json TEXT NOT NULL DEFAULT '[]',
          blocked_by_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
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


# ── team task tool tests ───────────────────────────────────────────────────────


def _setup_runtime_with_team(db_path, *, team_id: str, session_id: str = "sess-1"):
    from pi_team.store import TeamStore

    store = TeamStore(str(db_path))
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, tenant_id, agent_id, agent_version, agent_snapshot, created_at) "
        "VALUES (?, 'default', 'agt-lead', 1, '{}', 0)",
        (session_id,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO teams (id, session_id, tenant_id, name, description, lead_thread_id, lead_agent_id, status, created_at) "
        "VALUES (?, ?, 'default', 'test-team', '', 'sthr_primary', 'agt-lead', 'active', 0)",
        (team_id, session_id),
    )
    conn.commit()
    conn.close()
    return store


@pytest.mark.asyncio
async def test_team_task_create_and_list(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
    _init_team_db(db_path)
    team_id = "team-test001"
    _setup_runtime_with_team(db_path, team_id=team_id)

    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
            append_session_events=AsyncMock(),
            enqueue_session_events=AsyncMock(),
        )
    )

    from pi_team.tools import TeamTaskCreateTool, TeamTaskListTool

    create_tool = TeamTaskCreateTool()
    result = await create_tool.execute(
        "",
        {
            "team_id": team_id,
            "subject": "Write tests",
            "description": "Add unit tests for the new feature",
        },
    )
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["subject"] == "Write tests"
    assert payload["status"] == "pending"
    task_id = payload["id"]
    assert task_id.startswith("ttsk-")

    list_tool = TeamTaskListTool()
    list_result = await list_tool.execute("", {"team_id": team_id})
    assert not list_result.is_error
    tasks = json.loads(list_result.content[0].text)["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id
    assert tasks[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_team_task_update_status(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
    _init_team_db(db_path)
    team_id = "team-test002"
    _setup_runtime_with_team(db_path, team_id=team_id)

    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
            append_session_events=AsyncMock(),
            enqueue_session_events=AsyncMock(),
        )
    )

    from pi_team.tools import TeamTaskCreateTool, TeamTaskUpdateTool

    create_tool = TeamTaskCreateTool()
    create_result = await create_tool.execute(
        "", {"team_id": team_id, "subject": "Deploy to prod"}
    )
    task_id = json.loads(create_result.content[0].text)["id"]

    update_tool = TeamTaskUpdateTool()
    update_result = await update_tool.execute(
        "", {"team_id": team_id, "task_id": task_id, "status": "in_progress"}
    )
    assert not update_result.is_error
    payload = json.loads(update_result.content[0].text)
    assert payload["success"] is True
    assert "status" in payload["updated_fields"]
    assert payload["task"]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_team_task_delete(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
    _init_team_db(db_path)
    team_id = "team-test003"
    _setup_runtime_with_team(db_path, team_id=team_id)

    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
            append_session_events=AsyncMock(),
            enqueue_session_events=AsyncMock(),
        )
    )

    from pi_team.tools import TeamTaskCreateTool, TeamTaskListTool, TeamTaskUpdateTool

    create_tool = TeamTaskCreateTool()
    create_result = await create_tool.execute(
        "", {"team_id": team_id, "subject": "Temporary task"}
    )
    task_id = json.loads(create_result.content[0].text)["id"]

    update_tool = TeamTaskUpdateTool()
    del_result = await update_tool.execute(
        "", {"team_id": team_id, "task_id": task_id, "status": "deleted"}
    )
    assert not del_result.is_error
    payload = json.loads(del_result.content[0].text)
    assert payload["deleted"] is True

    list_tool = TeamTaskListTool()
    list_result = await list_tool.execute("", {"team_id": team_id})
    tasks = json.loads(list_result.content[0].text)["tasks"]
    assert tasks == []


@pytest.mark.asyncio
async def test_team_task_dependencies(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
    _init_team_db(db_path)
    team_id = "team-test004"
    _setup_runtime_with_team(db_path, team_id=team_id)

    configure_team_runtime(
        TeamRuntime(
            session_id="sess-1",
            tenant_id="default",
            database_path=str(db_path),
            lead_agent_id="agt-lead",
            append_session_events=AsyncMock(),
            enqueue_session_events=AsyncMock(),
        )
    )

    from pi_team.tools import TeamTaskCreateTool, TeamTaskGetTool, TeamTaskUpdateTool

    create_tool = TeamTaskCreateTool()
    t1 = json.loads(
        (await create_tool.execute("", {"team_id": team_id, "subject": "Step 1"})).content[0].text
    )["id"]
    t2 = json.loads(
        (await create_tool.execute("", {"team_id": team_id, "subject": "Step 2"})).content[0].text
    )["id"]

    # t2 is blocked by t1
    update_tool = TeamTaskUpdateTool()
    await update_tool.execute(
        "", {"team_id": team_id, "task_id": t2, "add_blocked_by": [t1]}
    )

    get_tool = TeamTaskGetTool()
    detail = json.loads(
        (await get_tool.execute("", {"team_id": team_id, "task_id": t2})).content[0].text
    )["task"]
    assert t1 in detail["blocked_by"]