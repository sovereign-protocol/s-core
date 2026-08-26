# Plan — one projection for open changes

Status: finalized design and implementation plan, 2026-08-20.

## Goal

Every normal Sovereign UI projects the same Core transition semantics in the
same way, while applications retain control of their domain layout and
authorization.

This began as a presentation refactor. Revision classification, adoption
policy, and application governance remain unchanged. The implementation also
corrects the Core reaction/rollback contract exposed by the shared controls:
locally authored changes say Take back and may restore the exact prior peer
revision even when that prior revision has another author.

## Architectural direction — headless Core, optional shell

Core's protocol machinery and its visual projection must be usable without
`SovereignShell`. Core continues to own the shell where an application uses
it, but the shell is one client of Core rather than a prerequisite for
collaboration.

The intended architecture has three layers:

1. **Headless Core** — identity, topics, persistence, transport, revision
   classification, adoption policy, and guarded commands.
2. **Binding client** — binds an ordinary DOM field or collection to a Core
   node and projects its confirmed/pending state.
3. **Optional UI** — inline marker/reaction controls, a Changes view, and
   connection/identity settings. An application may use any combination.

The first practical deployment remains the existing Python Core host. A small
browser client talks to that host; this plan does not require a JavaScript or
WASM port of the protocol engine.

An ordinary page should eventually be able to do the equivalent of:

```js
const core = await SovereignClient.connect({baseUrl, capability});
core.bindField(titleInput, {
  topicUuid,
  nodeUuid,
  field: "text",
  label: "Project title",
  adoption: "hold",
  commit: "blur",
});
```

The binding supplies stable protocol identity; a DOM position or generated
element id is not sufficient. Scalar fields commit on blur or an explicit
debounce, never once per keystroke. Lists require stable child UUIDs and an
explicit add/delete/move binding. This remains whole-version collaboration,
not character-level concurrent text editing.

Two command paths remain distinct:

- nodes created as generic bindings may use capability-scoped Core commands;
- application-owned nodes must continue through the owning application's
  command adapter and validation. A generic binding must never bypass domain
  invariants merely because it can name a field.

A host may preconfigure a relay or send connection management to a separate
Core page, but identity and sharing require informed consent. Browser access
to Core is origin-checked and capability-scoped by topic, node, and operation;
an arbitrary page never receives unrestricted Session access.

The current refactor must therefore keep `transitionMarker`,
`decorateTransition`, and `reactionControl` independent of panes, headers, and
`SovereignShell`. A generic binding proof follows the first-party migrations;
it does not expand the initial UI migration into a new protocol implementation.

## Decisions

### One visual channel per meaning

| Channel | Meaning |
| --- | --- |
| Pulsating dot | a change is still `in_flight` |
| Dashed outline | this representation, value, or position exists in only one perspective |
| Background and coloured left edge | adoption stage — whose move it is |
| Explanation | what changed, who authored it, and where it stands |
| Reaction control | the versions the user can choose |

Background colour is not an independent status language. A faint stage tint
may support amber and red on large surfaces, but selection, hover, and focus
must remain distinguishable from transition state.

### Stage projection

| Core stage | Marker / border | Motion | User meaning |
| --- | --- | --- | --- |
| `settled` | none | none | no open change |
| `in_flight` | grey | pulse | still travelling |
| `awaiting_peer` | grey | none | waiting on others |
| `awaiting_me` | amber | none | needs your review |
| `conflict` | red | none | conflict |

Colour is always accompanied by the leading edge, tooltip/focus text, or a
written status. The dot is reserved for `in_flight`; reduced-motion mode
removes the pulse without removing the grey mark.

### Presence, deletion, addition, and movement

Dashed does not mean only “added” or only “deleted”. It means that the drawn
representation exists in one perspective only. This covers:

- a newly created object held by one side;
- the visible remnant of a deletion;
- the alternative seat of a moved or reordered object;
- an alternative field value shown beside the locally held value.

