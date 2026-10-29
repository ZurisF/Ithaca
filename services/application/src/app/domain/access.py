"""Identity value used by application services."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Identity:
    id: UUID
    role: str
    display_name: str | None
