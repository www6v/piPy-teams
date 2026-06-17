"""Tests for pi_team long-running poll loop."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest

from pi_team.loop import (
    TeammateLoopConfig,
    TeammateLoopManager,
    format_mailbox_prompt,
)
from pi_team.runtime import TeamRuntime, clear_team_runtime, configure_team_runtime
from pi_team.store import AgentMessageRow, TeamMemberRow, TeamStore


@pytest.fixture(autouse=True)
def _reset_loop_state() -> None:
    clear_team_runtime()
    yield
    clear_team_runtime()


def _member() -> TeamMemberRow:
    return TeamMemberRow(
        id="tmem_worker",
        team_id="team-1",
        agent_id="agt-worker",
        display_name="worker",
        color="",
        thread_id="sthr_worker",
        role="",
        backend_type="in_process",
        status="idle",
        joined_at=0,
    )


def test_format_mailbox_prompt() -> None:
    msgs = [
        AgentMessageRow(
            id="tmsg-1",
            team_id="team-1",
            from_member_id="tmem-lead",
            to_member_id="tmem_worker",
            message_type="text",
            body="Implement auth",
            summary="Auth task",
            read_at=None,
            created_at=1,
        )
    ]
    text = format_mailbox_prompt(
        msgs,
        member_names={"tmem-lead": "lead"},
    )
    assert "From lead" in text
    assert "Auth task" in text
    assert "Implement auth" in text


@pytest.mark.asyncio
async def test_loop_enqueues_turn_on_unread(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
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
          joined_at INTEGER NOT NULL
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
        "INSERT INTO sessions (id, agent_id) VALUES ('sess-1', 'agt-lead')"
    )
    conn.execute(
        """
        INSERT INTO team_members (
          id, team_id, agent_id, display_name, thread_id,
          backend_type, status, joined_at
        ) VALUES (
          'tmem_worker', 'team-1', 'agt-worker', 'worker', 'sthr_worker',
          'in_process', 'idle', 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO team_members (
          id, team_id, agent_id, display_name, thread_id,
          backend_type, status, joined_at
        ) VALUES (
          'tmem-lead', 'team-1', 'agt-lead', 'lead', 'sthr_primary',
          'in_process', 'idle', 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO agent_messages (
          id, team_id, from_member_id, to_member_id,
          message_type, body, created_at
        ) VALUES (
          'tmsg-1', 'team-1', 'tmem-lead', 'tmem_worker',
          'text', 'Do the thing', 1
        )
        """
    )
    conn.commit()
    conn.close()

    enqueue_mock = AsyncMock()
    append_mock = AsyncMock()
    runtime = TeamRuntime(
        session_id="sess-1",
        database_path=str(db_path),
        append_session_events=append_mock,
        enqueue_session_events=enqueue_mock,
    )
    configure_team_runtime(runtime)
    manager = runtime.loop_manager
    cfg = TeammateLoopConfig(poll_interval_sec=0.05, idle_timeout_sec=30)

    started = await manager.start(
        _member(),
        session_id="sess-1",
        config=cfg,
    )
    assert started
    await asyncio.sleep(0.2)
    await manager.stop("sess-1", "tmem_worker")

    enqueue_mock.assert_awaited()
    call_events = enqueue_mock.await_args.args[0]
    assert call_events[0]["session_thread_id"] == "sthr_worker"
    assert "Do the thing" in call_events[0]["content"][0]["text"]

    store = TeamStore(str(db_path))
    msgs = store.list_unread_messages("team-1", "tmem_worker")
    assert msgs == []


@pytest.mark.asyncio
async def test_loop_shutdown_stops_and_responds(tmp_path) -> None:
    db_path = tmp_path / "oma.db"
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
          joined_at INTEGER NOT NULL
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
        "INSERT INTO sessions (id, agent_id) VALUES ('sess-1', 'agt-lead')"
    )
    conn.execute(
        """
        INSERT INTO team_members (
          id, team_id, agent_id, display_name, thread_id,
          backend_type, status, joined_at
        ) VALUES (
          'tmem_worker', 'team-1', 'agt-worker', 'worker', 'sthr_worker',
          'in_process', 'idle', 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO team_members (
          id, team_id, agent_id, display_name, thread_id,
          backend_type, status, joined_at
        ) VALUES (
          'tmem-lead', 'team-1', 'agt-lead', 'lead', 'sthr_primary',
          'in_process', 'idle', 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO agent_messages (
          id, team_id, from_member_id, to_member_id,
          message_type, body, created_at
        ) VALUES (
          'tmsg-shutdown', 'team-1', 'tmem-lead', 'tmem_worker',
          'shutdown_request', 'please stop', 1
        )
        """
    )
    conn.commit()
    conn.close()

    enqueue_mock = AsyncMock()
    append_mock = AsyncMock()
    runtime = TeamRuntime(
        session_id="sess-1",
        database_path=str(db_path),
        append_session_events=append_mock,
        enqueue_session_events=enqueue_mock,
    )
    configure_team_runtime(runtime)
    manager = runtime.loop_manager
    cfg = TeammateLoopConfig(poll_interval_sec=0.05, idle_timeout_sec=30)

    await manager.start(_member(), session_id="sess-1", config=cfg)
    await asyncio.sleep(0.25)

    enqueue_mock.assert_not_awaited()
    append_mock.assert_awaited()

    store = TeamStore(str(db_path))
    worker = store.get_member_by_id("team-1", "tmem_worker")
    assert worker is not None
    assert worker.status == "shutdown"

    responses = [
        m
        for m in store.list_unread_messages("team-1", "tmem-lead")
        if m.message_type == "shutdown_response"
    ]
    assert len(responses) == 1
    assert responses[0].body == "approved"
