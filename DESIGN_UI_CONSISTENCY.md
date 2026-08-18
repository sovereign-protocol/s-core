# Common elements of all Sovereign applications

Core owns the shell — header, dialogs, panes — so consistency across
applications is Core's concern rather than each application's. The first
half of this document is the original wish list; the **Decisions** section
below it is what was accepted and built, and is the part to read as
binding.

## Disagreement and Reactions

- Changes waiting for sync could show a small lamp on the top right of the field (like in a card on Kanban)
- highlighting nodes not Aligned + showing explaination text on mouseover
- Reaction buttons, dependent on who made the change and what kind of alignment is there

## Header on top

The top header should be have a consistent format for all apps. (e.g. Agreement lacks the line separating header from content and has a different format/position of elements). Here what a setup could be, left to right:
Left aligned:

- Collaboration icon (where there is a definite topic), opening the collab pane
- Name of selected topic
- pull-down button to select another topic
- Overall status of this topic (Aligned, synced..)

Middle:

- Icon and Name of the app
- Button(s) to navigate to another view or app (e.g. the four quadrant button for the overview)
- A [+] button to create an new topic, opening a modal for specifying what and how (topic specific)

Right aligned:

- a connect-area showing "local" when disconnected or the avatars of people connected with the current topic, clicking on the connect-area opens a right pane to show details of current connected peers, create and enter tokens (channel + current topic) to add/drop connections, to add/edit/delete channels (e.g. relay targets),
- My own avatar - clicking on it opens my avatar settings

## Colour Themes

- I like the idea of a general dark coulor theme (Kanban gray, cockpit blue) what color for agreements ?

---

# Decisions

Status: **U1-U6 accepted and implemented. U7 and U8 accepted, being built.**

## U1 — chrome is Core's, content is the application's

**ACCEPTED.** The shell's chrome — header, dialogs, panes — looks identical in
every application. Each application owns only its content area: the board, the
document, the overview.

Rationale: the shell was first written colour-neutral so each page could set
the surrounding palette. That guaranteed divergence. The same relay-target
dialog rendered three different ways, because Kanban styles `input`, Personal
Cockpit styles `dialog input`, and S-Team styles neither and fell through
to browser defaults. Core owns the functionality, so Core owns the appearance;
otherwise every application must re-style Core's markup, and a minimal one
never will.

Shell colours are exposed as tokens on `.shell-dialog` / `.shell-bar` so an
application _can_ re-theme deliberately. Doing nothing yields the same chrome
everywhere, which is the point.

## U2 — reserved colours

**ACCEPTED.** These carry meaning and must not become an application's identity:

| Colour          | Means                                   |
| --------------- | --------------------------------------- |
| red             | divergence                              |
| amber           | in transition                           |
| teal (`--teal`) | the shared accent, identical everywhere |
| green           | reads as "agreed" / success             |

An application palette picks from what is left.

## U3 — header layout

**ACCEPTED**, per the layout above. Fixed regions, left to right:

| Region | Holds                                                                                     |
| ------ | ----------------------------------------------------------------------------------------- |
| Left   | collaboration button (opens the agreement pane), topic name, topic switcher, topic status |
| Middle | application icon and name, navigation to other applications, `[+]` new topic              |
| Right  | connect area (peers, or "local"), own avatar                                              |

**Amended, 2026-08-17 — the regions are what you are looking at, where else
it reaches, and who is here:**

| Region | Holds                                                              |
| ------ | ------------------------------------------------------------------ |
| Left   | collaboration button, divider, application mark, topic name, topic status |
| Middle | the Cockpit, link chips, `[+ Link]`                                |
| Right  | the application's own controls, connect area, own avatar           |

The **topic switcher is gone**. Core already held the principle — _"topic
applications return through the Cockpit instead of forming a second
navigation mesh among themselves"_ — and a list of one application's own
topics in its own header was exactly that mesh, built before the Cockpit
existed. S-Team's teams are chosen in its Organizations tree, and every other
topic is a Cockpit tile away. `setTopicSelector` is `setTopicName`: a name,
edited in place where the application allows it, and nothing beside it.

