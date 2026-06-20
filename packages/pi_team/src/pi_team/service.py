"""Team coordination business logic (formerly internal/api/teams.go)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pi_team.ids import (
    PRIMARY_THREAD_ID,
    new_task_id,
    new_team_id,
    new_team_member_id,
    new_team_message_id,
    new_thread_id,
)
from pi_team.loop import get_loop_manager
from pi_team.platform import append_session_events, enqueue_session_events
from pi_team.runtime import get_team_runtime
from pi_team.serialize import serialize_member, serialize_message, serialize_team
from pi_team.shutdown import (
    MemberShutdownError,
    member_can_receive_messages,
    request_teammate_shutdown,
)
from pi_team.store import (
    AgentMessageRow,
    TeamMemberRow,
    TeamRow,
    TeamStore,
    TeamTaskRow,
    resolve_database_path,
)


class TeamServiceError(RuntimeError):
    pass


class TeamNotFoundError(TeamServiceError):
    pass


class SessionArchivedError(TeamServiceError):
    pass


def _store() -> TeamStore:
    runtime = get_team_runtime()
    if runtime is None:
        raise TeamServiceError("team tools unavailable: runtime not configured")
    db_path = resolve_database_path(runtime.database_path)
    return TeamStore(db_path)


def _require_session(session_id: str):
    store = _store()
    sess = store.get_session(session_id)
    if sess is None:
        raise TeamNotFoundError("not found")
    if sess.status == "archived":
        raise SessionArchivedError("session archived")
    return sess, store


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_member_specs(
    raw_members: Any,
    *,
    lead_display_name: str,
    lead_agent_id: str,
) -> list[dict[str, str]]:
    if not isinstance(raw_members, list):
        return []
    specs: list[dict[str, str]] = []
    for spec in raw_members:
        if not isinstance(spec, dict):
            continue
        agent_id = str(spec.get("agent_id") or "").strip()
        display_name = str(spec.get("display_name") or "").strip()
        if not agent_id or not display_name:
            continue
        if display_name == lead_display_name:
            continue
        if agent_id == lead_agent_id:
            continue
        specs.append(
            {
                "agent_id": agent_id,
                "display_name": display_name,
                "role": str(spec.get("role") or "").strip(),
                "color": str(spec.get("color") or "").strip(),
            }
        )
    return specs


def _validate_member_specs(
    store: TeamStore,
    tenant_id: str,
    specs: list[dict[str, str]],
) -> None:
    for spec in specs:
        if not store.agent_exists(tenant_id, spec["agent_id"]):
            raise TeamServiceError(
                f'agent "{spec["agent_id"]}" not found in tenant'
            )


def _insert_member(
    store: TeamStore,
    *,
    team_id: str,
    agent_id: str,
    display_name: str,
    role: str,
    color: str,
    now: int,
    thread_id: str | None = None,
) -> TeamMemberRow:
    member = TeamMemberRow(
        id=new_team_member_id(),
        team_id=team_id,
        agent_id=agent_id,
        display_name=display_name,
        color=color or "",
        thread_id=thread_id or new_thread_id(),
        role=role or "",
        backend_type="in_process",
        status="idle",
        joined_at=now,
    )
    store.create_member(member)
    return member


async def list_teams(session_id: str) -> dict[str, Any]:
    sess, store = _require_session(session_id)
    del sess
    teams = store.list_teams_for_session(session_id)
    items: list[dict[str, Any]] = []
    for team in teams:
        members = store.list_members(team.id)
        items.append(serialize_team(team, members))
    return {"teams": items}


async def create_team(session_id: str, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        raise TeamServiceError("name is required")

    sess, store = _require_session(session_id)
    existing = store.get_team_by_name(session_id, name)
    if existing is not None:
        raise TeamServiceError(f'team "{name}" already exists')

    runtime = get_team_runtime()
    if runtime is None:
        raise TeamServiceError("team tools unavailable: runtime not configured")
    lead_agent_id = runtime.lead_agent_id or sess.agent_id
    lead_display_name = str(args.get("lead_display_name") or "lead").strip() or "lead"

    member_specs = _normalize_member_specs(
        args.get("members"),
        lead_display_name=lead_display_name,
        lead_agent_id=lead_agent_id,
    )
    _validate_member_specs(store, sess.tenant_id, member_specs)

    now = _now_ms()
    team = TeamRow(
        id=new_team_id(),
        session_id=session_id,
        tenant_id=sess.tenant_id,
        name=name,
        description=str(args.get("description") or "").strip(),
        lead_thread_id=PRIMARY_THREAD_ID,
        lead_agent_id=lead_agent_id,
        status="active",
        created_at=now,
    )
    store.create_team(team)

    members: list[TeamMemberRow] = []
    lead_member = _insert_member(
        store,
        team_id=team.id,
        agent_id=lead_agent_id,
        display_name=lead_display_name,
        role="lead",
        color="",
        now=now,
        thread_id=PRIMARY_THREAD_ID,
    )
    members.append(lead_member)
    runtime.lead_member_id = lead_member.id
    runtime.active_team_id = team.id

    for spec in member_specs:
        member = _insert_member(
            store,
            team_id=team.id,
            agent_id=spec["agent_id"],
            display_name=spec["display_name"],
            role=spec["role"],
            color=spec["color"],
            now=now,
        )
        members.append(member)

    await append_session_events(
        [
            {
                "type": "session.team_created",
                "team_id": team.id,
                "name": name,
            }
        ]
    )
    return serialize_team(team, members)


async def spawn_teammate(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    if not team_id:
        raise TeamServiceError("team_id is required")

    sess, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    agent_id = str(args.get("agent_id") or "").strip()
    if not agent_id:
        raise TeamServiceError("agent_id is required")
    display_name = str(args.get("display_name") or "").strip()
    if not display_name:
        raise TeamServiceError("display_name is required")

    existing = store.get_member_by_display_name(team_id, display_name)
    if existing is not None:
        raise TeamServiceError(f'member "{display_name}" already exists')

    if not store.agent_exists(sess.tenant_id, agent_id):
        raise TeamServiceError(f'agent "{agent_id}" not found in tenant')

    now = _now_ms()
    member = _insert_member(
        store,
        team_id=team_id,
        agent_id=agent_id,
        display_name=display_name,
        role=str(args.get("role") or "").strip(),
        color=str(args.get("color") or "").strip(),
        now=now,
    )

    agent_name = store.get_agent_name(sess.tenant_id, agent_id) or agent_id
    await append_session_events(
        [
            {
                "type": "session.thread_created",
                "session_thread_id": member.thread_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "parent_thread_id": team.lead_thread_id,
                "team_id": team_id,
                "member_id": member.id,
                "display_name": display_name,
            }
        ]
    )

    start_loop = args.get("start_poll_loop", True)
    if start_loop is not False:
        await get_loop_manager().start(
            member,
            session_id=session_id,
        )

    return serialize_member(member)


def _is_broadcast_to(to: str) -> bool:
    return not to or to == "*"


async def _deliver_team_message(
    *,
    session_id: str,
    store: TeamStore,
    team_id: str,
    from_member: TeamMemberRow,
    recipient: TeamMemberRow,
    to_label: str,
    body: str,
    summary: str,
    msg_type: str,
    run_turn: bool,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Persist one message, build SSE payload, optional user.message enqueue."""
    now = _now_ms()
    msg_id = new_team_message_id()
    msg = AgentMessageRow(
        id=msg_id,
        team_id=team_id,
        from_member_id=from_member.id,
        to_member_id=recipient.id,
        message_type=msg_type,
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
        "to": to_label,
        "to_member_id": recipient.id,
        "message_type": msg_type,
        "summary": summary or None,
        "body": body,
    }
    target_thread_id = recipient.thread_id
    if target_thread_id:
        team_msg["session_thread_id"] = target_thread_id

    user_msg: dict[str, Any] | None = None
    if run_turn and target_thread_id and msg_type != "shutdown_request":
        if get_loop_manager().is_running(session_id, recipient.id):
            pass
        else:
            prompt = body
            if summary:
                prompt = f"{summary}\n\n{body}"
            user_msg = {
                "type": "user.message",
                "session_thread_id": target_thread_id,
                "content": [{"type": "text", "text": prompt}],
                "metadata": {
                    "harness": "team",
                    "team_id": team_id,
                    "message_id": msg_id,
                },
            }

    return msg_id, team_msg, user_msg


