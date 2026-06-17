"""Shutdown state machine tests for pi_team."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi_team.runtime import TeamRuntime, clear_team_runtime, configure_team_runtime
from pi_team.service import (
    TeamServiceError,
    create_team,
    send_team_message,
    spawn_teammate,
)
from pi_team.shutdown import (
    STATUS_SHUTDOWN,
    STATUS_SHUTTING_DOWN,
    drain_pending_shutdowns,
    request_teammate_shutdown,
)
from pi_team.store import AgentMessageRow, TeamStore


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
    monkeypatch.setattr("pi_team.shutdown.append_session_events", _noop)


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
          ('agt-w1', 'default', '{}', 0)
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
async def test_shutdown_request_via_send_team_message(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "crew", "start_poll_loop": False},
    )
    worker = await spawn_teammate(
        "sess-1",
        {
            "team_id": team["id"],
            "agent_id": "agt-w1",
            "display_name": "coder-1",
            "start_poll_loop": False,
        },
    )
    lead_id = team["members"][0]["id"]

    result = await send_team_message(
        "sess-1",
        {
            "team_id": team["id"],
            "from_member_id": lead_id,
            "to": "coder-1",
            "message_type": "shutdown_request",
            "body": "wrap up",
        },
    )
    assert result["status"] == STATUS_SHUTDOWN

    store = TeamStore(str(db_path))
    member = store.get_member_by_id(team["id"], worker["id"])
    assert member is not None
    assert member.status == STATUS_SHUTDOWN

    responses = store.list_unread_messages(team["id"], lead_id)
    assert any(m.message_type == "shutdown_response" for m in responses)


@pytest.mark.asyncio
async def test_duplicate_shutdown_rejected(tmp_path, mock_team_events) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "crew", "start_poll_loop": False},
    )
    await spawn_teammate(
        "sess-1",
        {
            "team_id": team["id"],
            "agent_id": "agt-w1",
            "display_name": "coder-1",
            "start_poll_loop": False,
        },
    )
    lead_id = team["members"][0]["id"]

    await send_team_message(
        "sess-1",
        {
            "team_id": team["id"],
            "from_member_id": lead_id,
            "to": "coder-1",
            "message_type": "shutdown_request",
            "body": "stop",
        },
    )

    with pytest.raises(TeamServiceError, match="already shutdown"):
        await send_team_message(
            "sess-1",
            {
                "team_id": team["id"],
                "from_member_id": lead_id,
                "to": "coder-1",
                "message_type": "shutdown_request",
                "body": "stop again",
            },
        )


@pytest.mark.asyncio
async def test_drain_pending_shutdowns_completes_console_path(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "crew", "start_poll_loop": False},
    )
    worker = await spawn_teammate(
        "sess-1",
        {
            "team_id": team["id"],
            "agent_id": "agt-w1",
            "display_name": "coder-1",
            "start_poll_loop": False,
        },
    )
    lead_id = team["members"][0]["id"]
    store = TeamStore(str(db_path))
    store.update_member_status(worker["id"], STATUS_SHUTTING_DOWN)
    from pi_team.ids import new_team_message_id

    store.create_message(
        AgentMessageRow(
            id=new_team_message_id(),
            team_id=team["id"],
            from_member_id=lead_id,
            to_member_id=worker["id"],
            message_type="shutdown_request",
            body="console shutdown",
            summary="",
            read_at=None,
            created_at=1,
        )
    )

    await drain_pending_shutdowns("sess-1")

    member = store.get_member_by_id(team["id"], worker["id"])
    assert member is not None
    assert member.status == STATUS_SHUTDOWN


@pytest.mark.asyncio
async def test_text_message_rejected_after_shutdown(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_db(db_path)
    _configure(db_path)

    team = await create_team(
        "sess-1",
        {"name": "crew", "start_poll_loop": False},
    )
    worker = await spawn_teammate(
        "sess-1",
        {
            "team_id": team["id"],
            "agent_id": "agt-w1",
            "display_name": "coder-1",
            "start_poll_loop": False,
        },
    )
    lead_id = team["members"][0]["id"]
    store = TeamStore(str(db_path))

    await request_teammate_shutdown(
        "sess-1",
        store=store,
        team_id=team["id"],
        target_member_id=worker["id"],
        from_member_id=lead_id,
        body="stop",
    )

    with pytest.raises(TeamServiceError, match="not accepting messages"):
        await send_team_message(
            "sess-1",
            {
                "team_id": team["id"],
                "from_member_id": lead_id,
                "to": "coder-1",
                "body": "more work",
            },
        )