The tooltip names the actual operation. Applications still decide where a
ghost or alternative value belongs because only they understand their layout.

### Reaction controls

Words remain because `Adopt` has no unambiguous conventional icon. Icons are
visual support, never the sole label.

| Choices | Inline control | Review-pane control |
| --- | --- | --- |
| one adopt | incoming-arrow + `Adopt` | icon + full existing action sentence |
| one rollback | undo-arrow + `Take back` | icon + full existing action sentence |
| several, all adopt | incoming-arrow + `Adopt` + chevron | same trigger; full menu items |
| several, all rollback | undo-arrow + `Take back` + chevron | same trigger; full menu items |
| both kinds | changes icon + `React` + chevron | same trigger; full menu items |

Every menu option carries the corresponding Adopt or Take-back icon. The React
trigger reuses Core's existing two-direction Changes glyph. All glyphs use the
U8 24×24, `currentColor`, unfilled stroke rules.

The inline control has short visible wording and the complete transition
sentence as tooltip and accessible description. There is no icon-only variant
in this refactor.

“Proposal” is reserved for a real application-domain proposal, especially an
S-Flow proposal. A generic peer revision is an open change and receives no
`Proposed` badge.

## Current inventory

| Surface | Current state | Required change |
| --- | --- | --- |
| Core Changes pane | Shared wording and reaction control; stage-coloured edge; full labels | Add stage dot and reaction icons; use review density |
| Core `reactionControl` | Direct full-text action for one choice; `React` menu for several | Add action glyphs, short/review densities, and action-aware menu trigger |
| S-Initiative | Shared reaction control; private event grouping; application-owned stage classes; mature card/column ghost placement | Use Core grouping/decoration, add markers where they add information, retain ghost algorithms, remove local stage CSS |
| S-Team | Dots plus backgrounds, blue dashed proposals and `Proposed` labels; shared reaction control; private grouping drops non-leading peer events | Use Core grouping/decoration, remove generic proposal badge/blue language, retain alternate-node/value placement |
| S-Flow | Private `transition_by_node`, `reactionButton`, `reactionChoices`, and stage CSS | Delete all four copies and use Core grouping/controls/decoration |
| S-Cockpit | Shared controls only for Initiative; hard-coded stage colours differ from Core | Adopt Core decoration and provide guarded reactions for Team and Flow through their facades |
| Protocol Explorer | Perspective stripe, dashed ghosts, `Accept` modal | Keep the diagnostic stripe; rename the act to Adopt and use the shared action icon where practical |
| Notes example | No normal transition UI | No migration unless it begins exposing open changes |

One current defect disappears with the migration: S-Flow creates classes such
as `stage-awaiting_me`, while its stylesheet targets `stage-awaiting-me`, so
those stage-specific rules do not match.

## Ownership boundary

### Core owns

1. Transition relation, stage, ranking, revision origin, and reaction choice.
2. Grouping identical target revisions across peers and retaining distinct
   target versions as distinct choices.
3. Transition sentences and short reaction verbs.
4. Adopt, Take-back, React, and chevron glyphs.
5. Reaction button/menu rendering, focus behavior, keyboard behavior, disabled
   state, and accessible naming.
6. In-flight markers, shared colour tokens, wash and leading-edge treatment,
   pulse,
   reduced-motion behavior, and the long-dashed perspective primitive.
7. The Changes pane's review presentation.
8. Pane-independent browser primitives and the capability contract for generic
   Core-owned bindings.

### Applications own

1. Which domain nodes are meaningful enough to display.
2. Domain change descriptions such as “Card moved to Done” or “Role renamed”.
3. Where an object, alternate value, or ghost belongs in the application UI.
4. Whether the current actor may react, including S-Team governance and other
   application interaction guards.
5. The guarded command callback and its HTTP/facade route.
6. Real domain proposals and their domain-specific presentation.

Core may expose capability-scoped generic commands only for generic Core-owned
binding nodes. It must not expose a route that bypasses the guards of an
application-owned node. Its browser component continues to receive an
`onReact(choice)` callback.