async def send_team_message(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    from_id = str(args.get("from_member_id") or "").strip()
    body = str(args.get("body") or "").strip()
    if not team_id or not from_id or not body:
        raise TeamServiceError(
            "team_id, from_member_id, and body are required"
        )

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    from_member = store.get_member_by_id(team_id, from_id)
    if from_member is None:
        raise TeamServiceError("from_member_id not found")

    msg_type = str(args.get("message_type") or "").strip() or "text"
    to = str(args.get("to") or "").strip()
    summary = str(args.get("summary") or "").strip()

    run_turn = args.get("run_target_turn", True)
    if run_turn is None:
        run_turn = True

    from pi_team.serialize import null_if_empty

    if msg_type == "shutdown_request":
        if _is_broadcast_to(to):
            raise TeamServiceError(
                "shutdown_request does not support broadcast"
            )
        recipient = store.get_member_by_display_name(team_id, to)
        if recipient is None:
            raise TeamServiceError(f'recipient "{to}" not found')
        try:
            return await request_teammate_shutdown(
                session_id,
                store=store,
                team_id=team_id,
                target_member_id=recipient.id,
                from_member_id=from_id,
                body=body,
                summary=summary,
            )
        except MemberShutdownError as exc:
            raise TeamServiceError(str(exc)) from exc

    if _is_broadcast_to(to):
        members = store.list_members(team_id)
        recipients = [
            m
            for m in members
            if m.id != from_id and member_can_receive_messages(m.status)
        ]
        team_events: list[dict[str, Any]] = []
        user_events: list[dict[str, Any]] = []
        message_ids: list[str] = []

        for recipient in recipients:
            msg_id, team_msg, user_msg = await _deliver_team_message(
                session_id=session_id,
                store=store,
                team_id=team_id,
                from_member=from_member,
                recipient=recipient,
                to_label="*",
                body=body,
                summary=summary,
                msg_type=msg_type,
                run_turn=run_turn,
            )
            message_ids.append(msg_id)
            team_events.append(team_msg)
            if user_msg is not None:
                user_events.append(user_msg)

        await append_session_events(team_events)
        if user_events:
            await enqueue_session_events(user_events, run_turn=True)

        return {
            "message_id": message_ids[0] if message_ids else None,
            "message_ids": message_ids,
            "team_id": team_id,
            "broadcast": True,
            "recipient_count": len(recipients),
        }

    recipient = store.get_member_by_display_name(team_id, to)
    if recipient is None:
        raise TeamServiceError(f'recipient "{to}" not found')
    if not member_can_receive_messages(recipient.status):
        raise TeamServiceError(
            f'recipient "{to}" is not accepting messages'
        )

    msg_id, team_msg, user_msg = await _deliver_team_message(
        session_id=session_id,
        store=store,
        team_id=team_id,
        from_member=from_member,
        recipient=recipient,
        to_label=to,
        body=body,
        summary=summary,
        msg_type=msg_type,
        run_turn=run_turn,
    )
    await append_session_events([team_msg])
    if user_msg is not None:
        await enqueue_session_events([user_msg], run_turn=True)

    return {
        "message_id": msg_id,
        "team_id": team_id,
        "to_member_id": null_if_empty(recipient.id),
        "session_thread_id": null_if_empty(recipient.thread_id),
    }


async def read_team_messages(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    recipient_id = str(args.get("recipient_member_id") or "").strip()
    if not team_id or not recipient_id:
        raise TeamServiceError(
            "team_id and recipient_member_id are required"
        )

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    msgs = store.list_unread_messages(team_id, recipient_id, 100)
    mark_read = bool(args.get("mark_read"))
    if mark_read and msgs:
        ids = args.get("message_ids")
        if not isinstance(ids, list) or not ids:
            ids = [m.id for m in msgs]
        else:
            ids = [str(i) for i in ids]
        await asyncio.to_thread(
            store.mark_messages_read,
            team_id,
            recipient_id,
            ids,
        )

    return {"messages": [serialize_message(m) for m in msgs]}


# ── team tasks ────────────────────────────────────────────────────────────────


def _serialize_task(task: TeamTaskRow) -> dict[str, Any]:
    return {
        "id": task.id,
        "team_id": task.team_id,
        "subject": task.subject,
        "description": task.description or None,
        "active_form": task.active_form or None,
        "owner_member_id": task.owner_member_id or None,
        "status": task.status,
        "blocks": task.blocks,
        "blocked_by": task.blocked_by,
        "metadata": task.metadata or None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


async def create_team_task(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    subject = str(args.get("subject") or "").strip()
    if not team_id or not subject:
        raise TeamServiceError("team_id and subject are required")

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    raw_metadata = args.get("metadata")
    metadata: dict[str, Any] = {}
    if isinstance(raw_metadata, dict):
        metadata = raw_metadata

    now = _now_ms()
    task = TeamTaskRow(
        id=new_task_id(),
        team_id=team_id,
        subject=subject,
        description=str(args.get("description") or ""),
        active_form=str(args.get("active_form") or ""),
        owner_member_id=str(args.get("owner_member_id") or ""),
        status="pending",
        blocks=[],
        blocked_by=[],
        metadata=metadata,
        created_at=now,
        updated_at=now,
    )
    store.create_task(task)
    return _serialize_task(task)


async def update_team_task(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    import json as _json

    team_id = str(args.get("team_id") or "").strip()
    task_id = str(args.get("task_id") or "").strip()
    if not team_id or not task_id:
        raise TeamServiceError("team_id and task_id are required")

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    task = store.get_task(team_id, task_id)
    if task is None:
        raise TeamServiceError("task not found")

    status = args.get("status")
    if status == "deleted":
        store.delete_task(team_id, task_id)
        return {"deleted": True, "task_id": task_id}

    db_updates: dict[str, Any] = {}
    updated_fields: list[str] = []

    if "subject" in args and args["subject"] != task.subject:
        db_updates["subject"] = str(args["subject"])
        updated_fields.append("subject")
    if "description" in args and args["description"] != task.description:
        db_updates["description"] = str(args["description"] or "")
        updated_fields.append("description")
    if "active_form" in args and args["active_form"] != task.active_form:
        db_updates["active_form"] = str(args["active_form"] or "")
        updated_fields.append("active_form")
    if "owner_member_id" in args and args["owner_member_id"] != task.owner_member_id:
        db_updates["owner_member_id"] = str(args["owner_member_id"] or "") or None
        updated_fields.append("owner_member_id")
    if status and status != task.status:
        db_updates["status"] = status
        updated_fields.append("status")

    # addBlocks: add IDs this task blocks
    add_blocks = args.get("add_blocks") or []
    if isinstance(add_blocks, list) and add_blocks:
        new_blocks = list({*task.blocks, *[str(x) for x in add_blocks]})
        db_updates["blocks_json"] = _json.dumps(new_blocks)
        updated_fields.append("blocks")

    # addBlockedBy: add IDs that block this task
    add_blocked_by = args.get("add_blocked_by") or []
    if isinstance(add_blocked_by, list) and add_blocked_by:
        new_blocked_by = list({*task.blocked_by, *[str(x) for x in add_blocked_by]})
        db_updates["blocked_by_json"] = _json.dumps(new_blocked_by)
        updated_fields.append("blocked_by")

    if "metadata" in args and isinstance(args["metadata"], dict):
        merged = {**task.metadata}
        for k, v in args["metadata"].items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        db_updates["metadata_json"] = _json.dumps(merged)
        updated_fields.append("metadata")

    if db_updates:
        store.update_task(team_id, task_id, db_updates)

    updated = store.get_task(team_id, task_id)
    return {
        "success": True,
        "task_id": task_id,
        "updated_fields": updated_fields,
        "task": _serialize_task(updated) if updated else None,
    }


async def list_team_tasks(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    if not team_id:
        raise TeamServiceError("team_id is required")

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    all_tasks = store.list_tasks(team_id)
    completed_ids = {t.id for t in all_tasks if t.status == "completed"}
    tasks = [
        {
            "id": t.id,
            "subject": t.subject,
            "status": t.status,
            "owner_member_id": t.owner_member_id or None,
            "blocked_by": [x for x in t.blocked_by if x not in completed_ids],
        }
        for t in all_tasks
    ]
    return {"tasks": tasks}


async def get_team_task(
    session_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    team_id = str(args.get("team_id") or "").strip()
    task_id = str(args.get("task_id") or "").strip()
    if not team_id or not task_id:
        raise TeamServiceError("team_id and task_id are required")

    _, store = _require_session(session_id)
    team = store.get_team_by_id(session_id, team_id)
    if team is None:
        raise TeamNotFoundError("not found")

    task = store.get_task(team_id, task_id)
    return {"task": _serialize_task(task) if task else None}


def session_id_from_runtime() -> str:
    runtime = get_team_runtime()
    if runtime is None or not runtime.session_id:
        raise TeamServiceError("team tools unavailable: session_id missing")
    return runtime.session_id
