"""A poll cycle must not pay twice for the same answer.

Sync correctness is covered elsewhere. What is guarded here is cost: how many
relay operations one cycle issues, and whether each of them asks something the
client does not already know. That distinction only becomes visible when it is
counted, because every redundant read still returns the right answer - the
session that motivated this file ran 423 cycles with no error of any kind while
spending 56% of its wall clock inside SFTP, roughly half of it re-reading
directories and re-downloading its own state.

Operations are counted at the RelayStorage boundary, not at the transport, so a
budget here means the same thing on a local folder, over SFTP, or over anything
added later. One logical operation is several SFTP round trips (a read is three,
a write four or five), which is why a small number in this file is a large
number of milliseconds on a real link.

Tests marked expectedFailure encode a step of DESIGN_RELAY_EFFICIENCY.md that
has not landed. unittest reports an unexpected success as a failure, so each one
announces itself the moment its fix arrives and the marker must be removed then.
"""

import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path

from sovereign.protocol import ProtocolNode
from sovereign.relay_logic import RelayLogic, RelayManager
from sovereign.relay_storage import SftpRelayStorage
from sovereign.session import Session
from sovereign.topic_registry import ApplicationRegistration


# Every method of the RelayStorage contract that costs a visit to the relay.
# Listed rather than inferred, so a method added to the contract has to be
# classified deliberately instead of silently escaping the budget.
RELAY_OPERATIONS = frozenset({
    "write_snapshot", "write_head",
    "read_head", "read_head_with_mtime", "read_snapshot",
    "list_peers", "list_peers_with_mtimes", "list_topics",
    "delete_publication", "delete_topic",
    "write_presence", "read_presence_with_mtime", "timing_probe",
    "verify_access", "write_blob", "read_blob", "has_blob", "list_blob_ids",
    "write_blob_lease", "delete_blob_lease", "list_blob_leases",
})

# An idle cycle over an unchanged relay, per peer, as measured today:
#   1  write_presence          the heartbeat, unconditional by design
#   1  read_presence_with_mtime the peer's heartbeat, cached across topics
# and per topic:
#   1  list_peers_with_mtimes  once per cycle, reused by publication, and its
#                              mtimes say which slots are worth reading at all
# No head is read on an idle cycle - not a peer's, not our own. What is left
# is the listing that discovers peers and notices departures, which cannot be
# inferred from anything already in hand.
IDLE_FIXED_OPERATIONS = 2
IDLE_OPERATIONS_PER_TOPIC = 1