**Left is one subject**: this topic, under its application's mark, with the
people on it and its state. The mark alone and not the wordmark — beside a
topic's own name the application's name is the redundant half, and an icon
says which application this is without competing to be read. The name element
stays in the DOM for a screen reader, which cannot see a mark.

**Middle is where else this reaches**, at two ranges: the Cockpit is every
topic you hold, the chips are the ones this topic names. `[+ Link]` closes
that row rather than opening it — the references are what there is to read,
and adding one is what you do about them. The Middle is the column that
grows, so the grid gives it the free space instead of centring it.

Notes from implementing it:

- The `[+]` new-topic button of the original layout was never built as a
  shell fixture and is not one now. Making a topic starts where the new one
  will belong: `[+ Link]` on a topic that will name it, and the Cockpit's own
  "+ Add new" for one belonging to nothing. Both open the same dialog (U5).
- Channel management moved _into_ the connection pane, as the layout implies.
  There is no separate "Relay targets" button in the header any more.
- An application showing many topics at once has no single topic status, so
  the left region collapses rather than claiming one.

**Superseded in part by U7, 2026-08-18.** The regions are renamed for what
they are — collaboration, navigation, connections — and two of their subjects
swap: the topic moves to the Middle and is centred, and everywhere it reaches
becomes one row of destinations beneath its name, the Cockpit included.

## U4 — one theme for 0.1

**ACCEPTED: dark everywhere.** S-Cockpit's dark half was applied
unconditionally, and all three applications now declare `color-scheme: dark`
so native controls, scrollbars, and form widgets match instead of rendering
light on a dark surface.

U1 forced this. Once the shell's chrome became unconditionally dark, an
application that followed `prefers-color-scheme` put a dark dialog on a light
page - measured on a light-mode machine: page `#f4f5f7`, dialog `#161b22`.
Following the machine per application is only coherent if _everything_
follows it, including Core's chrome.

Cost of the alternative, for when this is revisited: four palettes, of which
one existed. Kanban carries about ten tokens in `:root`, the shell seven, and
S-Team is mostly literal hex and would need tokenizing first.

Light mode returns as a themed pass across Core and all three applications,
with the open question of whether the machine chooses (`prefers-color-scheme`)
or the person does - a toggle stored in the Core profile would follow the user
across every application, since the profile is already Core.

**Amendment, 2026-07-26:** U4 originally kept one deliberate exception -
S-Team's document surface stayed light (`#f9fafb`), reasoned as paper
inside a dark frame. Using the desktop build surfaced that the exception
reads as a bug, not a design: a black-on-white panel inside an otherwise
dark window looks like the one thing that failed to theme, not like a
considered choice. "Dark everywhere" now means everywhere, including the
document itself - the panel moved to `#262319`, one step lighter than the
page, the relationship S-Initiative already uses for `--surface` over `--bg`.
No exception survives pending the theme toggle above.

## U5 — making a topic is one dialog

**ACCEPTED.** `SovereignShell.openNewTopicDialog` is the only way a topic is
made. It asks what the thing is called, what it starts from, and offers a
snapshot file instead of both; the application supplies the noun, the list of
templates, whether one is required, the snapshot type it accepts, and the call
that creates.

U1 predicted this and the evidence arrived anyway. There were four copies —
`newBoardModal`, `newTeamModal` and `newFlowModal` in the Cockpit, and
`newItemModal` in S-Team — identical but for the noun and whether the template
select was required. The S-Team copy was the only place a snapshot file could
not be loaded. That was not a decision anybody took about teams; it is what a
copy costs, and it is exactly the divergence U1 was written to prevent.

The line between the two owners is what each half can know:

| Core | the application |
| --- | --- |
| the form, its wording, the order of the questions | the noun |
| that a name field is a placeholder and never a value | what a template *is* — a board to copy, a team to clone, a workflow definition |
| reading a snapshot file, and refusing the wrong one | whether starting from nothing is allowed |
| hiding a question nobody asked — no templates, no snapshot | what creating calls, and what it says afterwards |

