"""Version rules shared by a future desktop bridge and its sidecar."""

from __future__ import annotations

from dataclasses import dataclass


class ProtocolVersionError(ValueError):
    """Raised when two surface participants cannot safely communicate."""


@dataclass(frozen=True, order=True)
class ProtocolVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ProtocolVersionError("protocol versions cannot be negative")

    def wire(self) -> str:
        return f"{self.major}.{self.minor}"

    def accepts(self, other: "ProtocolVersion") -> bool:
        """Accept additive minor changes, but never a changed major meaning."""
        return self.major == other.major and other.minor <= self.minor

    @classmethod
    def parse(cls, value: str) -> "ProtocolVersion":
        parts = value.split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ProtocolVersionError(f"invalid protocol version: {value!r}")
        return cls(int(parts[0]), int(parts[1]))


CURRENT_PROTOCOL = ProtocolVersion(2, 0)
