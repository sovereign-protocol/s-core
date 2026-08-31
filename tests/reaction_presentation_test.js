"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/sovereign/assets/shared.js"),
  "utf8",
);
const context = {
  document: {
    documentElement: {setAttribute() {}},
    getElementById() { return null; },
    createElement(tagName) {
      return {
        tagName: tagName.toUpperCase(),
        dataset: {},
        setAttribute(name, value) { this[name] = String(value); },
      };
    },
  },
  window: {
    localStorage: {getItem() { return null; }},
  },
};
vm.runInNewContext(
  `${source}\nglobalThis.__SovereignUI = SovereignUI;`,
  context,
);

const present = (choices, density) => (
  context.__SovereignUI.reactionPresentation(choices, density)
);
const adopt = {action: "adopt", label: "Adopt card change from Alice"};
const adoptOther = {action: "adopt", label: "Adopt card change from Bob"};
const rollback = {action: "rollback", label: "Take back my card change"};

assert.deepEqual(
  {...present([adopt], "inline")},
  {menu: false, iconKind: "adopt", label: "Adopt"},
);
assert.deepEqual(
  {...present([adopt], "review")},
  {menu: false, iconKind: "adopt", label: "Adopt"},
);
assert.deepEqual(
  {...present([rollback], "inline")},
  {menu: false, iconKind: "rollback", label: "Take back"},
);
assert.deepEqual(
  {...present([adopt, adoptOther], "inline")},
  {menu: true, iconKind: "adopt", label: "Adopt"},
);
assert.deepEqual(
  {...present([adopt, rollback], "inline")},
  {menu: true, iconKind: "react", label: "React"},
);

const localReordering = {
  type: "local_made_changes",
  stage: "awaiting_peer",
  reaction: "rollback",
  authored_locally: true,
  peer_addr: "relay:A",
  changes: [{node_label: "Section", authored_noun: "reordering"}],
};
assert.equal(
  present(localReordering, "review").label,
  "Take back",
);
assert.equal(
  present({...localReordering, reaction: "adopt", authored_locally: false}, "review").label,
  "Adopt",
);
const initiativeEdit = {
  ...localReordering,
  changes: [
    {node_label: "Initiative", authored_noun: "modification", authored_detail: "name changed"},
    {node_label: "Initiative", authored_noun: "modification", authored_detail: "intention changed"},
  ],
};
assert.equal(
  present(initiativeEdit, "review").label,
  "Take back",
);
assert.equal(
  present({
    ...localReordering,
    type: "peer_made_changes",
    reaction: "adopt",
    authored_locally: true,
  }, "review").label,
  "Adopt",
);

assert.equal(
  context.__SovereignUI.transitionMarker(
    {stage: "awaiting_me"},
    {stages: ["in_flight"]},
  ),
  null,
);
assert.equal(
  context.__SovereignUI.transitionMarker({stage: "awaiting_me"}),
  null,
);
assert.equal(
  context.__SovereignUI.transitionMarker({stage: "in_flight"})
    .dataset.transitionStage,
  "in_flight",
);
const travellingMarker = context.__SovereignUI.transitionMarker(
  {
    stage: "awaiting_me",
    events: [
      {stage: "awaiting_me", type: "peer_made_changes", peer_addr: "relay:A"},
      {stage: "in_flight", type: "local_made_changes", peer_addr: "relay:B"},
    ],
  },
  {stages: ["in_flight"]},
);
assert.equal(travellingMarker.dataset.transitionStage, "in_flight");

const heldMarker = context.__SovereignUI.adoptionPolicyMarker({adopt: "hold"});
assert.equal(heldMarker.getAttribute?.("role") || heldMarker.role, "img");
assert.equal(heldMarker.title, "Changes here wait for your approval.");
assert.equal(context.__SovereignUI.adoptionPolicyMarker({adopt: "auto"}), null);
assert.equal(
  context.__SovereignUI.adoptionPolicyMarker(
    {adopt: "hold"}, {transition: {stage: "awaiting_me"}},
  ),
  null,
);