A snapshot and a template are alternatives, not both: loading a file disables
the template select rather than quietly ignoring it. The file is checked here
so the wrong one is refused while the dialog is open, but the application that
owns the kind validates it again and is the authority.

**Amended, 2026-08-17.** The application no longer supplies the noun, the
templates or the create call from a table of its own. It reads them from
`Session.topic_kinds()` and creates through `create_application_topic`, both
answered by the owning application's `ApplicationRegistration`. Three
applications had each grown that table; one of them could start a team from a
snapshot file and another could not, which is the same drift U1 predicts about
appearance, arriving in behaviour. See `PUBLIC_API.md`, "Making a topic".

## U6 — what a topic is attached to is shown by Core, beside its name

**ACCEPTED.** `SovereignShell.setTopicLinks` draws every reference a topic
makes, as chips after `[+ Link]` in the Middle region. S-Initiative's chips
and S-Team's rows-and-pulldowns were two renderings of one thing; both are
gone.

Where the line falls:

- **Core** draws the chips, opens the link menu, and performs the two acts
  that are its own: taking up a reference you do not hold, and removing one.
  It composes every destination from `application_summaries()`, so no
  application knows another's route — the query parameter is `?topic=` in all
  of them, which is what made that possible.
- **The application** says which links exist, what there is to link, and what
  making one calls.

Three consequences worth stating.

**Nobody sets who may remove.** A link is adopted same-origin, so the only
reference you can take off is the one you put up — Core refuses the rest in
`remove_topic_link` rather than deleting locally and diverging. The `×` acts
at once, everywhere, with no confirmation: what it removes is one reference,
and the topic and everybody else's reference to it are untouched.

**An offer is a link, drawn dimmed.** S-Team kept unheld items out of the
list and in a "Connect to…" pulldown, reasoning that a row is something you
can open and an offer is not. True of a row; not true of a chip that says so
itself. Clicking a dashed chip takes it up.

**A link on the topic belongs in the bar; a link on a node does not.** A card
naming the process it waits on renders beside the card — in the bar it would
be a fact about something you cannot see. This settles the open question in
`DESIGN_TOPIC_LINKS.md` about a reference to an unreachable topic: beside the
node it is information, in the topbar it would be noise.

The bar shows four chips and turns the rest into a count that opens the full
list. A team can run a dozen things; a bar that holds all of them stops being
a bar.

**Superseded in part by U7, 2026-08-18.** What a topic is attached to is still
Core's to draw and still lives beside the name — but as one menu, not as
chips. The last sentence above is the reason: the bar lost the argument at
four chips, not at twelve.

## U7 — one bar, five objects

**ACCEPTED, not yet built.** The header had grown thirteen visual treatments
and no focal point. This fixes both, and amends U3 and U6 where they conflict.

### What was wrong

Counted from the shipped bar: a bordered icon box, a rule, a filled rounded
square, an 18px/700 editable field, up to three pill status bands in three
colours, an icon nav link, a bordered pill chip carrying a 10px uppercase
label and a `×`, a dashed variant of that chip, a dashed `[+ Link]` pill, a
bare `+N`, the avatar cluster, the avatar button, and whatever an application
put in `shell-app-actions`. Thirteen treatments, four border languages
(solid, dashed, none, hover-underline), three corner radii, five type sizes.

No ordering fixes that; the vocabulary itself has to shrink.

The structure fault is separate and literal: `grid-template-columns: auto
minmax(0, 1fr) auto` cannot centre anything, so nothing in the bar was
anchored and the eye had no entry point.

### The regions

| Region | Holds |
| ------ | ----- |
| Left — collaboration | `[Agenda · N]`, `[Changes · N]` |
| Middle — navigation | application mark and topic name; a row of destinations beneath |
| Right — connections | the people on this topic, then your own avatar |