class _CountingStorage:
    """Delegates to a real backend and records what was asked of it."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = Counter()
        self.listed_topics: list[str] = []
        self.written_snapshots: list[str] = []
        self.mtime_resolution_seconds = inner.mtime_resolution_seconds

    def __getattr__(self, name):
        attribute = getattr(self._inner, name)
        if name not in RELAY_OPERATIONS:
            return attribute

        def recorded(*args, **kwargs):
            self.calls[name] += 1
            # Both listing methods, so a caller switching between them cannot
            # make the duplicate-listing test pass by measuring nothing.
            if name in ("list_peers", "list_peers_with_mtimes"):
                self.listed_topics.append(args[0])
            if name == "write_snapshot":
                self.written_snapshots.append(args[2])
            return attribute(*args, **kwargs)

        return recorded

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    def reset(self) -> None:
        self.calls.clear()
        self.listed_topics.clear()
        self.written_snapshots.clear()


def register_notes_app(session: Session, topics: list | None = None) -> list:
    """A topic type without an application - same shape as the relay tests."""
    topics = [] if topics is None else topics
    session.register_application(ApplicationRegistration(
        application_id="notes",
        root_types=frozenset({"notes"}),
        list_topics=lambda: list(topics),
        accept_invitation=session.accept_topic_invitation,
        assignment_scoped=True,
        mount_invitation=True,
    ))
    return topics


class RelayEfficiencyCase(unittest.TestCase):
    def setUp(self) -> None:
        self.relay_root, self.state_dir = self.new_relay_location()

    def new_relay_location(self) -> tuple[str, str]:
        """An empty relay and a private place for its bookkeeping.

        Bookkeeping goes in the temp directory deliberately: the default state
        path is derived from the working directory (relay_logic.py:130), so a
        test that does not pin it leaves a file in the repository - which is
        how several hundred of them accumulated.
        """
        relay_root = tempfile.TemporaryDirectory()
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(relay_root.cleanup)
        self.addCleanup(state_dir.cleanup)
        return relay_root.name, state_dir.name

    def connect(self, session: Session, identity: str,
                location: tuple[str, str] | None = None) -> RelayLogic:
        relay_root, state_dir = location or (self.relay_root, self.state_dir)
        relay = RelayLogic(session, {
            "relay_root": relay_root,
            "relay_identity": identity,
            "relay_state_file": str(Path(state_dir) / f"{identity}.json"),
        })
        relay.storage = _CountingStorage(relay.storage)
        return relay

    def publisher(
        self, topic_count: int, location: tuple[str, str] | None = None,
    ) -> tuple[Session, RelayLogic, list[ProtocolNode]]:
        session = Session("addr-a")
        topics = register_notes_app(session)
        made = [
            session.create_child(
                session.root_uuid(), {"type": "notes", "name": f"topic-{index}"}, {},
            ).value
            for index in range(topic_count)
        ]
        topics.extend(made)
        relay = self.connect(session, "A", location)
        relay.set_scoped_topics({node.uuid for node in made})
        relay.publish_due_topics()
        return session, relay, made

    def subscriber(
        self, topic_uuids, location: tuple[str, str] | None = None,
    ) -> tuple[Session, RelayLogic]:
        """A peer that has taken the topics and publishes its own copy back."""
        session = Session("addr-b")
        topics = register_notes_app(session)
        relay = self.connect(session, "B", location)
        relay.set_scoped_topics(set(topic_uuids))
        relay.mark_topics_desired(sorted(topic_uuids))
        relay.poll_and_apply()
        topics.extend(
            session.protocol.index.get(uuid) for uuid in sorted(topic_uuids)
        )
        relay.publish_due_topics()
        return session, relay

    def settle(self, *relays: RelayLogic, cycles: int = 4) -> None:
        """Run both sides until convergence, then start counting from zero."""
        for _ in range(cycles):
            for relay in relays:
                relay.poll_once()
        for relay in relays:
            relay.storage.reset()


class TransportReportingSurvivesAStorageSwapTests(RelayEfficiencyCase):
    """Step 1. A swapped storage that reports nothing hides its own faults.

    relay.sftp_reconnect travels through the same callback as the timing
    events and is always on, so a client whose storage was replaced stops
    reporting dropped connections entirely - silently, and for the rest of the
    process's life. Observed live: one of two clients went dark at 22:08:17
    while continuing to poll normally for another 203 cycles.
    """

    DESCRIPTOR = {
        "type": "sftp", "host": "relay.example", "port": 22,
        "username": "user", "root": "/srv/relay",
    }

    def sftp_config(self, identity: str) -> dict:
        return {
            "relay_backend": "sftp",
            "relay_sftp_host": "relay.example",
            "relay_sftp_username": "user",
            "relay_sftp_root": "/srv/relay",
            "relay_identity": identity,
            "relay_state_file": str(Path(self.state_dir) / f"{identity}.json"),
        }

    def test_a_connection_built_at_boot_reports_transport_events(self):
        relay = RelayLogic(Session("addr-a"), self.sftp_config("A"))
        self.assertIsNotNone(relay.storage.on_event)

    def test_re_ensuring_a_connection_keeps_transport_reporting(self):
        # ensure_connection's existing-connection branch assigns a freshly
        # built storage over the wired one. Every accepted token, edited
        # target and startup registry bootstrap takes this path.
        manager = RelayManager(Session("addr-a"), self.sftp_config("A"))
        connection = manager.ensure_connection(self.DESCRIPTOR)
        self.assertIsNotNone(connection.storage.on_event)

    def test_adopting_a_descriptor_wires_transport_reporting(self):
        # A client that rode in on a token builds its backend here and
        # nowhere else, so this is its only chance to be wired at all.
        relay = RelayLogic(Session("addr-b"), {
            "relay_identity": "B",
            "relay_state_file": str(Path(self.state_dir) / "B.json"),
        })
        self.assertIsNone(relay.storage)
        self.assertTrue(relay.adopt_storage_from_descriptor(self.DESCRIPTOR))
        self.assertIsNotNone(relay.storage.on_event)


class IdlePollCycleCostTests(RelayEfficiencyCase):
    """What one cycle costs when there is nothing to say and nothing to hear.

    This is the number that decides how many topics a client can carry: at a
    22ms round trip and three to four round trips per operation, a 3s poll
    interval affords roughly forty operations before the cycle stops fitting
    inside it.
    """

    def test_an_idle_cycle_costs_a_fixed_amount_plus_a_charge_per_topic(self):
        session, relay_a, made = self.publisher(3)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b)

        relay_a.poll_once()

        self.assertEqual(
            relay_a.storage.total,
            IDLE_FIXED_OPERATIONS + IDLE_OPERATIONS_PER_TOPIC * 3,
        )
        self.assertEqual(dict(relay_a.storage.calls), {
            "write_presence": 1,
            "read_presence_with_mtime": 1,
            "list_peers_with_mtimes": 3,
        })

    def test_an_idle_cycle_moves_no_content(self):
        session, relay_a, made = self.publisher(2)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b)

        relay_a.poll_once()

        self.assertEqual(relay_a.storage.calls["write_snapshot"], 0)
        self.assertEqual(relay_a.storage.calls["read_snapshot"], 0)

    def test_cost_grows_linearly_with_topic_count(self):
        # A budget that is merely "small today" is not a budget. What has to
        # hold is the shape: an index or a manifest changes the slope, a
        # careless nested read changes the exponent.
        for topic_count in (1, 2, 4):
            with self.subTest(topics=topic_count):
                location = self.new_relay_location()
                _, relay_a, made = self.publisher(topic_count, location)
                _, relay_b = self.subscriber(
                    {node.uuid for node in made}, location,
                )
                self.settle(relay_a, relay_b)

                relay_a.poll_once()

                self.assertEqual(
                    relay_a.storage.total,
                    IDLE_FIXED_OPERATIONS
                    + IDLE_OPERATIONS_PER_TOPIC * topic_count,
                )

    def test_a_topic_is_listed_once_per_cycle(self):
        # poll_and_apply lists topics/<t>/peers and publication reuses that
        # listing rather than re-reading a directory nothing has written to in
        # the meantime. Three topics, three listings saved, ~280ms - a fifth
        # of the cycle.
        _, relay_a, made = self.publisher(3)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b)

        relay_a.poll_once()

        listed = Counter(relay_a.storage.listed_topics)
        self.assertEqual(
            [uuid for uuid, count in listed.items() if count > 1], [],
        )


class _RecordingSftp:
    """Enough of an SFTP client to count what one read costs in round trips."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.calls: list[str] = []

    def open(self, path, _mode="rb"):
        self.calls.append(f"open {path}")
        data = self.files.get(path)
        if data is None:
            raise FileNotFoundError(path)
        return _RecordingFile(self, data)

    def stat(self, path):
        self.calls.append(f"stat {path}")
        return types.SimpleNamespace(st_mtime=1000.0, st_mode=0)


