from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


class LanguageModel(Protocol):
    async def complete(self, messages: Sequence[Message]) -> str:
        """Generate a reply; translate provider failures into application errors."""
        ...