Five objects, down from thirteen, and the three names are parallel because
the regions are: what is being worked out, where you can go, who is here.
Status stays with the function it belongs to — what needs deciding sits on
the control that opens the pane where you decide it, and who is online sits
on the avatars.

**The Middle is centred and is the anchor.** The grid becomes `minmax(0, 1fr)
auto minmax(0, 1fr)` with the middle shrink-to-fit, so the title is optically
centred and does not shift when a person joins or a count appears — which the
old `auto 1fr auto` could not do at any width. It is the only two-line object
in the bar, which is what makes it read as the anchor without being large:
15px is enough where 18px/700 was shouting to compensate for being off to one
side.

**The name is not a field at rest.** It renders as plain text; the edit box
appears only while editing. A 34px control with a transparent border reads as
a widget, not as the name of the thing you are looking at. While editing it
takes a fixed minimum width, so both flanks absorb the growth symmetrically
instead of the bar shoving sideways.

**The title line holds two elements and no more** — the mark and the name.
That is what lets it read as an anchor at a glance, and it is why nothing
else was allowed onto it. A switcher chevron sat there through one revision;
it pushed the name off the centre line by half its own width, which undid the
reason the topic had been moved to the middle at all.

**The kind is not drawn beside the name.** `topic_noun` names the field and
supplies the rename placeholder, but it is not rendered as a word next to the
mark that already says it. Measured in use: "Initiative · in Alpha" beneath a
board whose mark is a board says the same thing twice, once as a picture and
once as a word. This is U3's finding about the wordmark, arriving again about
the noun. Where kinds are genuinely mixed — Cockpit tiles — naming them is
still right.

### The navigation row

Beneath the name, and it is the whole of the middle's second line: what this
topic names, then everything you hold, with a rule where the range changes.

    Elect Identity for Toma · Alpha  ⌄ | ▦

**Names only, and every one of them a link.** The kind label a chip used to
carry in small capitals earned nothing — the destination says what it is the
moment you arrive — and dropping it is what makes the row uniformly one class
of thing, and therefore uniformly clickable. A row that is text in some
places and a link in others teaches nothing.

**Hover brightens; it never emboldens.** A bolder face is wider than the text
it replaces, so it reflows the row and drags everything to its right
sideways; on a centred layout the whole line jitters. Muted to full strength
reads as the item coming forward and moves nothing.

**The chevron is unconditional and is not a count.** Its menu lists every
related topic, whether or not it fitted, plus `Link related…`. Because
nothing is ever hidden there is nothing to signal — no `+N`, no ellipsis, and
no case the reader has to be taught. `Link related…` must be reachable
whether or not anything overflowed, which is what ruled out hanging it off a
control that only appears when something does.

**The Cockpit is on this row, last.** It is the widest range, so it sits at
the far end, and the rule before it states the jump — the one separator that
whitespace could not have said. It was tried on the far left, where it reads
as an application logo and lands in the collaboration region, and on the far
right, where it lands among the people. Neither region is about going
anywhere; this one is.

Its mark is small at this size, so the target is padded well past the glyph.
Where no application registers as an aggregator both the mark and the rule
are absent, along with the wording that names it (`DESIGN_VOCABULARY.md`).

**Only the names shrink.** The chevron, the rule and the Cockpit are
`flex: none`; the list of names is `min-width: 0` and clips. A long list
truncates itself rather than pushing the controls off the bar.

Items you do not hold are not on this row and not in its menu. U6 reasoned
that an offer is a link drawn dimmed, which was right for a chip you could
click; among places to go, a row that goes nowhere until you take it up is a
different act, and it lives in the dialog with the other acts.

**An aggregator draws no row at all.** The Cockpit already shows every topic
you hold, so a row offering a few of them — and offering the Cockpit itself —
is the second navigation mesh Core has refused since U3, rebuilt one line
lower. An application with no topic selected draws none either: there is
nothing to place.

### The name is sized by its line box

