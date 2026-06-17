"""Host-injected session event bridge (append / enqueue)."""

from __future__ import annotations

from typing import Any

from pi_team.runtime import get_team_runtime


class TeamPlatformError(RuntimeError):
    pass


async def append_session_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    runtime = get_team_runtime()
    if runtime is None or runtime.append_session_events is None:
        raise TeamPlatformError(
            "team tools unavailable: append_session_events not configured"
        )
    await runtime.append_session_events(events)


async def enqueue_session_events(
    events: list[dict[str, Any]],
    *,
    run_turn: bool = True,
) -> None:
    if not events:
        return
    runtime = get_team_runtime()
    if runtime is None or runtime.enqueue_session_events is None:
        raise TeamPlatformError(
            "team tools unavailable: enqueue_session_events not configured"
        )
    await runtime.enqueue_session_events(events, run_turn=run_turn)