## Core implementation

### 1. Normalize the server-side projection

Add `Session.group_transition_events(events)` as the single implementation of
the currently duplicated `transition_by_node` functions.

It must:

- select the leading event with `Session.transition_rank`;
- attach `reaction_for_event` to every concrete event;
- attach whether the represented act was authored by this identity;
- keep an `events` list on every unsettled group;
- merge identical revision targets and collect `delivery_peer_addrs`;
- keep distinct peer revisions as distinct menu choices;
- preserve application-supplied `changes` descriptions untouched;
- return only JSON-safe detached mappings.

S-Initiative's current revision signature and origin-peer preference are the
reference behavior. S-Team currently discards non-leading events and therefore
cannot offer every multi-peer choice. S-Flow retains events but does not merge
identical revision targets delivered by several peers. The shared
implementation corrects both cases.

Applications continue to collect/filter events and attach descriptions before
passing them to Core for grouping.

### 2. Extend the shared glyph and menu APIs

Add private Core action glyphs and an `actionGlyph(kind)` helper for:

- `adopt`: arrow entering an open boundary;
- `take_back`: conventional counter-clockwise undo arrow;
- `react`: existing `ICON_CHANGES`;
- menu disclosure: existing `ICON_CHEVRON_DOWN`.

Extend `actionMenu` items with `iconKind`. The menu renderer, not the caller,
resolves the SVG. Existing label-only callers remain valid.

### 3. Extend `SovereignUI.reactionControl`

Add `density: "inline" | "review"`, defaulting to `inline`. Every first-party
caller explicitly selects its intended density so its context is clear.

The component derives its trigger from the complete choice set:

- one choice: direct action;
- several choices with one action kind: action-labelled menu;
- both action kinds: React menu.

Menu items always use full action sentences and action icons. The component
continues to disable itself while its callback is running.

Core's own Changes pane opts into `review`.

### 4. Add shared transition decoration

Add two composable primitives:

- `SovereignUI.transitionMarker(info, options)` creates the dot, tooltip,
  accessible label, optional stage filter, and optional activation callback;
- `SovereignUI.decorateTransition(element, info, options)` clears stale state,
  sets `data-transition-stage`, attaches the explanation, and applies the
  shared surface class.

Neither primitive may query or mutate `SovereignShell`, assume a pane exists,
or require shell markup. The shell, first-party applications, and the future
binding client all call the same functions.

Use data attributes rather than application-generated `stage-*` class names.
This removes underscore/hyphen drift and keeps stage-to-colour mapping in one
stylesheet.

Add shared CSS for:

- `.ui-transition-marker`;
- `.ui-transition-surface` by `data-transition-stage`;
- `.ui-perspective-ghost` / `.ui-perspective-alternative`;
- inline and review reaction densities;
- icon-bearing action-menu rows.

The dot's visible glyph may be small, but its focus/click target must meet the
shared control size. Mouse hover, keyboard focus, and accessible text expose
the same `transitionLabel` sentence.

### 5. Record the contract

Add the accepted grammar to `DESIGN_UI_CONSISTENCY.md` and update
`DESIGN_VOCABULARY.md` where it currently describes only full reaction labels.
Document the new shared JS primitives in `PUBLIC_API.md`.

## Application migration

### Phase A — S-Flow as the minimal reference

1. Replace Flow's private `transition_by_node` implementation with
   `Session.group_transition_events`.
2. Replace local `reactionButton` and `reactionChoices` with an explicit
   `density: "inline"` `SovereignUI.reactionControl`.
3. Replace `applyTransitionClass` and private stage CSS with Core decoration and
   markers on the process and assignment rows.
4. Retain the real workflow Proposal wording and styling.
5. Replace the adopt/rollback routes with one guarded `/api/flow/react`
   endpoint.
6. Expose one facade `react_to_node(...)` command that dispatches to the
   existing guarded accept/rollback methods.

