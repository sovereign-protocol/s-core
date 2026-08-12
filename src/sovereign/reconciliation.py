"""Application-declared, Core-executed perspective reconciliation policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LastWriteWinsPolicy:
    """Resolve a restricted node change using an application timestamp.

    ``data_fields`` and ``include_parent`` define the semantic fields covered
    by this rule. Every other own field must agree before the rule applies.
    The timestamp itself is metadata rather than a semantic difference.
    """

    node_type: str
    timestamp_field: str
    data_fields: tuple[str, ...] = ()
    include_parent: bool = False
    fallback_to_updated_at: bool = True
    settle_timestamp_only: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.node_type, str) or not self.node_type:
            raise ValueError("node_type must be a non-empty string")
        if not isinstance(self.timestamp_field, str) or not self.timestamp_field:
            raise ValueError("timestamp_field must be a non-empty string")
        if any(not isinstance(field, str) or not field for field in self.data_fields):
            raise ValueError("data_fields must contain non-empty strings")
        if self.timestamp_field in self.data_fields:
            raise ValueError("timestamp_field must not also be a data field")
        if len(set(self.data_fields)) != len(self.data_fields):
            raise ValueError("data_fields must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        """Return the inspectable application policy declaration."""

        return {
            "strategy": "last_write_wins",
            "node_type": self.node_type,
            "timestamp_field": self.timestamp_field,
            "data_fields": list(self.data_fields),
            "include_parent": self.include_parent,
            "fallback_to_updated_at": self.fallback_to_updated_at,
            "settle_timestamp_only": self.settle_timestamp_only,
        }
