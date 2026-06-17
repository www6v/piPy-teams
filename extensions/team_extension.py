"""piPy extension: team coordination tools.

Business logic lives in pi_team/service.py (SQLite + platform events).
Host must configure TeamRuntime before the extension loads (OMA turn).
"""

from __future__ import annotations

from typing import Any

from pi_team.runtime import TEAM_TOOL_NAMES, get_team_runtime
from pi_team.tools import (
    ReadTeamMessagesTool,
    SendTeamMessageTool,
    SpawnTeammateTool,
    TeamCreateTool,
)


def register(api: Any) -> None:
    runtime = get_team_runtime()
    if runtime is None or runtime.session_id is None:
        return

    enabled = runtime.enabled_tools or TEAM_TOOL_NAMES
    tools = [
        TeamCreateTool(),
        SpawnTeammateTool(),
        SendTeamMessageTool(),
        ReadTeamMessagesTool(),
    ]
    for tool in tools:
        if tool.name in enabled:
            api.register_tool(tool)
