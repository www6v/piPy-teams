"""ContextVar isolation for TeamRuntime."""

from __future__ import annotations

import asyncio

import pytest

from pi_team.runtime import (
    TeamRuntime,
    configure_team_runtime,
    get_team_runtime,
    reset_team_runtime,
)


@pytest.mark.asyncio
async def test_runtime_context_isolation() -> None:
    outer = TeamRuntime(session_id="sess-outer")
    token = configure_team_runtime(outer)
    assert get_team_runtime() is outer

    seen: list[str | None] = []

    async def inner_task() -> None:
        inner = TeamRuntime(session_id="sess-inner")
        inner_token = configure_team_runtime(inner)
        seen.append(get_team_runtime().session_id if get_team_runtime() else None)
        reset_team_runtime(inner_token)

    await inner_task()
    seen.append(get_team_runtime().session_id if get_team_runtime() else None)
    reset_team_runtime(token)

    assert seen == ["sess-inner", "sess-outer"]


@pytest.mark.asyncio
async def test_loop_manager_scoped_per_runtime() -> None:
    runtime_a = TeamRuntime(session_id="sess-a")
    runtime_b = TeamRuntime(session_id="sess-b")
    assert runtime_a.loop_manager is not runtime_b.loop_manager

    token_a = configure_team_runtime(runtime_a)
    assert get_team_runtime() is runtime_a
    reset_team_runtime(token_a)

    token_b = configure_team_runtime(runtime_b)
    assert get_team_runtime() is runtime_b
    assert get_team_runtime().loop_manager is runtime_b.loop_manager
    reset_team_runtime(token_b)
