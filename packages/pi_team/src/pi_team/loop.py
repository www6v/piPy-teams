"""Long-running in-process teammate mailbox poll loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from pi_team.platform import enqueue_session_events
from pi_team.runtime import get_team_runtime
from pi_team.store import AgentMessageRow, TeamMemberRow, TeamStore, resolve_database_path

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SEC = float(
    os.environ.get("TEAMMATE_POLL_INTERVAL_SEC", "2.0")
)
DEFAULT_IDLE_TIMEOUT_SEC = float(
    os.environ.get("TEAMMATE_IDLE_TIMEOUT_SEC", "600")
)


@dataclass(frozen=True)
class TeammateLoopKey:
    session_id: str
    member_id: str

    def as_str(self) -> str:
        return f"{self.session_id}:{self.member_id}"


@dataclass
class TeammateLoopConfig:
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC
    idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT_SEC
    enqueue_turn: bool = True


def format_mailbox_prompt(
    messages: list[AgentMessageRow],
    *,
    member_names: dict[str, str],
) -> str:
    """Build a single user prompt from unread mailbox rows."""
    if not messages:
        return ""
    blocks: list[str] = ["[Team mailbox]"]
    for msg in messages:
        sender = member_names.get(msg.from_member_id, msg.from_member_id)
        header = f"From {sender}"
        if msg.message_type and msg.message_type != "text":
            header = f"{header} ({msg.message_type})"
        body = msg.body.strip()
        if msg.summary and msg.summary.strip():
            body = f"{msg.summary.strip()}\n\n{body}"
        blocks.append(f"{header}:\n{body}")
    return "\n\n".join(blocks)


def _split_shutdown_messages(
    messages: list[AgentMessageRow],
) -> tuple[list[AgentMessageRow], list[AgentMessageRow]]:
    shutdown: list[AgentMessageRow] = []
    work: list[AgentMessageRow] = []
    for msg in messages:
        if msg.message_type == "shutdown_request":
            shutdown.append(msg)
        elif msg.message_type == "shutdown_response":
            continue
        else:
            work.append(msg)
    return shutdown, work


class TeammateLoopManager:
    """Tracks background poll tasks per session member."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._configs: dict[str, TeammateLoopConfig] = {}

    def is_running(self, session_id: str, member_id: str) -> bool:
        key = TeammateLoopKey(session_id, member_id).as_str()
        task = self._tasks.get(key)
        return task is not None and not task.done()

    def running_member_ids(self, session_id: str) -> set[str]:
        prefix = f"{session_id}:"
        out: set[str] = set()
        for key, task in self._tasks.items():
            if not key.startswith(prefix):
                continue
            if task.done():
                continue
            out.add(key[len(prefix):])
        return out

    async def start(
        self,
        member: TeamMemberRow,
        *,
        session_id: str,
        config: TeammateLoopConfig | None = None,
    ) -> bool:
        if member.backend_type != "in_process":
            return False
        key = TeammateLoopKey(session_id, member.id).as_str()
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            return False

        cfg = config or TeammateLoopConfig()
        self._configs[key] = cfg
        task = asyncio.create_task(
            _run_teammate_loop(session_id, member, cfg),
            name=f"teammate-loop-{member.display_name}",
        )
        self._tasks[key] = task
        task.add_done_callback(lambda _t: self._tasks.pop(key, None))
        return True

    async def stop(self, session_id: str, member_id: str) -> bool:
        key = TeammateLoopKey(session_id, member_id).as_str()
        task = self._tasks.pop(key, None)
        self._configs.pop(key, None)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def stop_all_for_session(self, session_id: str) -> int:
        prefix = f"{session_id}:"
        keys = [k for k in self._tasks if k.startswith(prefix)]
        stopped = 0
        for key in keys:
            member_id = key[len(prefix):]
            if await self.stop(session_id, member_id):
                stopped += 1
        return stopped


def get_loop_manager() -> TeammateLoopManager:
    runtime = get_team_runtime()
    if runtime is None:
        raise RuntimeError("team runtime not configured")
    return runtime.loop_manager


async def _run_teammate_loop(
    session_id: str,
    member: TeamMemberRow,
    config: TeammateLoopConfig,
) -> None:
    runtime = get_team_runtime()
    if runtime is None:
        return
    db_path = resolve_database_path(runtime.database_path)
    store = TeamStore(db_path)
    store.update_member_status(member.id, "listening")

    last_activity = time.monotonic()
    try:
        while True:
            await asyncio.sleep(config.poll_interval_sec)
            if not _session_active(store, session_id):
                logger.info(
                    "teammate loop stopping: session %s unavailable",
                    session_id,
                )
                break

            refreshed = store.get_member_by_id(member.team_id, member.id)
            if refreshed is None or refreshed.status == "shutdown":
                break

            messages = await asyncio.to_thread(
                store.list_unread_messages,
                member.team_id,
                member.id,
                100,
            )
            if not messages:
                if (
                    config.idle_timeout_sec > 0
                    and time.monotonic() - last_activity
                    >= config.idle_timeout_sec
                ):
                    logger.info(
                        "teammate loop idle timeout member=%s",
                        member.display_name,
                    )
                    break
                continue

            last_activity = time.monotonic()
            shutdown_msgs, work_msgs = _split_shutdown_messages(messages)
            if refreshed.status == "shutting_down":
                work_msgs = []
            all_ids = [m.id for m in messages]

            if shutdown_msgs:
                from pi_team.shutdown import complete_teammate_shutdown

                await complete_teammate_shutdown(
                    store,
                    session_id=session_id,
                    member=member,
                    requests=shutdown_msgs,
                    mark_read_ids=all_ids,
                )
                break

            if work_msgs and config.enqueue_turn:
                await _enqueue_mailbox_turn(
                    store,
                    session_id=session_id,
                    member=member,
                    messages=work_msgs,
                )

            await asyncio.to_thread(
                store.mark_messages_read,
                member.team_id,
                member.id,
                all_ids,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "teammate loop failed session=%s member=%s",
            session_id,
            member.display_name,
        )
    finally:
        current = store.get_member_by_id(member.team_id, member.id)
        if current is not None and current.status == "listening":
            store.update_member_status(member.id, "idle")


def _session_active(store: TeamStore, session_id: str) -> bool:
    sess = store.get_session(session_id)
    return sess is not None and sess.status != "archived"


async def _enqueue_mailbox_turn(
    store: TeamStore,
    *,
    session_id: str,
    member: TeamMemberRow,
    messages: list[AgentMessageRow],
) -> None:
    names = _member_name_map(store, member.team_id)
    prompt = format_mailbox_prompt(messages, member_names=names)
    if not prompt:
        return
    store.update_member_status(member.id, "active")
    user_msg: dict[str, Any] = {
        "type": "user.message",
        "session_thread_id": member.thread_id,
        "content": [{"type": "text", "text": prompt}],
        "metadata": {
            "harness": "team",
            "team_id": member.team_id,
            "member_id": member.id,
            "source": "teammate_poll_loop",
            "message_ids": [m.id for m in messages],
        },
    }
    await enqueue_session_events([user_msg], run_turn=True)
    store.update_member_status(member.id, "listening")


def _member_name_map(
    store: TeamStore,
    team_id: str,
) -> dict[str, str]:
    members = store.list_members(team_id)
    return {m.id: m.display_name for m in members}
