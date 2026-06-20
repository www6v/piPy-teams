"""Public async API for team tools (wraps pi_team.service)."""

from __future__ import annotations

from typing import Any

from pi_team.service import (
    SessionArchivedError,
    TeamNotFoundError,
    TeamServiceError,
    create_team as _create_team,
    create_team_task as _create_team_task,
    get_team_task as _get_team_task,
    list_teams as _list_teams,
    list_team_tasks as _list_team_tasks,
    read_team_messages as _read_team_messages,
    send_team_message as _send_team_message,
    session_id_from_runtime,
    spawn_teammate as _spawn_teammate,
    update_team_task as _update_team_task,
)


def _wrap_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, (TeamServiceError, TeamNotFoundError, SessionArchivedError)):
        return RuntimeError(str(exc))
    return RuntimeError(str(exc))


async def list_teams() -> dict[str, Any]:
    try:
        return await _list_teams(session_id_from_runtime())
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def create_team(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _create_team(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def spawn_teammate(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _spawn_teammate(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def send_team_message(args: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in args.items() if v is not None}
    if "run_target_turn" not in body:
        body["run_target_turn"] = True
    try:
        return await _send_team_message(session_id_from_runtime(), body)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def read_team_messages(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _read_team_messages(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def create_team_task(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _create_team_task(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def update_team_task(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _update_team_task(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def list_team_tasks(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _list_team_tasks(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc


async def get_team_task(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _get_team_task(session_id_from_runtime(), args)
    except Exception as exc:
        raise _wrap_error(exc) from exc