`.ui-editable-text` carries `min-height: 34px` for full-size fields, and
`min-height` beats `height`. Setting a height on the title in the bar
therefore did nothing: the name sat in a box a third taller than the row and
out of line with the mark beside it. It is sized by `line-height` with
`min-height: 0`, so the text and the mark share one optical centre whatever
the font does.

This is the general hazard of restyling a shared primitive by its outer
class. Anything the bar shrinks needs its `min-*` floors cleared, not just
its sizes set.

### The shape vocabulary

Binding, because thirteen treatments is what happens without it.

| | |
| --- | --- |
| Bar | one row, 52px, one hairline beneath |
| Sizes | control 28px, avatar 24px, icon 18px, and nothing else |
| Shapes | two: a circle is a person, a 6px rounded rect is a control |
| Borders | none at rest; hover is an 8% surface tint, open is 14% |
| Type | two sizes: 15px/600 for the name, 12px for everything else |
| Colour | the count takes the conflict colour when any change is a conflict, otherwise neutral; no other colour but the focus ring |

No 999px pills anywhere in the bar, and no dashed borders — dashed means "not
yours yet", which is a distinction you can only read where there is room to
explain it.

### What this costs

- **`setAppActions` goes.** The shell bar holds no application controls at
  all. Its two callers move: S-Initiative's auto-adopt indicator into the
  collaboration pane as a labelled row (a 2×2 square nobody can read is not a
  control), and the Cockpit's `+ New` into its own grid, which is what U5
  already describes as "the Cockpit's own '+ Add new'".
  `s-cockpit/tests/test_package_layout.py` asserts the call exists and changes
  with it.
- **The three status bands become one count**, and the count is conflicts plus
  what needs your review — not what is still travelling. The reasoning, and
  where the other states are shown instead, is in `DESIGN_VOCABULARY.md`.
- **The application mark moves** from the Left to the Middle, where it forms
  one lockup with the name. The screen-reader-only name element moves with it.
- Wording throughout the bar follows `DESIGN_VOCABULARY.md`, which was fixed
  first so nothing is renamed twice.

## U8 — three classes of icon, three construction rules

**ACCEPTED, not yet built.** Icons drifted for the same reason the header did:
nothing said what kind of thing an icon is, so each was drawn to its own
recipe. There are three classes and they are built differently.

| Class | Construction | Why |
| --- | --- | --- |
| Application mark | whole shapes on the grid, straight edges, 3–5 of them | renders at 18px in the header lockup |
| Object | one idea, four strokes at most | appears beside a name, at rest, in lists |
| Act | the conventional glyph, never invented | a person must recognise it without learning it |

All of them: `viewBox="0 0 24 24"`, `fill: none`, stroke `currentColor`,
round caps and joins. An application mark **depicts what the application
holds** — it does not characterise it. A rocket for S-Initiative was
considered and rejected: five shapes with curves and diagonals fills in at
18px, it is a metaphor standing beside three depictions, and it promises a
launch that a board of moving cards does not have.

### Application marks

| Application | Paths |
| --- | --- |
| S-Cockpit | unchanged — four 7×7 rects at 3,3 / 14,3 / 3,14 / 14,14, `rx="1"` |
| S-Team | `<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4"/><path d="M6 16v-4h12v4"/>` |
| S-Initiative | `<rect x="4" y="4" width="6" height="14" rx="2"/><rect x="14" y="4" width="6" height="8" rx="2"/><path d="M5.5 7.5h3"/><path d="M15.5 7.5h3"/>` |
| S-Flow | `<circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><path d="M7 12h3"/><path d="M14 12h3"/>` |

S-Team's document mark is retired: it depicted paper, and paper is what the
Agreement is, so the application and one of its own objects claimed the same
glyph. S-Flow's square-and-checkmark read as a checklist rather than
something that moves through stages. S-Initiative's three descending bars
read as a bar chart; two rounded columns read as a board.

### Objects

