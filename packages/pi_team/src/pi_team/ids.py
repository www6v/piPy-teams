"""ID generation aligned with internal/store/ids.go."""

from __future__ import annotations

import secrets
import string

_ID_ALPHABET = string.digits + string.ascii_lowercase
_ID_LENGTH = 16

PRIMARY_THREAD_ID = "sthr_primary"


def _random_string(length: int = _ID_LENGTH) -> str:
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def new_team_id() -> str:
    return f"team-{_random_string()}"


def new_team_member_id() -> str:
    return f"tmem-{_random_string()}"


def new_team_message_id() -> str:
    return f"tmsg-{_random_string()}"


def new_thread_id() -> str:
    return f"sthr_{_random_string()}"
