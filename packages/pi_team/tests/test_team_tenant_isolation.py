"""Tenant and session isolation for pi_team harness."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi_team.runtime import TeamRuntime, clear_team_runtime, configure_team_runtime
from pi_team.service import TeamNotFoundError, TeamServiceError, create_team, spawn_teammate


@pytest.fixture(autouse=True)
def _clear_team_runtime_fixture() -> None:
    clear_team_runtime()
    yield
    clear_team_runtime()


def _init_multi_tenant_db(db_path: Path) -> None:
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
          ('agt-a-lead', 'tenant-a', '{"name":"lead-a"}', 0),
          ('agt-a-worker', 'tenant-a', '{"name":"worker-a"}', 0),
          ('agt-b-worker', 'tenant-b', '{"name":"worker-b"}', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO sessions (id, tenant_id, agent_id, agent_version, agent_snapshot, created_at)
        VALUES
          ('sess-a', 'tenant-a', 'agt-a-lead', 1, '{}', 0),
          ('sess-b', 'tenant-b', 'agt-a-lead', 1, '{}', 0)
        """
    )
    conn.commit()
    conn.close()


def _configure_runtime(
    db_path: Path,
    *,
    session_id: str,
    tenant_id: str,
    lead_agent_id: str,
) -> None:
    configure_team_runtime(
        TeamRuntime(
            session_id=session_id,
            tenant_id=tenant_id,
            platform_base="http://127.0.0.1:8787",
            internal_secret="secret",
            database_path=str(db_path),
            lead_agent_id=lead_agent_id,
        )
    )


@pytest.fixture
def mock_team_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(_events: list[object]) -> None:
        return None

    monkeypatch.setattr("pi_team.service.append_session_events", _noop)


@pytest.mark.asyncio
async def test_create_team_uses_session_tenant_id(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_multi_tenant_db(db_path)
    _configure_runtime(
        db_path,
        session_id="sess-a",
        tenant_id="tenant-a",
        lead_agent_id="agt-a-lead",
    )

    payload = await create_team("sess-a", {"name": "alpha"})
    assert payload["name"] == "alpha"

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT tenant_id FROM teams WHERE id = ?",
        (payload["id"],),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "tenant-a"


@pytest.mark.asyncio
async def test_spawn_teammate_rejects_cross_tenant_agent(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_multi_tenant_db(db_path)
    _configure_runtime(
        db_path,
        session_id="sess-a",
        tenant_id="tenant-a",
        lead_agent_id="agt-a-lead",
    )

    team = await create_team("sess-a", {"name": "alpha"})
    with pytest.raises(TeamServiceError, match="not found in tenant"):
        await spawn_teammate(
            "sess-a",
            {
                "team_id": team["id"],
                "agent_id": "agt-b-worker",
                "display_name": "coder",
            },
        )


@pytest.mark.asyncio
async def test_spawn_teammate_allows_same_tenant_agent(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_multi_tenant_db(db_path)
    _configure_runtime(
        db_path,
        session_id="sess-a",
        tenant_id="tenant-a",
        lead_agent_id="agt-a-lead",
    )

    team = await create_team("sess-a", {"name": "alpha"})
    member = await spawn_teammate(
        "sess-a",
        {
            "team_id": team["id"],
            "agent_id": "agt-a-worker",
            "display_name": "coder",
            "start_poll_loop": False,
        },
    )
    assert member["agent_id"] == "agt-a-worker"


@pytest.mark.asyncio
async def test_team_lookup_scoped_to_session(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_multi_tenant_db(db_path)
    _configure_runtime(
        db_path,
        session_id="sess-a",
        tenant_id="tenant-a",
        lead_agent_id="agt-a-lead",
    )

    team = await create_team("sess-a", {"name": "alpha"})
    team_id = team["id"]

    with pytest.raises(TeamNotFoundError):
        await spawn_teammate(
            "sess-b",
            {
                "team_id": team_id,
                "agent_id": "agt-a-worker",
                "display_name": "coder",
            },
        )


@pytest.mark.asyncio
async def test_create_team_rejects_cross_tenant_initial_member(
    tmp_path, mock_team_events
) -> None:
    db_path = tmp_path / "oma.db"
    _init_multi_tenant_db(db_path)
    _configure_runtime(
        db_path,
        session_id="sess-a",
        tenant_id="tenant-a",
        lead_agent_id="agt-a-lead",
    )

    with pytest.raises(TeamServiceError, match="not found in tenant"):
        await create_team(
            "sess-a",
            {
                "name": "alpha",
                "members": [
                    {
                        "agent_id": "agt-b-worker",
                        "display_name": "coder",
                    }
                ],
            },
        )

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    conn.close()
    assert count == 0