class _RecordingFile:
    def __init__(self, sftp: _RecordingSftp, data: bytes):
        self._sftp = sftp
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return self._data

    def stat(self):
        # fstat on the open handle - no path lookup, and paramiko pipelines
        # it on the connection the read already opened.
        self._sftp.calls.append("fstat")
        return types.SimpleNamespace(st_mtime=1000.0)


class OneVisitPerFileTests(unittest.TestCase):
    """Content and timestamp come from the same visit, not two.

    Over SFTP the difference is a whole round trip, paid on every head and
    every heartbeat - per peer, per topic, per cycle. It is also the only way
    the pair is coherent: a separate stat can describe a version the read did
    not see, and this mtime decides both how stale a peer looks and whether
    its head is read again at all.
    """

    def storage(self, files: dict[str, bytes]) -> tuple[SftpRelayStorage, _RecordingSftp]:
        storage = SftpRelayStorage("host", "user", "/relay")
        sftp = _RecordingSftp(files)
        storage._sftp = sftp
        return storage, sftp

    def test_reading_a_head_costs_one_open_and_no_stat(self):
        path = "/relay/topics/t1/peers/B/head.json"
        storage, sftp = self.storage({path: b'{"hash": "abc"}'})

        head, mtime = storage.read_head_with_mtime("t1", "B")

        self.assertEqual(head, {"hash": "abc"})
        self.assertEqual(mtime, 1000.0)
        self.assertEqual(sftp.calls, [f"open {path}", "fstat"])

    def test_reading_a_heartbeat_costs_one_open_and_no_stat(self):
        path = "/relay/identities/B/presence.json"
        storage, sftp = self.storage({path: b'{"identity": "B"}'})

        presence, mtime = storage.read_presence_with_mtime("B")

        self.assertEqual(presence, {"identity": "B"})
        self.assertEqual(mtime, 1000.0)
        self.assertEqual(sftp.calls, [f"open {path}", "fstat"])

    def test_a_missing_file_answers_without_a_second_lookup(self):
        storage, sftp = self.storage({})

        self.assertEqual(storage.read_head_with_mtime("t1", "B"), (None, None))
        self.assertEqual(
            sftp.calls, ["open /relay/topics/t1/peers/B/head.json"],
        )