### Phase B — S-Initiative

1. Migrate cards, columns, initiative root, needs, clauses, approach sections,
   and milestones to Core markers/decoration.
2. Replace Initiative's private `transition_by_node` implementation with
   `Session.group_transition_events`, retaining its liveness filtering around
   the normalized groups.
3. Pass `density: "inline"` at normal reaction sites; Core already owns the
   shared Changes pane's `review` density.
4. Preserve `movedByPeer`, `movedByMe`, `currentSeatOf`, and ghost placement;
   replace only their visual classes with Core's dashed primitive.
5. Keep one reaction entry point per node: normally on the solid card, on the
   ghost only when no solid representation exists.
6. Replace the two frontend mutation routes with `/api/initiative/react`.
7. Remove local `.diff`, stage-colour, `.adopt`, and reaction appearance rules
   after every Initiative surface uses Core.
8. Remove the browser copy of adoption-policy presentation logic once
   Initiative's server payload supplies the final reactable set, computed
   beside its adoption metadata/resolver; the guarded command remains the
   authority.

### Phase C — S-Team

1. Replace the hand-built `status-lamp` with the Core marker in `elementRow`
   and the team heading.
2. Use the shared background and leading edge for adoption stages, with every
   dot reserved for `in_flight`.
3. Replace `is-proposed`, `proposal-badge`, and blue proposal styling with the
   shared dashed alternative treatment and Core explanation.
4. Apply the same rule to peer-only memberships, roles, sections, clauses,
   accountabilities, domains, and alternate Agreement field values.
5. Keep the `proposed_nodes` / `proposed_changes` payloads initially because
   they locate remote alternatives in the document; rename them only in a
   separate payload cleanup if useful.
6. Replace Team's private `transition_by_node` implementation with
   `Session.group_transition_events` so multi-peer choices are not lost.
7. Pass `density: "inline"` at document reaction sites.
8. Add `react_to_node(...)` to the Team facade, preserving all existing
   governance and interaction guards.

### Phase D — S-Cockpit

1. Replace hard-coded card stage colours and transition classes with Core
   decoration/markers.
2. Keep inline reactions on visible Initiative cards, explicitly using
   `density: "inline"`.
3. Add one `/api/cockpit/react` route that dispatches through the selected
   application's `react_to_node(...)` facade command.
4. Enable review-pane reactions for Initiative, Team, and Flow when the
   matching application/facade is active; otherwise show the change and link to
   its application without a false action.
5. Aggregated tiles use the highest-ranked child stage for their marker and a
   count in the tooltip; they do not pretend that the tile itself is the
   changed node.
6. Cockpit has no grouping implementation of its own: verify that all source
   adapters consume Core-grouped facade results without regrouping or dropping
   their `events` lists.

### Phase E — diagnostic UI and cleanup

1. Change Protocol Explorer's visible `Accept` wording to `Adopt` and add the
   action icon, but retain its multi-peer stripe because it exposes more than a
   normal application projection.
2. Remove obsolete application CSS, private stage maps, reaction-choice
   builders, private event-grouping implementations, and old routes.
3. Verify every first-party `reactionControl` call supplies `inline` or
   `review`.

### Phase F — generic binding proof

Build one deliberately ordinary integration page, outside `SovereignShell`,
containing a textarea bound to a generic Core-owned scalar node.

1. Add an origin-checked, capability-scoped browser client for the existing
   Python Core host.
2. Implement `bindField` with stable topic/node/field identity, confirmed and
   optimistic state, blur/debounced commit, and clean unbinding.
3. Reuse Core's marker, tooltip, dashed alternative, and reaction control
   without importing or constructing the shell.
4. Demonstrate automatic adoption and held Adopt/Take-back/React flows between
   two clients.
5. Provide optional standalone Changes and connection/settings components;
   the field works without either component.
6. Require explicit relay consent or an already approved host configuration.
7. Prove that the capability cannot read or mutate another topic/node and that
   generic commands cannot modify application-owned nodes.

