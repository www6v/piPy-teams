"""Team coordination DTOs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TeamMemberRef(BaseModel):
    id: str
    display_name: str
    agent_id: str
    thread_id: str | None = None
    role: str | None = None


class TeamRef(BaseModel):
    id: str
    name: str
    lead_thread_id: str = "sthr_primary"
    members: list[TeamMemberRef] = Field(default_factory=list)