class SilenceIsOnlyTrustedWhenItIsProofTests(RelayEfficiencyCase):
    """Not reading a head is a claim that nothing was written to it.

    The saving is real - one round trip per peer per topic per cycle, the
    largest recurring charge an idle client pays - but it is bought with an
    inference, and the inference has a timing hole. SFTP reports mtimes in
    whole seconds, so a write landing in the same second as the one just
    observed leaves the slot looking untouched. Believing that would drop the
    peer's change and keep dropping it until something else wrote into the
    slot: a silent, open-ended sync failure, which is worse than any number
    of wasted reads.
    """

    def test_a_head_written_between_cycles_is_still_read(self):
        session_a, relay_a, made = self.publisher(1)
        topic = made[0]
        session_b, relay_b = self.subscriber({topic.uuid})
        self.settle(relay_a, relay_b)

        relay_a.poll_once()
        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 0)

        session_b.modify(
            topic.uuid,
            {**session_b.protocol.index[topic.uuid].data, "name": "moved on"},
            {},
        )
        relay_b.publish_due_topics()

        relay_a.storage.reset()
        applied = relay_a.poll_once()

        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 1)
        self.assertIn((topic.uuid, "B"), applied.applied)

    def test_a_slot_is_not_trusted_until_its_timestamp_has_aged(self):
        # The guard, driven directly: a backend whose clock cannot resolve
        # anything finer than an hour can never prove a slot was untouched,
        # so every head is read, every cycle. Correctness before cost.
        _, relay_a, made = self.publisher(2)
        _, relay_b = self.subscriber({node.uuid for node in made})
        relay_a.storage.mtime_resolution_seconds = 3600.0
        self.settle(relay_a, relay_b)

        relay_a.poll_once()

        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 2)

    def test_a_topic_waiting_to_be_grafted_keeps_being_offered(self):
        # An unchanged slot means unchanged content, which is not the same as
        # nothing left to do. A topic that arrived before this client could
        # mount it is parked as a pending invitation and has to be offered
        # again every poll; settling the slot would stop it being looked at
        # and the graft would never be retried. Caught by s-team, where a
        # subteam admitted later never appeared.
        _, relay_a, made = self.publisher(1)
        topic = made[0]

        # No application registered, so the arriving subtree has no handler
        # and stays a cache rather than being grafted.
        session_b = Session("addr-b")
        relay_b = self.connect(session_b, "B")
        relay_b.set_scoped_topics({topic.uuid})
        relay_b.mark_topics_desired([topic.uuid])
        for _ in range(4):
            relay_b.poll_once()
        self.assertIsNone(session_b.protocol.index.get(topic.uuid))

        relay_b.storage.reset()
        relay_b.poll_once()

        self.assertEqual(relay_b.storage.calls["read_head_with_mtime"], 1)

    def test_a_sibling_writing_into_our_own_slot_is_still_seen(self):
        # The own-slot read is the sibling rule's, and skipping it is the
        # last and least comfortable of these savings: being wrong means
        # publishing over work somebody is about to be asked about. A sibling
        # writes into the slot the same way anyone else writes theirs, so the
        # listing shows it - but that has to be true, not assumed.
        session_a, relay_a, made = self.publisher(1)
        topic = made[0]
        self.settle(relay_a)
        relay_a.poll_once()
        self.assertEqual(relay_a.storage.calls["read_head"], 0)

        # A second client of the same person, publishing under the shared
        # identity from work built on what this one already published.
        sibling_session = Session("addr-a2")
        sibling_topics = register_notes_app(sibling_session)
        # Same publication identity, its own bookkeeping - a sibling is
        # another machine, not another object sharing this one's state file.
        sibling = RelayLogic(sibling_session, {
            "relay_root": self.relay_root,
            "relay_identity": "A",
            "relay_state_file": str(Path(self.state_dir) / "A-laptop.json"),
        })
        sibling.storage = _CountingStorage(sibling.storage)
        sibling.set_scoped_topics({topic.uuid})
        sibling.poll_and_apply()
        sibling_topics.append(sibling_session.protocol.index[topic.uuid])
        sibling_session.modify(
            topic.uuid,
            {**sibling_session.protocol.index[topic.uuid].data, "name": "by the laptop"},
            {},
        )
        sibling.publish_due_topics()

        relay_a.storage.reset()
        result = relay_a.poll_once()

        # The slot was read again, and the sibling rule ran on what it found
        # and reported work. What that rule then decides - take, or raise an
        # alarm for the person - is test_sibling_clients.py's subject; what
        # matters here is that skipping the read never hides the question.
        self.assertEqual(relay_a.storage.calls["read_head"], 1)
        self.assertIn((topic.uuid, "A"), result.applied)

    def test_a_returning_peer_is_read_again(self):
        # A withdrawn publication clears `applied`, and the settled mtime has
        # to go with it - otherwise the slot reappears with the mtime it left
        # with, looks untouched, and the peer is never read again.
        session_a, relay_a, made = self.publisher(1)
        topic = made[0]
        _, relay_b = self.subscriber({topic.uuid})
        self.settle(relay_a, relay_b)
        relay_a.poll_once()
        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 0)

        relay_b.withdraw_topic_publication(topic.uuid)
        relay_a.poll_once()
        relay_b.publish_due_topics()

        relay_a.storage.reset()
        applied = relay_a.poll_once()

        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 1)
        self.assertIn((topic.uuid, "B"), applied.applied)


