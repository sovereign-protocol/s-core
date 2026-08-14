"""Per-node adoption metadata: what Core does with an incoming change.

An application records, per node, how changes to that node are to be handled.
Core reads the record and executes it, and never interprets what the node
means. See DESIGN_ADOPTION_METADATA.md.

Entries are local: not part of the node, not hashed, not published, never
adopted from a peer. A peer's opinion about how their own change should be
treated is not an input to how the recipient treats it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


# What to do with a change: adopt it, hold it for a decision, or do not offer
# it at all. `never` also keeps the node out of the divergence list - a node
# nobody may adopt has no business in a list of things to decide about.
ADOPT_AUTO = "auto"
ADOPT_HOLD = "hold"
ADOPT_NEVER = "never"
ADOPT_VALUES = (ADOPT_AUTO, ADOPT_HOLD, ADOPT_NEVER)

# Whose revision is acceptable at all. `same-origin` means "only revisions
# carrying the origin that already authored this node", which Core answers from
# revision_origin without any application semantics. A concrete identity uuid
# covers delegated authority - a trustee, say. Core must never learn
# set-valued authority ("any current member"): the application resolves that to
# concrete uuids and writes them.
AUTHOR_ANY = "any"
AUTHOR_SAME_ORIGIN = "same-origin"

# What an application answers when Core asks about a node it is holding.
# `hold` records that nothing has decided yet; these are the three ways that
# ends. `defer` leaves the decision to the user, which is what `hold` means
# when the application has no rule of its own - and it is the answer Core
# assumes when no resolver is registered.
RESOLVE_ADOPT = "adopt"
RESOLVE_REFUSE = "refuse"
RESOLVE_DEFER = "defer"
RESOLVE_VALUES = (RESOLVE_ADOPT, RESOLVE_REFUSE, RESOLVE_DEFER)


@dataclass(frozen=True)
class AdoptionEntry:
    """One node's handling. `None` means "inherit"."""

    adopt: str | None = None
    additions: str | None = None
    author: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("adopt", "additions"):
            value = getattr(self, field_name)
            if value is not None and value not in ADOPT_VALUES:
                raise ValueError(
                    f"{field_name} must be one of {ADOPT_VALUES}, not {value!r}"
                )
        if self.author is not None and (
            not isinstance(self.author, str) or not self.author.strip()
        ):
            raise ValueError("author must be a non-empty string")

    def inherit(self, base: "AdoptionEntry") -> "AdoptionEntry":
        """Fill this entry's unset fields from `base`."""
        return AdoptionEntry(
            adopt=self.adopt if self.adopt is not None else base.adopt,
            additions=(
                self.additions if self.additions is not None else base.additions
            ),
            author=self.author if self.author is not None else base.author,
        )

    def with_author(self, author: str) -> "AdoptionEntry":
        return replace(self, author=author)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in (
                ("adopt", self.adopt),
                ("additions", self.additions),
                ("author", self.author),
            )
            if value is not None
        }

    @classmethod
    def from_dict(cls, value: Any) -> "AdoptionEntry | None":
        """Build an entry from stored data, or None if it is unusable.

        Restoring never raises: a stored table that cannot be read is dropped
        so the conservative root default applies, rather than refusing to open
        the session.
        """
        if not isinstance(value, dict):
            return None
        try:
            entry = cls(
                adopt=value.get("adopt"),
                additions=value.get("additions"),
                author=value.get("author"),
            )
        except (TypeError, ValueError):
            return None
        return entry if entry.to_dict() else None


# The answer when nothing has been declared anywhere. Conservative by
# construction: a missing entry can never widen what is accepted.
ROOT_DEFAULT = AdoptionEntry(
    adopt=ADOPT_HOLD, additions=ADOPT_HOLD, author=AUTHOR_ANY,
)
