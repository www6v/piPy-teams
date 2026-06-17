"""piPy tool classes for team coordination."""

from __future__ import annotations

import json
from typing import Any

from pi_agent.types import AgentToolResult
from pi_ai.types import TextContent

from pi_team.client import (
    create_team,
    read_team_messages,
    send_team_message,
    spawn_teammate,
)
from pi_team.runtime import get_team_runtime


def _json_result(payload: Any, *, is_error: bool = False) -> AgentToolResult:
    text = json.dumps(payload, indent=2)
    return AgentToolResult(
        content=[TextContent(text=text)],
        is_error=is_error,
    )


class TeamCreateTool:
    name = "team_create"
    description = (
        "Create a coordinated agent team within this session. "
        "The session lead is registered automatically as member display_name "
        "\"lead\" on the primary thread (use its id as from_member_id for "
        "send_team_message). Returns team id and member ids."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique team name within the session",
            },
            "description": {
                "type": "string",
                "description": "Optional team description",
            },
            "lead_display_name": {
                "type": "string",
                "description": (
                    "Display name for the auto-registered lead member "
                    '(default "lead")'
                ),
            },
            "members": {
                "type": "array",
                "description": "Optional initial teammates to spawn",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "role": {"type": "string"},
                        "color": {"type": "string"},
                    },
                    "required": ["agent_id", "display_name"],
                },
            },
        },
        "required": ["name"],
    }
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        args: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            return _json_result({"error": "name is required"}, is_error=True)
        try:
            payload = await create_team(args)
            runtime = get_team_runtime()
            if isinstance(payload, dict) and payload.get("id"):
                runtime.active_team_id = str(payload["id"])
            return _json_result(payload)
        except RuntimeError as exc:
            return _json_result({"error": str(exc)}, is_error=True)


class SpawnTeammateTool:
    name = "spawn_teammate"
    description = (
        "Add a named teammate to an existing team. Creates a session thread "
        "and registers the member for mailbox routing."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "team_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "display_name": {
                "type": "string",
                "description": "Address used by send_team_message (to=...)",
            },
            "role": {"type": "string"},
            "color": {"type": "string"},
            "start_poll_loop": {
                "type": "boolean",
                "description": (
                    "Start background mailbox poll loop (default true)"
                ),
            },
        },
        "required": ["team_id", "agent_id", "display_name"],
    }
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        args: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        try:
            payload = await spawn_teammate(args)
            return _json_result(payload)
        except RuntimeError as exc:
            return _json_result({"error": str(exc)}, is_error=True)


class SendTeamMessageTool:
    name = "send_team_message"
    description = (
        "Send a mailbox message to a teammate (by display_name) or broadcast "
        "with to=\"*\". Use message_type shutdown_request to shut down a "
        "teammate (runs shutdown state machine). Wakes the target thread "
        "to run a turn by default."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "team_id": {"type": "string"},
            "from_member_id": {"type": "string"},
            "to": {
                "type": "string",
                "description": "Recipient display_name or \"*\" for broadcast",
            },
            "body": {"type": "string"},
            "summary": {"type": "string"},
            "message_type": {
                "type": "string",
                "description": "text | shutdown_request | plan_approval_request",
            },
            "run_target_turn": {
                "type": "boolean",
                "description": "Enqueue user.message on target thread (default true)",
            },
        },
        "required": ["team_id", "from_member_id", "to", "body"],
    }
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        args: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        try:
            payload = await send_team_message(args)
            return _json_result(payload)
        except RuntimeError as exc:
            return _json_result({"error": str(exc)}, is_error=True)


class ReadTeamMessagesTool:
    name = "read_team_messages"
    description = (
        "Read unread mailbox messages for a team member. "
        "Optionally mark them read after fetching."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "team_id": {"type": "string"},
            "recipient_member_id": {"type": "string"},
            "mark_read": {"type": "boolean"},
            "message_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["team_id", "recipient_member_id"],
    }
    execution_mode = "parallel"

    async def execute(
        self,
        tool_call_id: str,
        args: dict[str, Any],
        signal: Any = None,
        on_update: Any = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        try:
            payload = await read_team_messages(args)
            return _json_result(payload)
        except RuntimeError as exc:
            return _json_result({"error": str(exc)}, is_error=True)
