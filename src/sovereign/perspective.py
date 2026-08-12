"""Read-only projections across locally owned and observed perspectives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .protocol import ProtocolNode


@dataclass(frozen=True)
class PerspectiveObservation:
    """Runtime facts about when one topic perspective was observed."""

    address: str
    topic_uuid: str
    observed_monotonic: float
    observed_at: str
    source_age_seconds: float | None = None
    source_timestamp: float | None = None
    channel_kind: str | None = None


@dataclass(frozen=True)
class PerspectiveSource:
    """Verified owner and runtime provenance of a projected node."""

    identity_uuid: str
    identity_key: str
    addresses: tuple[str, ...]
    local: bool
    age_seconds: float | None
    observed_at: str | None
    source_timestamp: float | None
    channel_kind: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_uuid": self.identity_uuid,
            "identity_key": self.identity_key,
            "addresses": list(self.addresses),
            "local": self.local,
            "age_seconds": self.age_seconds,
            "observed_at": self.observed_at,
            "source_timestamp": self.source_timestamp,
            "channel_kind": self.channel_kind,
        }


@dataclass(frozen=True)
class ProjectedNode:
    """A detached protocol node together with its perspective provenance."""

    node: ProtocolNode
    perspective: PerspectiveSource
    conflict: bool = False

    @property
    def uuid(self) -> str:
        return self.node.uuid

    @property
    def data(self) -> dict:
        return self.node.data

    @property
    def weights(self) -> dict:
        return self.node.weights

    @property
    def created_at(self) -> str:
        return self.node.created_at

    @property
    def updated_at(self) -> str:
        return self.node.updated_at

    def to_dict(self) -> dict[str, Any]:
        payload = self.node.to_dict()
        payload["perspective"] = {
            **self.perspective.to_dict(),
            "conflict": self.conflict,
        }
        return payload


@dataclass(frozen=True)
class _RevisionCandidate:
    """One cached copy of a node and where it was observed."""

    node: ProtocolNode
    source: Any
    verified: bool


@dataclass(frozen=True)
class _RevisionResolution:
    """The selected representation and all sources carrying that revision."""

    node: ProtocolNode
    sources: tuple[Any, ...]
    conflict: bool


def _revision_timestamp(node: ProtocolNode) -> float:
    try:
        value = datetime.fromisoformat(str(node.updated_at).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _resolve_revision_candidates(
    candidates: list[_RevisionCandidate],
    *,
    allow_unverified_fallback: bool = False,
) -> _RevisionResolution | None:
    """Resolve duplicate cached revisions once for every Core consumer.

    Logical sequences are comparable only within one revision origin. Across
    origins, Core keeps the conflict visible and selects a stable display
    representation using signed timestamps and hashes. Sources are merged only
    when they carry the selected own revision; differing descendants do not
    split an otherwise identical node revision.
    """

    verified = [candidate for candidate in candidates if candidate.verified]
    eligible = verified or (candidates if allow_unverified_fallback else [])
    if not eligible:
        return None

    by_origin: dict[str, list[_RevisionCandidate]] = {}
    for candidate in eligible:
        by_origin.setdefault(candidate.node.revision_origin or "", []).append(candidate)

    newest: list[_RevisionCandidate] = []
    for origin_candidates in by_origin.values():
        highest_sequence = max(
            candidate.node.revision_seq for candidate in origin_candidates
        )
        newest.extend(
            candidate for candidate in origin_candidates
            if candidate.node.revision_seq == highest_sequence
        )

    selected = max(newest, key=lambda candidate: (
        _revision_timestamp(candidate.node),
        candidate.node.revision_origin or "",
        candidate.node.content_hash,
        candidate.node.state_hash,
        candidate.node.parent_uuid or "",
    ))
    node = selected.node
    matching_sources = tuple(
        candidate.source for candidate in eligible
        if (
            candidate.node.revision_origin == node.revision_origin
            and candidate.node.revision_seq == node.revision_seq
            and candidate.node.content_hash == node.content_hash
            and candidate.node.parent_uuid == node.parent_uuid
        )
    )
    conflict = len({
        (candidate.node.content_hash, candidate.node.parent_uuid)
        for candidate in newest
    }) > 1
    return _RevisionResolution(node, matching_sources, conflict)
