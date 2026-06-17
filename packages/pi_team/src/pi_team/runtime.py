"""Per-turn runtime for team tools (ContextVar isolation)."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from pi_team.loop import TeammateLoopManager


def _default_loop_manager() -> TeammateLoopManager:
    from pi_team.loop import TeammateLoopManager

    return TeammateLoopManager()


TEAM_TOOL_NAMES = frozenset(
    {
        "team_create",
        "spawn_teammate",
        "send_team_message",
        "read_team_messages",
    }
)

AppendEventsFn = Callable[[list[dict[str, Any]]], Awaitable[None]]
EnqueueEventsFn = Callable[..., Awaitable[None]]


@dataclass
class TeamRuntime:
    session_id: str | None = None
    tenant_id: str | None = None
    platform_base: str | None = None
    internal_secret: str | None = None
    database_path: str | None = None
    lead_agent_id: str | None = None
    lead_member_id: str | None = None
    active_team_id: str | None = None
    enabled_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(TEAM_TOOL_NAMES)
    )
    append_session_events: AppendEventsFn | None = None
    enqueue_session_events: EnqueueEventsFn | None = None
    loop_manager: TeammateLoopManager = field(
        default_factory=_default_loop_manager,
        repr=False,
    )


_runtime: ContextVar[TeamRuntime | None] = ContextVar(
    "team_runtime",
    default=None,
)


def configure_team_runtime(runtime: TeamRuntime) -> Token:
    return _runtime.set(runtime)


def get_team_runtime() -> TeamRuntime | None:
    return _runtime.get()


def reset_team_runtime(token: Token) -> None:
    _runtime.reset(token)


def clear_team_runtime() -> None:
    runtime = _runtime.get()
    if runtime is not None and runtime.session_id:
        try:
            asyncio.get_running_loop().create_task(
                runtime.loop_manager.stop_all_for_session(runtime.session_id)
            )
        except RuntimeError:
            pass
    _runtime.set(None)
