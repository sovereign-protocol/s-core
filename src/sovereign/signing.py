"""Ed25519 identity keys and canonical protocol-revision signatures."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

SIGNATURE_VERSION = 1
SIGNING_ALGORITHM = "ed25519"


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def key_id_for_public_key(public_key: str) -> str:
    digest = hashlib.sha256(_decode(public_key)).hexdigest()
    return f"ed25519:{digest}"


def generate_keypair() -> dict[str, str]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public = _encode(public_raw)
    return {
        "algorithm": SIGNING_ALGORITHM,
        "key_id": key_id_for_public_key(public),
        "private_key": _encode(private_raw),
        "public_key": public,
    }


def public_key_for_private_key(private_key: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.from_private_bytes(_decode(private_key))
    return _encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def sign_bytes(private_key: str, payload: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.from_private_bytes(_decode(private_key))
    return _encode(private.sign(payload))


def verify_bytes(public_key: str, payload: bytes, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(_decode(public_key)).verify(
            _decode(signature), payload,
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def key_event_payload(event: dict) -> dict:
    return {
        key: event[key]
        for key in ("event", "key_id", "algorithm", "public_key", "authorized_by")
        if key in event
    }


def activation_event(
    keypair: dict[str, str], authorizer: dict[str, str] | None = None,
) -> dict:
    signer = authorizer or keypair
    event = {
        "event": "activate",
        "key_id": keypair["key_id"],
        "algorithm": SIGNING_ALGORITHM,
        "public_key": keypair["public_key"],
        "authorized_by": signer["key_id"],
    }
    event["signature"] = sign_bytes(
        signer["private_key"], _canonical(key_event_payload(event)),
    )
    return event


def revocation_event(key_id: str, authorizer: dict[str, str]) -> dict:
    event = {
        "event": "revoke",
        "key_id": key_id,
        "authorized_by": authorizer["key_id"],
    }
    event["signature"] = sign_bytes(
        authorizer["private_key"], _canonical(key_event_payload(event)),
    )
    return event


def resolve_key_events(events: Any) -> tuple[dict[str, str], set[str], str | None]:
    """Return all known keys, active ids, and a validation error."""
    if not isinstance(events, list) or not events:
        return {}, set(), "signing_key_events must be a non-empty list"
    known: dict[str, str] = {}
    active: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            return known, active, f"signing key event {index} must be an object"
        kind = event.get("event")
        key_id = event.get("key_id")
        authorizer = event.get("authorized_by")
        signature = event.get("signature")
        if not all(isinstance(value, str) and value for value in (
            kind, key_id, authorizer, signature,
        )):
            return known, active, f"signing key event {index} is incomplete"
        if kind == "activate":
            public_key = event.get("public_key")
            if event.get("algorithm") != SIGNING_ALGORITHM or not isinstance(
                public_key, str,
            ):
                return known, active, f"signing key event {index} is unsupported"
            try:
                derived_id = key_id_for_public_key(public_key)
            except (ValueError, TypeError):
                return known, active, f"signing key event {index} has an invalid key"
            if derived_id != key_id or key_id in known:
                return known, active, f"signing key event {index} has an invalid key id"
            verification_key = public_key if index == 0 and authorizer == key_id else known.get(authorizer)
            if verification_key is None or (index > 0 and authorizer not in active):
                return known, active, f"signing key event {index} has no active authorizer"
            if not verify_bytes(
                verification_key, _canonical(key_event_payload(event)), signature,
            ):
                return known, active, f"signing key event {index} has an invalid signature"
            known[key_id] = public_key
            active.add(key_id)
        elif kind == "revoke":
            verification_key = known.get(authorizer)
            if key_id not in active or authorizer not in active:
                return known, active, f"signing key event {index} names an inactive key"
            if key_id == authorizer:
                return known, active, f"signing key event {index} cannot self-revoke"
            if verification_key is None or not verify_bytes(
                verification_key, _canonical(key_event_payload(event)), signature,
            ):
                return known, active, f"signing key event {index} has an invalid signature"
            active.remove(key_id)
        else:
            return known, active, f"signing key event {index} has an unknown type"
    return known, active, None


def revision_payload(node: Any) -> dict:
    return {
        "signature_version": SIGNATURE_VERSION,
        "uuid": node.uuid,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "content_hash": node.content_hash,
        "base_hash": node.base_hash,
        "base_parent_uuid": node.base_parent_uuid,
        "revision_origin": node.revision_origin,
        "revision_seq": node.revision_seq,
        "weights": node.weights,
        "data": node.data,
        "revision_parent_uuid": node.revision_parent_uuid,
        "deleted": node.deleted,
    }


def sign_revision(node: Any, keypair: dict[str, str]) -> None:
    node.revision_key_id = keypair["key_id"]
    node.revision_signature = sign_bytes(
        keypair["private_key"], _canonical(revision_payload(node)),
    )


def verify_revision(node: Any, public_key: str) -> bool:
    signature = getattr(node, "revision_signature", None)
    return isinstance(signature, str) and verify_bytes(
        public_key, _canonical(revision_payload(node)), signature,
    )
