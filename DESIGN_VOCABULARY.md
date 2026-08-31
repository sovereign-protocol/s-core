# One word per concept

Core owns the shell (U1), so Core owns the words in it. This document fixes
the user-facing vocabulary. It is written before the header redesign because
the header is where most of the drift is visible, and renaming things twice
is worse than renaming them once.

The scope is **what a person reads**. Internal names — event types, stages,
route parameters, CSS classes, Python identifiers — are deliberately left
alone. They are precise, they are tested, and nobody reads them.

## What was wrong

Four findings, from an inventory of the strings actually shipped.

**"Topic" means three things.** It is Core's protocol noun for a shared root
(`topic_uuid`, `?topic=`); it is the agenda field's placeholder, "Add a
discussion topic" (`shared.js`), which is an unrelated meaning two panes
away; and it is not a word anybody applies to their own team or board. The
cure was already half-built and unused in the shell: `topic_noun` in
`topic_registry.py`, declared as "Organization", "Flow" and "Initiative".

**"Agreement" already belongs to S-Team.** A Team Agreement is a document
that members accept, with its own states — "No Agreement", "Agreement
incomplete", "Identity holders disagree". S-Team also uses *align* for a
third thing: "Align your Agreement copy with Identity". Reporting sync state
as "Aligned" or "in agreement" collides head-on with a real domain object.

**One concept carried four surface words.** The header button said "Aligned",
the pane heading said "In transition", the styles said `disagreement` and
`has-divergence`, the Cockpit stat said "divergence", the fallback sentence
said "Difference". Underneath sit five stages and five event types, which is
fine — the fault is that five internal names leaked out as five different
public ones.

**People had three names.** "Involved Individuals" as a pane heading, "peer"
in visible sentences ("Peer changes are adopted automatically"), and
"participant" in the pairing note. The same auto-adopt setting was labelled
"Adopt automatically"/"Hold for me to decide" by Core and "Always"/"Never" by
S-Initiative — and the descriptions exist in three copies, in `shared.js`,
`initiative.html` and `boardofboards.html`, which is the divergence U1 was
written to prevent, arriving in language.

## The rule

**Say whose move it is.** That is the only property of a change a person can
act on, and every state word should answer it. "Diverged", "in transition"
and "not aligned" describe the data; "needs your review" and "waiting on
others" describe the reader's situation, which is what a status line is for.

Two consequences follow. Settled says nothing at all — silence is the state.
And a change that is merely travelling is not counted, because a number you
cannot act on inflates the one you can.

## The lexicon

| Concept | Internal (unchanged) | Say | Never say |
| --- | --- | --- | --- |
| A shared root | `topic`, `topic_uuid`, `?topic=` | the kind, from `topic_noun`: Initiative, Organization, Flow | "topic" |
| A node inside one | `node`, `node_uuid` | the object: card, role, section, step — otherwise "item" | "node" |
| The queue as a whole | `transition_by_node` | **changes** | "transitions", "alignment", "disagreements" |
| Settled | `in_agreement`, `settled` | in the header, nothing at all; where a state must be named, **no open changes** | "aligned", "agreed", "in agreement" |
| Your decision pending | `awaiting_me` | **needs your review** | "awaiting me", "to review" |
| Two-sided | `conflict` | **conflict** | "divergence", "disagreement", "to resolve" |
| Your change travelling | `in_flight`, `awaiting_peer` | **waiting on others** | "in transition", "pending", "diverged" |
| Taking a change | `adopt`, `rollback` | **adopt** / **take back** | "apply", "accept", "merge" |
| The standing rule | `auto_adopt` | **adopt incoming changes automatically** / **review each change first** | bare "always" / "never", "auto-adopt" |
| Another person | `peer` | **people**, or their name | "peer", "individual", "participant" |
| A publishing self | `identity`, paired client | **identity** | "participant", "account" |
| Agenda entry | `agenda_item` | **agenda item** | "discussion topic", "point" |
| You hold it | `held` | **in my Cockpit** | "held" |
| You do not hold it | `unheld` | **available to add** | "not held", "unheld" |
| Stop holding it | drop | **remove from Cockpit** | "stop holding" |
| The right-hand pane | — | **People and channels** | "Sharing & Sync" |

### There is no collective noun

Where the shell must name an Initiative, an Organization and a Flow at once,
it **composes from `topic_noun` or avoids the noun**. It does not introduce a
generic word — not "topic", not "work", not "space".

- A menu entry that applies to any kind reads `Manage links…`; these are
  local navigation shortcuts and not domain relationships.
- Prose names the kind: "This flow is held by two people", never "this topic
  is held by two people".

The cost is that generic strings must be composed rather than written, and
`topic_noun` becomes load-bearing for the shell rather than only for the
new-topic dialog. That is the intended direction: it is the only place that
already knows what one of these is called to a person.

### The three nouns stay as registered

Initiative, **Organization**, **Flow** — not "Team" and not "Process".

"Organization" was chosen over "Team" deliberately and the reason sits beside
the registration in `s-team/logic.py`: a team made from outside the
application is a root team, and that is what a root team is called; nested
ones are made inside it. "Process" is the internal type name (`PROCESS_TYPE`)
and the application is called S-Flow, so "Flow" is the word a person meets.
Changing either means overturning a recorded decision, not picking a synonym.

### Adopt is the verb, in both places