class NoRedundantContentTransferTests(RelayEfficiencyCase):
    """Bytes that cross the relay must be bytes the receiver does not hold."""

    def test_a_peer_head_matching_our_own_state_costs_no_snapshot_read(self):
        # When a peer adopts our change, its content hash becomes our hash and
        # it republishes. A state hash is content identity, so there is nothing
        # left to fetch. Eleven of twelve snapshot reads in the traced session
        # were this.
        session_a, relay_a, made = self.publisher(1)
        topic = made[0]
        session_b, relay_b = self.subscriber({topic.uuid})

        self.assertEqual(
            session_a.node_state_hash(topic.uuid),
            session_b.node_state_hash(topic.uuid),
            "the scenario is only meaningful if both sides agree",
        )
        # First contact still fetches: our own copy cannot say where a peer we
        # have never seen keeps this topic.
        relay_a.poll_and_apply()

        # The shape that produced the waste: A edits, B takes the edit, and B
        # republishes content whose hash is now A's own.
        session_a.modify(topic.uuid, {"type": "notes", "name": "renamed"}, {})
        relay_a.publish_due_topics()
        relay_b.poll_and_apply()
        session_b.accept_peer_node("relay:A", topic.uuid, topic_uuid=topic.uuid)
        relay_b.publish_due_topics()
        self.assertEqual(
            session_b.node_state_hash(topic.uuid),
            session_a.node_state_hash(topic.uuid),
        )

        relay_a.storage.reset()
        applied = relay_a.poll_and_apply()

        self.assertEqual(relay_a.storage.calls["read_snapshot"], 0)
        self.assertIn((topic.uuid, "B"), applied)
        self.assertEqual(
            session_a.get_cached_peer_subtree("relay:B", topic.uuid).state_hash,
            session_a.node_state_hash(topic.uuid),
            "the peer cache must hold what a fetch would have produced",
        )

    def test_an_acknowledgement_does_not_rewrite_the_subtree(self):
        # An observation-only publication carries no content change, so it
        # writes a head and leaves the subtree alone. Seven of sixteen board
        # publications in the traced session were this, each rewriting the
        # whole tree to move a sequence number - and making a file named
        # after its own hash mutable, which is what let a reader catch one
        # mid-change.
        _, relay_a, made = self.publisher(1)
        _, relay_b = self.subscriber({node.uuid for node in made})

        for _ in range(4):
            relay_a.poll_once()
            relay_b.poll_once()

        rewritten = [
            state_hash
            for state_hash, count in Counter(relay_a.storage.written_snapshots).items()
            if count > 1
        ]
        self.assertEqual(rewritten, [])

    def test_one_change_costs_one_subtree_write_and_one_acknowledgement(self):
        # The acknowledgement protocol's own termination: ack_requested is
        # false for observation-only heads, so the pair goes quiet rather than
        # trading acks of acks. What each side pays to get there is the point
        # of step 6 - the author writes its subtree once, and the peer, whose
        # own content did not change, answers with a head and nothing else.
        session_a, relay_a, made = self.publisher(1)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b, cycles=6)

        session_a.modify(made[0].uuid, {"type": "notes", "name": "renamed"}, {})
        relay_a.publish_once()
        for _ in range(6):
            relay_b.poll_once()
            relay_a.poll_once()

        self.assertEqual(relay_a.storage.calls["write_snapshot"], 1)
        self.assertEqual(relay_b.storage.calls["write_snapshot"], 0)
        self.assertEqual(relay_b.storage.calls["write_head"], 1)

        relay_a.storage.reset()
        relay_b.storage.reset()
        for _ in range(3):
            relay_a.poll_once()
            relay_b.poll_once()
        for relay in (relay_a, relay_b):
            self.assertEqual(relay.storage.calls["write_snapshot"], 0)
            self.assertEqual(relay.storage.calls["write_head"], 0)

    def test_a_peer_arriving_after_an_acknowledgement_still_gets_the_topic(self):
        # The head a bare acknowledgement leaves behind still has to name a
        # snapshot that is there. Nothing checks that on the write side, so a
        # third client reading the topic for the first time is the test.
        session_a, relay_a, made = self.publisher(1)
        topic = made[0]
        _, relay_b = self.subscriber({topic.uuid})
        # Counted rather than settled: the acknowledgement this is about
        # happens during convergence, and settle() clears the record of it.
        for _ in range(6):
            relay_a.poll_once()
            relay_b.poll_once()
        self.assertGreater(relay_a.storage.calls["write_head"], 0)
        # One subtree write, from publishing the topic in the first place -
        # the acknowledgements above it added none.
        self.assertEqual(relay_a.storage.calls["write_snapshot"], 1)

        session_c = Session("addr-c")
        register_notes_app(session_c)
        relay_c = self.connect(session_c, "C")
        relay_c.set_scoped_topics({topic.uuid})
        relay_c.mark_topics_desired([topic.uuid])

        self.assertIn((topic.uuid, "A"), relay_c.poll_and_apply())
        self.assertEqual(
            session_c.node_state_hash(topic.uuid),
            session_a.node_state_hash(topic.uuid),
        )


