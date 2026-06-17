"""Team coordination library (host-agnostic)."""

from pi_team.runtime import (
    TeamRuntime,
    clear_team_runtime,
    configure_team_runtime,
    get_team_runtime,
)
from pi_team.types import TeamMemberRef, TeamRef

__all__ = [
    "TeamMemberRef",
    "TeamRef",
    "TeamRuntime",
    "clear_team_runtime",
    "configure_team_runtime",
    "get_team_runtime",
    "get_loop_manager",
]


def __getattr__(name: str):
    if name == "get_loop_manager":
        from pi_team.loop import get_loop_manager

        return get_loop_manager
    raise AttributeError(name)