The standing rule and the individual act use the same verb. The per-change
buttons already read "Adopt card move from B" and "Take back my card move",
and adoption is the protocol's own concept — see `DESIGN_ADOPTION_METADATA.md`
and `DESIGN_ADOPTION_METADATA.md`. A setting that says "apply" above
buttons that say "adopt" is the split this document exists to close.

"Adopt" also carries what "apply" does not: a change from someone else becomes
yours because you took it, not because the machine merged it. That is the
whole subject.

## Where the states are shown

The header carries **one** number. The three states are labelled in the pane,
where there is room for words.

| Surface | Shows |
| --- | --- |
| `[Changes · N]` in the header | N = conflicts **plus** what needs your review. Nothing else. |
| Changes waiting on others | no count; the existing `stage-pulse` on the control |
| Pane rows | "Needs your review", "Conflict", "Waiting on others" |
| Pane, nothing outstanding | "No open changes" |

A count that includes changes you cannot act on is a count you learn to
ignore, which is why "waiting on others" is a state but not a number. It is
still visible: the control pulses while anything is in flight.

## Navigation wording

| Where | Says |
| --- | --- |
| The navigation row | local destinations' own names, and nothing else |
| Navigation menu, heading | Navigation |
| Navigation menu, below the divider | Manage links… |
| The Cockpit, on the row | no words — its mark, labelled "Open S-Cockpit" |
| Link dialog | Navigation links |

**The row carries no kind labels.** A related topic is named and nothing
more. The kind was a chip's small-capitals prefix and it bought nothing — the
destination says what it is on arrival — while dropping it is what lets the
whole row be one class of thing and therefore uniformly clickable.

**The kind is not drawn beside the topic's own name either.** `topic_noun`
names the field and supplies the rename placeholder; it is not rendered as a
word next to the application mark that already says it. Measured in use:
"Initiative · in Alpha" under a board whose mark is a board states the same
fact twice, once as a picture and once as a word. Amended 2026-08-18; the
line beneath the name is now destinations, not description.

**The Cockpit is optional.** The row adds it only when an application
registers `role === "aggregator"`, so an installation may have none. Every
string above that names the Cockpit needs a fallback that does not — "Add"
and "Remove", with the mark and its rule absent — rather than naming a
surface that is not installed.

## What this retires

User-facing strings only. Every line below is a rename, not a behaviour
change.

| Where | Now | Becomes |
| --- | --- | --- |
| `shared.js` `refreshDisagreements` | "Everything on this topic is Aligned" | (no text; the control is quiet) |
| `shared.js` status bands | "2 to resolve", "1 to review", "3 in transition" | one count on `[Changes · N]`; the rest move into the pane |
| `shared.js` collab pane | `<h3>In transition</h3>` | `<h3>Changes</h3>` |
| `shared.js` empty list | "Nothing in transition." | "No open changes." |
| `shared.js` agenda field | "Add a discussion topic" | "Add an agenda item" |
| `s-team/logic.py` `NODE_LABELS` | `"agenda_item": "Discussion topic"` | `"agenda_item": "Agenda item"` |
| `shared.js` connections pane | "Sharing & Sync" | "People and channels" |
| `shared.js` peers section | "Involved Individuals" | "People" |
| `shared.js` auto-adopt labels | "Adopt automatically" / "Hold for me to decide" | "Adopt incoming changes automatically" / "Review each change first" |
| `shared.js` auto-adopt descriptions | "Peer changes are adopted automatically." | "Changes from other people are adopted automatically." |
| `initiative.html`, `boardofboards.html` | own copies of the same four descriptions | deleted; Core's are the only ones, extended per mode |
| `initiative.html` auto-adopt labels | "Always" / "Never" | Core's two, with the card-scoped modes phrased to match |
| the auto-adopt indicator in the header | S-Initiative's 2×2 square | removed; the setting is a labelled row in the pane |

Four notes.

**The setting is never an icon.** Adoption policy is too unfamiliar to survive
as a glyph — S-Initiative's 2×2 square cannot be read without its tooltip. It
is a labelled control inside the collaboration pane and nowhere else. The
cost, accepted deliberately: the standing rule is no longer visible at rest.

**A control's number counts the thing the control is named for.** `[Agenda ·
3]` and `[Changes · 2]` are two controls with two counts. A setting and a
status count never share one control.

**The three copies of the auto-adopt descriptions collapse to one.** Core
already accepts `autoAdoptLabels` and `autoAdoptDescriptions` overrides; an
application supplies only the modes Core does not know about and inherits the
wording of the two it does.

**CSS class names and element ids are not renamed.** `shell-disagreement-row`,
`has-divergence` and `shellNotAlignedTitle` keep their names. They are read by
tests and by application stylesheets, and renaming them buys nothing a person
can see. Where a heading's text changes, the id above it does not.

## Reaction controls

The inline vocabulary is deliberately shorter than the explanatory sentence:
**Adopt**, **Take back**, and **React**. The icon supports the word but never
replaces it. `React` is used only when a menu mixes adoption and taking back;
a menu containing one kind names that kind. Review surfaces retain the full
sentence in the tooltip and accessible name, such as “Adopt card move from
Ana”, while keeping the visible button short.

**Proposal** remains domain language. It may name a proposal in a decision
process, but it must not label an arbitrary incoming revision.