class LocalWorkLeavesWithoutPayingForInboundSyncTests(RelayEfficiencyCase):
    """An edit must not wait behind a full inbound poll to get out.

    publish_once exists for this (relay_logic.py:890): a cycle publishes last,
    so routing an edit through one put a floor of about 1.5s on every change,
    most of it inbound work the edit does not depend on. In the traced session
    each card move left the machine in 0.69-1.00s.
    """

    def test_publishing_reads_only_our_own_slot(self):
        session, relay_a, made = self.publisher(1)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b)

        session.modify(made[0].uuid, {"type": "notes", "name": "renamed"}, {})
        relay_a.publish_once()

        self.assertEqual(dict(relay_a.storage.calls), {
            # The sibling rule, which is the whole reason this path may skip
            # the inbound poll at all - it must not be optimised away.
            "read_head": 1,
            "write_snapshot": 1,
        })
        self.assertEqual(relay_a.storage.calls["read_head_with_mtime"], 0)
        self.assertEqual(relay_a.storage.calls["read_snapshot"], 0)

    def test_an_unchanged_topic_publishes_nothing(self):
        session, relay_a, made = self.publisher(2)
        _, relay_b = self.subscriber({node.uuid for node in made})
        self.settle(relay_a, relay_b)

        relay_a.publish_once()

        self.assertEqual(relay_a.storage.calls["write_snapshot"], 0)


if __name__ == "__main__":
    unittest.main()
