"""Who is acting on a request: the demo operator, a signed-in user, or a guest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Actor:
    kind: Literal["operator", "user", "guest"]
    subject: str
    name: str

    @property
    def can_write(self) -> bool:
        return self.kind != "guest"


OPERATOR = Actor("operator", "demo-operator", "Demo operator")


def profile_of(actor: Actor) -> str | None:
    """Whose preferences apply: a signed-in user's own, or the shared profile (None)."""
    return actor.subject if actor.kind == "user" else None


def actor_of(request: Any) -> Actor:
    """The actor the security middleware attached to the request; the demo operator by default."""
    state = getattr(request, "state", None)
    actor = getattr(state, "actor", None)
    return actor if isinstance(actor, Actor) else OPERATOR