This phase proves the boundary. Production list bindings, offline service
workers, package distribution, and a JavaScript/WASM protocol port remain
separate work.

## Verification

### Core unit contracts

- stage ranking and grouped leading event;
- one adopt choice;
- one rollback choice;
- identical targets held by several peers merge into one choice;
- identical targets still merge when observation gives deliveries different
  causal classifications;
- distinct targets remain separate;
- same-action multiple choices produce an action menu;
- mixed adopt/rollback choices produce a React menu;
- menu items carry the correct icon kind and full label;
- settled and in-flight events do not expose reaction controls;
- accessible name and tooltip use the same transition sentence;
- omitted reaction density resolves to `inline`;
- Core's Changes pane explicitly uses and verifies `review` density.

Prefer testing a pure `reactionPresentation(choices, density)` helper rather
than asserting source strings. Keep DOM construction thin over that result.

### Application contracts

- no application defines stage colours or maps stages to CSS classes;
- no application implements its own reaction-choice builder;
- no application logic implements transition grouping; temporary facade
  wrappers may only delegate to `Session.group_transition_events`;
- every first-party reaction-control caller selects a density explicitly;
- every rendered unsettled domain element has a Core marker unless it is a
  deliberately suppressed aggregate/container duplicate;
- application guards still reject unauthorized adoption and rollback;
- S-Flow's domain Proposal remains distinct from open changes;
- S-Team no longer labels generic incoming revisions `Proposed`;
- Initiative move/deletion ghosts keep their current placement and one-action
  rule;
- Cockpit never offers a reaction when the owning facade is absent.

### Generic binding contracts

- transition primitives operate with no shell DOM present;
- a field commits at the configured boundary rather than per keystroke;
- confirmed state and pending local intention remain distinct;
- the same inline and review reactions work on a generic scalar node;
- a capability is limited to its declared topic, node, fields, and operations;
- relay connection requires consent or an already approved configuration;
- a generic binding cannot mutate an application-owned node.

### Scenario matrix

Run two-client scenarios for modification, creation, deletion, move, and
reorder in both directions, through:

- `in_flight`, `awaiting_peer`, `awaiting_me`, and `conflict`;
- auto-adopt, held-for-review, and never-offered policy;
- one peer, identical revisions from several peers, and competing revisions;
- solid representation present, ghost only, and solid plus alternate ghost.

The user performs visual acceptance for dark and light themes, narrow
cards/rows, keyboard-only use, touch-size controls, long person/object names,
and reduced-motion mode. Implementation verification here is automated and
structural; it does not claim visual approval.

## Release order

1. Core: final grouping/UI APIs, documentation, tests, and the Core-owned
   Changes pane at `review` density.
2. S-Flow: minimal reference migration.
3. S-Initiative: complex ghost/reference migration.
4. S-Team: document alternatives and governance-guard migration.
5. Source facade releases.
6. S-Cockpit: cross-application reaction dispatch.
7. Core/application cleanup.
8. Generic binding proof as a separate, capability-scoped Core-client release.

No backward-compatibility layer, route shim, or persisted-data migration is
required.

## Completion criteria

- The same stage has the same colour, background, leading edge, wording, and
  motion in every normal application; dots appear only while `in_flight`.
- Dashed always means a one-perspective representation, value, or position.
- Every Adopt, Take-back, and React control is rendered by Core.
- Adopt and Take-back icons appear both on direct controls and inside React
  menus.
- Generic open changes are never labelled Proposal.
- Applications contain placement and authorization logic, but no duplicated
  transition presentation or event-grouping logic.
- First-party callers opt into their intended reaction density.
- Transition markers, decoration, and reaction controls work without
  `SovereignShell` or pane markup.
- The generic binding proof synchronizes and reacts to one ordinary textarea
  through the existing Python Core host under a narrow capability.
- Existing synchronization, adoption, rollback, and governance tests remain
  unchanged in behavior and pass.
