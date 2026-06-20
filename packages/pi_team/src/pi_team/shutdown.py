"""Teammate shutdown state machine (request → shutting_down → shutdown)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pi_team.ids import new_team_message_id
from pi_team.platform import append_session_events
from pi_team.store import AgentMessageRow, TeamMemberRow, TeamStore

STATUS_IDLE = "idle"
STATUS_LISTENING = "listening"
STATUS_ACTIVE = "active"
STATUS_SHUTTING_DOWN = "shutting_down"
STATUS_SHUTDOWN = "shutdown"

TERMINAL_STATUSES = frozenset({STATUS_SHUTDOWN})
SHUTDOWN_IN_PROGRESS = frozenset({STATUS_SHUTTING_DOWN, STATUS_SHUTDOWN})


class MemberShutdownError(RuntimeError):
    """Invalid shutdown transition or duplicate request."""


def member_can_receive_messages(status: str) -> bool:
    return status not in SHUTDOWN_IN_PROGRESS


def assert_member_can_shutdown(status: str) -> None:
    if status == STATUS_SHUTDOWN:
        raise MemberShutdownError("member already shutdown")
    if status == STATUS_SHUTTING_DOWN:
        raise MemberShutdownError("member shutdown already in progress")


def _now_ms() -> int:
    return int(time.time() * 1000)


async def request_teammate_shutdown(
    session_id: str,
    *,
    store: TeamStore,
    team_id: str,
    target_member_id: str,
    from_member_id: str,
    body: str,
    summary: str = "",
) -> dict[str, Any]:
    """Begin shutdown: shutting_down → message → stop loop → complete."""
    target = store.get_member_by_id(team_id, target_member_id)
    if target is None:
        raise MemberShutdownError("target member not found")
    if target.backend_type != "in_process":
        raise MemberShutdownError(
            "shutdown only supported for in_process members"
        )

    from_member = store.get_member_by_id(team_id, from_member_id)
    if from_member is None:
        raise MemberShutdownError("from_member_id not found")

    assert_member_can_shutdown(target.status)

    store.update_member_status(target.id, STATUS_SHUTTING_DOWN)
    await append_session_events(
        [
            {
                "type": "team.member_shutting_down",
                "team_id": team_id,
                "member_id": target.id,
                "display_name": target.display_name,
                "session_thread_id": target.thread_id,
            }
        ]
    )

    now = _now_ms()
    msg_id = new_team_message_id()
    msg = AgentMessageRow(
        id=msg_id,
        team_id=team_id,
        from_member_id=from_member.id,
        to_member_id=target.id,
        message_type="shutdown_request",
        body=body,
        summary=summary,
        read_at=None,
        created_at=now,
    )
    store.create_message(msg)

    team_msg: dict[str, Any] = {
        "type": "team.message",
        "team_id": team_id,
        "message_id": msg_id,
        "from_member_id": from_member.id,
        "from_display_name": from_member.display_name,
        "to": target.display_name,
        "to_member_id": target.id,
        "message_type": "shutdown_request",
        "summary": summary or None,
        "body": body,
    }
    if target.thread_id:
        team_msg["session_thread_id"] = target.thread_id
    await append_session_events([team_msg])

    from pi_team.loop import get_loop_manager

    await get_loop_manager().stop(session_id, target.id)

    await complete_teammate_shutdown(
        store,
        session_id=session_id,
        member=target,
        requests=[msg],
        mark_read_ids=[msg_id],
    )

    return {
        "message_id": msg_id,
        "team_id": team_id,
        "member_id": target.id,
        "display_name": target.display_name,
        "status": STATUS_SHUTDOWN,
    }


async def complete_teammate_shutdown(
    store: TeamStore,
    *,
    session_id: str,
    member: TeamMemberRow,
    requests: list[AgentMessageRow],
    mark_read_ids: list[str] | None = None,
) -> None:
    """Finalize shutdown: respond to requests, emit team.member_shutdown."""
    current = store.get_member_by_id(member.team_id, member.id)
    if current is None:
        return
    if current.status == STATUS_SHUTDOWN:
        return

    store.update_member_status(member.id, STATUS_SHUTDOWN)
    for req in requests:
        await send_shutdown_response(
            store,
            session_id=session_id,
            member=member,
            to_member_id=req.from_member_id,
            approved=True,
        )

    if mark_read_ids:
        await asyncio.to_thread(
            store.mark_messages_read,
            member.team_id,
            member.id,
            mark_read_ids,
        )

    await append_session_events(
        [
            {
                "type": "team.member_shutdown",
                "team_id": member.team_id,
                "member_id": member.id,
                "display_name": member.display_name,
                "session_thread_id": member.thread_id,
            }
        ]
    )


async def send_shutdown_response(
    store: TeamStore,
    *,
    session_id: str,
    member: TeamMemberRow,
    to_member_id: str,
    approved: bool,
) -> None:
    del session_id
    body = "approved" if approved else "rejected"
    now = _now_ms()
    msg = AgentMessageRow(
        id=new_team_message_id(),
        team_id=member.team_id,
        from_member_id=member.id,
        to_member_id=to_member_id,
        message_type="shutdown_response",
        body=body,
        summary="",
        read_at=None,
        created_at=now,
    )
    store.create_message(msg)
    recipient = store.get_member_by_id(member.team_id, to_member_id)
    team_msg: dict[str, Any] = {
        "type": "team.message",
        "team_id": member.team_id,
        "message_id": msg.id,
        "from_member_id": member.id,
        "from_display_name": member.display_name,
        "to": recipient.display_name if recipient else to_member_id,
        "message_type": "shutdown_response",
        "body": body,
    }
    if recipient is not None:
        team_msg["to_member_id"] = recipient.id
    # Tag with the sender's thread so this protocol event doesn't land in the
    # recipient's primary-thread history between a tool_use and its tool_result.
    if member.thread_id:
        team_msg["session_thread_id"] = member.thread_id
    await append_session_events([team_msg])


async def drain_pending_shutdowns(session_id: str) -> None:
    """Complete shutdown for members stuck in shutting_down (e.g. Console path)."""
    from pi_team.runtime import get_team_runtime
    from pi_team.store import resolve_database_path

    runtime = get_team_runtime()
    if runtime is None:
        return
    db_path = resolve_database_path(runtime.database_path)
    store = TeamStore(db_path)
    teams = store.list_teams_for_session(session_id)
    for team in teams:
        for member in store.list_members(team.id):
            if member.status != STATUS_SHUTTING_DOWN:
                continue
            messages = store.list_unread_messages(
                team.id,
                member.id,
                100,
            )
            shutdown_reqs = [
                m
                for m in messages
                if m.message_type == "shutdown_request"
            ]
            if not shutdown_reqs:
                continue
            all_ids = [m.id for m in messages]
            await complete_teammate_shutdown(
                store,
                session_id=session_id,
                member=member,
                requests=shutdown_reqs,
                mark_read_ids=all_ids,
            )