| Object | Paths |
| --- | --- |
| Agreement | `<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 14l2 2 4-4"/>` |
| Role | `<path d="M12 3l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V6z"/>` |
| Seat | the Role shield with `<circle cx="12" cy="9.5" r="1.8"/><path d="M9 14.4c.5-1.4 1.6-2.2 3-2.2s2.5.8 3 2.2"/>` |
| Members | `<circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><path d="M21 21v-2a4 4 0 0 0-3-3.85"/>` |
| Purpose | `<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.9"/>` |
| Agenda | three `r="1.1"` dots at x=5, y=7/12/17, with `<path d="M9 7h10"/><path d="M9 12h10"/><path d="M9 17h6"/>` |
| Trustee | `<circle cx="8" cy="15" r="3.6"/><path d="M10.6 12.4L20 3"/><path d="M15.6 7.4l2.6 2.6"/>` |

**Role, Seat and Members are the set that has to be tested at 18px first.**
They are the distinction the domain turns on: a Role is an office with nobody
in it, a Seat is that office filled (`team_role_holding`), and Members are
people irrespective of office. If those three read as one thing, the set has
failed.

**Trustee is a key** because a trustee holds the team's identity on behalf of
the members — `agreement_identity` is a trustee role, per
`DESIGN_NODE_CLASSES.md`. Not a gavel, which reads legal and is illegible
small; not a crown or star, which read status rather than stewardship.

Two glyphs became available through decisions taken elsewhere: the document,
once S-Team stopped using it, and two-people, once U7 removed the
collaboration button that owned `ICON_COLLABORATION`.

### Acts, and the three destructions

`DESIGN_TOPIC_LINKS.md` keeps **remove**, **drop** and **delete** strictly
apart, and records what conflating them cost: a list removal that called
`delete_process` destroyed the thing everywhere. At the surface those three
become two promises, and each promise gets one glyph that is never used for
the other.

| Glyph | Means | Paths |
| --- | --- | --- |
| minus in a circle | off my side, reversible — removing a link, dropping a topic | `<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>` |
| trash can | gone for everyone | unchanged |
| `×` | close, never destructive | unchanged — reserved, so it can never be read as either |

`ICON_SETTINGS` is redrawn: Feather's gear is a twenty-node path that turns
to mush at 18px. A circle with eight radial ticks survives the size —
`<circle cx="12" cy="12" r="3.2"/>` with ticks at 12/3, 12/18.6, 3/12,
18.6/12 and the four diagonals.

There is one settings glyph, not two. Splitting "configure" from
"preferences" is a distinction the reader has to be taught, which is what an
act glyph must never require.

### Attribution

The shipped paths for gear, trash, expand, collapse and share are Feather's,
which is MIT and requires its notice to travel with redistribution; the
Members and Board geometry follows Tabler, MIT on the same terms. `NOTICE`
has no third-party section. Either it gains an MIT attribution block or every
path is redrawn originally — the repositories are public, so this is decided
before release, not after.

### Not yet assigned

`NODE_LABELS` also carries Section, Clause, Accountability, Domain, Role
answer, Membership application, Membership invitation, Membership type,
Trustee election and Trusteeship state. Most need no mark of their own:
Section and Clause are document structure and inherit the Agreement family,
and the membership variants are states of one object — one glyph with a
state, not four glyphs. **Trustee election is the one real gap**: it has to
read as contested, and a key does not.

## Current palettes

| Surface      | Colour                 | Note                                                    |
| ------------ | ---------------------- | ------------------------------------------------------- |
| Shell chrome | `#161b22` on `#0d1117` | Core's, identical everywhere (U1)                       |
| S-Initiative | `#171818` warm gray    |                                                         |
| S-Cockpit    | `#0d1117` blue-gray    |                                                         |
| S-Team       | `#1c1a17` warm ink     | document panel `#262319`, one step lighter (2026-07-26) |

S-Team was `#111827` until U2, almost exactly the Cockpit's `#0d1117`, so
two of the three applications looked alike. The warm neutral separates it and
avoids every reserved colour.

## Modal Conventions

- X top-right, click-outside-to-close
