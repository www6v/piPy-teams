"""Serialize team rows for tool/API responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pi_team.store import AgentMessageRow, TeamMemberRow, TeamRow


def format_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def null_if_empty(value: str) -> str | None:
    return value if value else None


def serialize_member(member: TeamMemberRow) -> dict[str, Any]:
    return {
        "id": member.id,
        "team_id": member.team_id,
        "agent_id": member.agent_id,
        "display_name": member.display_name,
        "color": null_if_empty(member.color),
        "thread_id": null_if_empty(member.thread_id),
        "role": null_if_empty(member.role),
        "backend_type": member.backend_type,
        "status": member.status,
        "joined_at": format_iso(member.joined_at),
    }


def serialize_team(
    team: TeamRow,
    members: list[TeamMemberRow],
) -> dict[str, Any]:
    return {
        "id": team.id,
        "session_id": team.session_id,
        "name": team.name,
        "description": null_if_empty(team.description),
        "lead_thread_id": team.lead_thread_id,
        "lead_agent_id": team.lead_agent_id,
        "status": team.status,
        "created_at": format_iso(team.created_at),
        "members": [serialize_member(m) for m in members],
    }


def serialize_message(msg: AgentMessageRow) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": msg.id,
        "team_id": msg.team_id,
        "from_member_id": msg.from_member_id,
        "message_type": msg.message_type,
        "body": msg.body,
        "summary": null_if_empty(msg.summary),
        "created_at": format_iso(msg.created_at),
    }
    if msg.to_member_id:
        out["to_member_id"] = msg.to_member_id
    if msg.read_at is not None:
        out["read_at"] = format_iso(msg.read_at)
    return out
