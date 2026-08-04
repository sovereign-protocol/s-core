# Sovereign Protocol serialization and hashing specification

Status: normative for protocol schema version `3` during the `0.x` series.
Breaking changes are permitted before `1.0`; incompatible channel input and
stored sessions are rejected rather than migrated.

## Version domains

The following versions are independent and must not share a wire field:

| Domain | Current field/value | Status |
|---|---|---|
| Python distribution | `0.1.8` | implemented |
| Protocol tree envelope | `protocol_schema_version: 3` | implemented |
| Session persistence envelope | `format: sovereign-session`, `version: 2` | implemented |
| Connect token | `token_version: 3` | implemented |
| Channel descriptor | `descriptor_version: 1` | implemented |
| Core public-profile schema | `profile_schema_version: 2` | implemented |
| Application data schema | owned and versioned by each application | implemented |
| Application facade/API | `facade_api_version`, owned by each facade | implemented |

## Canonical hash input

Hash input is UTF-8 JSON with object keys sorted and separators `,` and `:`;
no insignificant whitespace is present. The digest is SHA-256, represented by
its first 20 lowercase hexadecimal characters.

`content_hash` covers exactly:

```json
{"data":{},"deleted":false,"weights":{}}
```

The shown values are illustrative. A node's UUID, parent, timestamps,
children, revision base, revision origin, and revision sequence are excluded.

`state_hash` covers the node's `content_hash` and a list of every immediate
child's `[uuid, state_hash]` pair. The pairs are sorted lexicographically.
Consequently sibling order is not shared, while replacing a child with a
different UUID is detectable.

## Protocol node

A serialized node contains:

- `uuid`, `created_at`, `updated_at`;
- `data`, `weights`, `deleted`, `parent_uuid`, and recursive `children`;
- verified `content_hash` and `state_hash`;
- `base_hash`, `base_parent_uuid`, `revision_origin`, and `revision_seq`;
- `revision_parent_uuid`, `revision_key_id`, and `revision_signature`.

`base_hash` is the node's content hash before the current revision wave.
Successive edits by the same `revision_origin` compound against that base.
Adoption preserves the origin; an independent edit by another origin starts a
new wave. `revision_seq` is a non-negative logical sequence issued by the
origin and preserved by adopters and forwarders. It orders different revisions
from the same origin without comparing wall clocks. Revision metadata is
deliberately excluded from both hashes.

`revision_signature` is Ed25519 over canonical UTF-8 JSON containing signature
version 1 and the node's own UUID, timestamps, data, weights, deleted state,
authored parent, content hash, base fields, revision origin, and revision
sequence. `revision_parent_uuid` preserves that authored parent when a shared
topic or paired profile is mounted beneath a different local container.
Children and `state_hash` are excluded because each node revision is signed
independently. Forwarding and adoption preserve the signature unchanged.

The retired field `revision_origin_identity` is invalid.

## Protocol tree envelope

Every subtree crossing a channel uses:

```json
{
  "protocol_schema_version": 3,
  "subtree": {"...": "Protocol node"},
  "parent_uuid": null
}
```

Missing or unknown protocol versions are rejected. Hash damage inside a known
schema may be repaired on an explicitly repair-capable ingestion path; a schema
version mismatch must never be treated as hash damage.

The executable golden example is
[`tests/fixtures/protocol_tree_v3.json`](tests/fixtures/protocol_tree_v3.json).

## Other envelopes

A saved session contains `format`, `version`, `protocol_schema_version`,
`protocol_root`, and Session-owned metadata. A connect token contains
`token_version`, identity, topic UUIDs, and channel descriptors. Every channel
descriptor contains its own `descriptor_version` and channel-specific fields.

These outer formats may evolve independently from the protocol tree schema.
Older formats are incompatible and rejected.

The Core public profile is also independent structured data. Version 2 contains
`identity_key`, `display_name`, optional avatar data (`picture` and
`attachments`), structural `type`/`name` fields, and `signing_key_events`. It
does not contain email or other contact information.

`signing_key_events` is an ordered append-only chain. The first `activate`
event is self-signed. Later activations are signed by an active key. A `revoke`
event must be signed by another active key; self-revocation is rejected. Key
rotation activates a new key before optionally revoking the old one. A device
with no other active key cannot recover from compromise without replacing the
identity.

Each sibling device has its own private key. Pairing authorizes a new public
key in the identity profile and carries the corresponding private-key bundle
inside the bearer pairing token. The private key is persisted only in the
local session envelope, never in protocol content or relay publication. The
session file and pairing token are therefore sensitive and rely on local file
permissions and confidential token delivery; encrypted at-rest key storage is
not part of schema 3.

Verification returns `valid` when the signature matches an active key bound to
the claimed identity, `unknown` when the identity or key binding is unavailable,
and `invalid` for unsigned, malformed, forged, or revoked-key revisions.
Verification does not grant application authority.
