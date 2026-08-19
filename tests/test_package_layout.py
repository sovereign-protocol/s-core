"""Packaging and asset invariants for what Core actually ships.

The pre-split repository checked all four distributions at once by
hard-coding each version. That could only run where every package was
installed, and the literals went stale the moment one distribution
released on its own. Each repository now asserts its own layout, and the
version assertion states the invariant that matters - metadata and module
agree - rather than a number that has to be edited on every release.
"""

import ast
import importlib.metadata
import importlib.util
import unittest
from importlib.resources import files
from pathlib import Path

import sovereign


ROOT = Path(__file__).resolve().parents[1]
SHARED_JS = files("sovereign.assets").joinpath("shared.js").read_text(encoding="utf-8")
SHARED_SESSION_JS = files("sovereign.assets").joinpath(
    "shared-session.js",
).read_text(encoding="utf-8")


class PackageLayoutTests(unittest.TestCase):
    def test_distribution_and_module_versions_agree(self):
        self.assertEqual(
            importlib.metadata.version("sovereign-protocol"), sovereign.__version__,
        )

    def test_old_flat_core_modules_are_not_importable(self):
        for module_name in (
            "protocol", "session", "transport", "relay_logic",
            "relay_storage", "blob_store", "topic_registry", "versions",
        ):
            self.assertIsNone(importlib.util.find_spec(module_name), module_name)

    def test_installed_browser_assets_are_available(self):
        self.assertTrue(files("sovereign.assets").joinpath("shared.js").is_file())
        self.assertTrue(
            files("sovereign.assets").joinpath("shared-api.js").is_file(),
        )
        self.assertTrue(
            files("sovereign.assets").joinpath("shared-session.js").is_file(),
        )
        self.assertTrue(files("sovereign.assets").joinpath("manual.html").is_file())

    def test_package_sources_live_under_the_declared_src_root(self):
        # Asserting where the imported module loaded from only holds for an
        # editable install: CI installs a wheel, so __file__ points into
        # site-packages. The invariant is this repository's layout - the
        # source sits under src/, and no flat copy survives beside it for an
        # import to pick up ahead of the installed package.
        self.assertTrue((ROOT / "src" / "sovereign" / "__init__.py").is_file())
        self.assertFalse((ROOT / "sovereign").exists())

    def test_applications_cannot_receive_channel_manager(self):
        from sovereign.application import ApplicationServices

        self.assertNotIn("channel_manager", ApplicationServices.__dataclass_fields__)

    def test_shared_peer_renderer_does_not_depend_on_channel_rows(self):
        peers_renderer = SHARED_JS.split("_renderPeersList() {", 1)[1].split(
            "async _renderConnTargets() {", 1,
        )[0]
        self.assertNotIn("channel.", peers_renderer)

    def test_topic_app_headers_delegate_navigation_and_creation_to_cockpit(self):
        self.assertNotIn("shellCreateTopicBtn", SHARED_JS)
        self.assertIn('app.role === "aggregator"', SHARED_JS)

    def test_shared_ui_kit_exposes_only_reusable_primitives(self):
        for primitive in (
            "avatar", "entityBadge", "disclosure", "editableText",
            "reorderHandle", "reorderableList", "addComposer",
            "selectControl", "refreshSelect", "selectOptions",
            "selectionControl", "selectionField",
            "actionMenu", "reactionControl",
        ):
            self.assertIn(f"  {primitive}(", SHARED_JS)

    def test_selection_fields_and_action_menus_have_distinct_shared_contracts(self):
        shared_css = files("sovereign.assets").joinpath("shared.css").read_text(
            encoding="utf-8",
        )
        selection = SHARED_JS.split("  selectionControl(options = {}) {", 1)[1].split(
            "\n  selectionField(options = {}) {", 1,
        )[0]
        field = SHARED_JS.split("  selectionField(options = {}) {", 1)[1].split(
            "\n  actionMenu(options = {}) {", 1,
        )[0]
        menu = SHARED_JS.split("function ensureActionMenu() {", 1)[1].split(
            "\nfunction openActionMenu(", 1,
        )[0]
        self.assertIn('document.createElement("select")', selection)
        self.assertIn('select.addEventListener("change", options.onChange)', selection)
        self.assertIn("this.selectionControl(options)", field)
        self.assertIn('control.className = "ui-select-control"', SHARED_JS)
        self.assertIn('select.classList.add("ui-select", "ui-select-native")', SHARED_JS)
        self.assertIn('button.setAttribute("aria-haspopup", "menu")', SHARED_JS)
        self.assertIn('event.key === "ArrowDown"', menu)
        self.assertIn('event.key === "Escape"', menu)
        self.assertIn(".ui-select-control", shared_css)
        self.assertIn("select.ui-select-native", shared_css)
        self.assertIn("border: 1px solid var(--line", shared_css)
        self.assertIn("color-scheme: inherit", shared_css)
        self.assertIn("select.ui-select-native option", shared_css)
        self.assertIn("var(--surface, var(--panel, var(--shell-surface, Canvas)))", shared_css)
        self.assertIn(".ui-action-menu", shared_css)

    def test_shared_editable_text_owns_text_field_appearance_and_behavior(self):
        shared_css = files("sovereign.assets").joinpath("shared.css").read_text(
            encoding="utf-8",
        )
        for marker in (
            "ui-editable-text", "dataset.placeholder", "allowEmpty", "onCommit",
        ):
            self.assertIn(marker, SHARED_JS)
        self.assertIn(".ui-editable-text,", shared_css)
        self.assertIn(".ui-text-field", shared_css)

    def test_shared_js_requires_no_dom_element_at_load(self):
        """Core must not make an element an unwritten requirement of using it.

        `document.getElementById("confirmModalCancelBtn").onclick = ...` ran at
        the top level, so an application page without that markup threw partway
        through this file: `SovereignUI` was defined, `SovereignShell` was not,
        and the page rendered nothing with an empty console. S-Flow had no
        confirm modal and had therefore never displayed a process. Anything
        Core touches at load time has to tolerate its absence.
        """
        offenders = [
            (number, line)
            for number, line in enumerate(SHARED_JS.splitlines(), start=1)
            if line.startswith(("document.", "window.document."))
        ]
        self.assertEqual(offenders, [])

    def test_entity_badges_share_one_outer_height(self):
        shared_css = files("sovereign.assets").joinpath("shared.css").read_text(
            encoding="utf-8",
        )
        self.assertIn(".ui-entity-badge {", shared_css)
        self.assertIn("box-sizing: border-box", shared_css)
        self.assertIn("min-height: 32px", shared_css)

    def test_one_dialog_makes_a_topic_wherever_it_is_made(self):
        """Four copies of one form had already drifted apart.

        Three in the Cockpit and one in S-Team, identical but for the noun -
        and the S-Team one was the only place a snapshot file could not be
        loaded. Nobody decided that; it is what a copy costs. The shape is
        Core's now, so there is nowhere for the next drift to start.
        """
        dialog = SHARED_JS.split(
            "openNewTopicDialog(options = {}) {", 1,
        )[1].split("\n  },", 1)[0]
        # A prefilled name turns "I did not type one" into a name somebody
        # chose. Placeholder, never value.
        self.assertIn('name.value = "";', dialog)
        self.assertIn("name.placeholder = `Untitled ${noun}`", dialog)
        # Nothing to start from and nothing required is not an empty menu,
        # it is no question - and so is a kind that has no snapshot to read.
        self.assertIn("!templates.length && !required", dialog)
        self.assertIn("!options.snapshotType", dialog)

    def test_a_loaded_snapshot_settles_what_a_topic_starts_from(self):
        loader = SHARED_JS.split(
            "async _loadSnapshotChoice(chosen) {", 1,
        )[1].split("\n  },", 1)[0]
        self.assertIn("s-protocol.item-snapshot", loader)
        self.assertIn("state.options.snapshotType", loader)
        self.assertIn("SNAPSHOT_FILE_LIMIT", loader)
        # Disabled rather than quietly ignored: a select that goes on
        # offering a choice the create call will not use is a lie.
        self.assertIn("select.disabled = true", loader)

    def test_open_collaboration_pane_refreshes_with_polled_topic_state(self):
        refresh = SHARED_JS.split("refresh() {", 1)[1].split("},", 1)[0]
        self.assertIn("this.refreshCollaborationPane()", refresh)
        pane_refresh = SHARED_JS.split("refreshCollaborationPane() {", 1)[1].split(
            "\n  },", 1,
        )[0]
        self.assertIn("if (!pane || pane.hidden) return", pane_refresh)
        self.assertIn("this._renderAgenda()", pane_refresh)
        self.assertIn("agenda.contains(document.activeElement)", pane_refresh)

    def test_the_header_counts_only_what_a_decision_is_owed_on(self):
        """One number, and it excludes what is merely travelling.

        The bar used to carry three coloured bands - "to resolve", "to
        review", "in transition". U7 replaced them with one count on one
        control, and DESIGN_VOCABULARY.md fixes what it counts: a conflict,
        or somebody else's change waiting for me. A count that includes what
        you cannot act on is a count you learn to ignore.
        """
        refresh = SHARED_JS.split("refreshDisagreements() {", 1)[1].split(
            "\n  },", 1,
        )[0]
        self.assertIn("const owed = conflicts + mine;", refresh)
        self.assertIn('this._setCount("shellChangesBtn", owed, "Changes")', refresh)
        # Travelling is still visible - it pulses rather than counting.
        self.assertIn('changes.classList.toggle("is-moving", moving > 0)', refresh)
        # The retired bands are gone from the surface entirely.
        for retired in (
            "In transition",
            'text: "to resolve"',
            'text: "to review"',
            'text: "in transition"',
            "Current divergences",
        ):
            self.assertNotIn(retired, SHARED_JS)
        self.assertIn("No open changes.", SHARED_JS)

    def test_confirmed_snapshot_replaces_optimistic_projection_atomically(self):
        confirmation = SHARED_SESSION_JS.split(
            "async _confirm(", 1,
        )[1].split("\n    _remove(", 1)[0]
        self.assertIn("this._beginBatch()", confirmation)
        self.assertIn("this._endBatch(", confirmation)

    def test_agenda_reordering_uses_the_shared_control(self):
        agenda_row = SHARED_JS.split("_agendaRow(item) {", 1)[1].split(
            "\n  _renderAgenda() {", 1,
        )[0]
        agenda = SHARED_JS.split("_renderAgenda() {", 1)[1].split(
            "\n  refreshCollaborationPane() {", 1,
        )[0]
        reorder = SHARED_JS.split("reorderableList(options = {}) {", 1)[1].split(
            "\n  addComposer(options = {}) {", 1,
        )[0]
        self.assertIn("SovereignUI.reorderHandle", agenda_row)
        self.assertIn("SovereignUI.reorderableList", agenda)
        self.assertIn('document.addEventListener("mousemove", move)', reorder)
        self.assertIn('document.addEventListener("mouseup", up)', reorder)
        self.assertIn('event.key !== previous && event.key !== next', reorder)
        self.assertNotIn("row.draggable = true", agenda_row)

    def test_collaboration_selects_use_the_shared_option_population(self):
        agenda_row = SHARED_JS.split("_agendaRow(item) {", 1)[1].split(
            "\n  _renderAgenda() {", 1,
        )[0]
        auto_adopt = SHARED_JS.split("_autoAdoptControl() {", 1)[1].split(
            "\n  openCollab() {", 1,
        )[0]
        self.assertIn("SovereignUI.selectionControl({", agenda_row)
        self.assertIn('variant: "compact"', agenda_row)
        self.assertIn("SovereignUI.selectionControl({", auto_adopt)

    def test_agenda_creation_uses_the_shared_optimistic_session(self):
        create = SHARED_JS.split("async _addAgendaItem()", 1)[1].split(
            "_identityFor(uuid)", 1,
        )[0]
        self.assertIn("sessionView.mutate", create)
        self.assertIn("optimisticUuid", create)
        self.assertIn('invalidates: ["tiles", "context"]', create)

    def test_an_authors_agenda_text_uses_the_shared_editor(self):
        agenda_row = SHARED_JS.split("_agendaRow(item) {", 1)[1].split(
            "\n  _renderAgenda() {", 1,
        )[0]
        self.assertIn("SovereignUI.editableText", agenda_row)
        self.assertIn("routes.update", agenda_row)

    def test_relay_presence_refreshes_without_a_browser_reload(self):
        self.assertIn(
            "() => this.refreshSharingHeader()",
            SHARED_JS,
        )
        self.assertIn("_sharingRefreshTimer", SHARED_JS)

    def test_domain_logic_modules_do_not_depend_on_host_or_http_controllers(self):
        paths = [
            ROOT / "src" / "sovereign" / "protocol_explorer.py",
            *sorted(ROOT.glob("examples/*/src/*/logic.py")),
        ]
        self.assertGreaterEqual(len(paths), 2, paths)
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            } | {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            self.assertFalse(
                any(
                    name == "starlette"
                    or name.startswith("starlette.")
                    or name.endswith(".controller")
                    or name.endswith("_controller")
                    or name == "sovereign.application"
                    for name in imports
                ),
                str(path),
            )
            self.assertFalse(any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in {"build_routes", "create_application"}
                for node in tree.body
            ), str(path))
            self.assertFalse(any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(arg.arg == "runtime" for arg in node.args.args)
                for node in ast.walk(tree)
            ), str(path))


class ThemeTests(unittest.TestCase):
    """U4 shipped dark-only and left light mode as the open question. The
    switch is Core's, because the shell owns the chrome every application
    draws inside - an application choosing its own would put a dark dialog
    on a light page, which is the exact failure U4 was written about.
    """

    SHARED_CSS = files("sovereign.assets").joinpath("shared.css").read_text(
        encoding="utf-8",
    )

    def test_the_shell_defines_both_palettes(self):
        self.assertIn("--shell-surface: #161b22", self.SHARED_CSS)
        self.assertIn('[data-theme="light"]', self.SHARED_CSS)

    def test_light_moves_tokens_rather_than_individual_rules(self):
        # An application that reads the tokens gets light for free; one that
        # hardcodes a colour stays visibly wrong rather than half-working.
        # Redefining rules here instead would hide that distinction.
        light = self.SHARED_CSS.split('[data-theme="light"] .shell-dialog', 1)[1]
        light = light.split("}", 1)[0]
        for token in ("--shell-surface", "--shell-text", "--shell-border"):
            self.assertIn(token, light)

    def test_colour_scheme_moves_with_the_theme(self):
        # Native controls, scrollbars and form widgets follow color-scheme.
        # Pinning it to dark would render them dark inside a light page.
        self.assertIn(':root[data-theme="light"] { color-scheme: light; }', self.SHARED_CSS)
        self.assertIn(':root[data-theme="dark"] { color-scheme: dark; }', self.SHARED_CSS)

    def test_the_theme_is_applied_before_first_paint(self):
        # At parse time, not on DOMContentLoaded: otherwise the page renders
        # the default palette and corrects itself, which is a visible flash.
        self.assertIn("applyTheme(storedTheme())", SHARED_JS)
        # Checks for a listener registration, not the bare word - the comment
        # above the call names DOMContentLoaded to explain why it is avoided,
        # and matching prose would fail on the explanation itself.
        marker = SHARED_JS.index("applyTheme(storedTheme())")
        self.assertNotIn('addEventListener("DOMContentLoaded"', SHARED_JS[:marker])

    def test_an_unreadable_preference_falls_back_rather_than_throwing(self):
        # Private browsing and some embedded webviews throw on localStorage
        # access. A theme is not worth failing a page load over.
        stored = SHARED_JS.split("function storedTheme()", 1)[1].split("\n}", 1)[0]
        self.assertIn("catch", stored)
        self.assertIn("DEFAULT_THEME", stored)

    def test_the_preference_is_local_and_not_in_the_synced_profile(self):
        # A display choice for this machine. Putting it in the Core profile
        # would sync a cosmetic setting to every device and every peer.
        self.assertIn("localStorage", SHARED_JS)
        self.assertIn('THEME_STORAGE_KEY = "sovereign.theme"', SHARED_JS)

    def test_the_control_lives_in_the_profile_dialog(self):
        self.assertIn("shellThemeSelect", SHARED_JS)
        # It sits inside the profile dialog's markup, not the header bar.
        dialog = SHARED_JS.split("_ensureProfileDialog() {", 1)[1]
        dialog = dialog.split("document.body.append", 1)[0]
        self.assertIn("shellThemeSelect", dialog)

    def test_the_theme_applies_on_change_rather_than_on_save(self):
        # The dialog's Save writes the profile; the theme is not profile
        # data, so waiting for Save would both delay it and imply Cancel
        # reverts it. It applies on change and Cancel leaves it alone.
        self.assertIn('getElementById("shellThemeSelect").onchange', SHARED_JS)
        save = SHARED_JS.split("async _saveProfile(", 1)[1].split("\n  },", 1)[0]
        self.assertNotIn("shellThemeSelect", save)


class ShellLayoutTests(unittest.TestCase):
    SHARED_CSS = files("sovereign.assets").joinpath("shared.css").read_text(
        encoding="utf-8",
    )

    def test_the_bar_centres_the_topic_between_equal_flanks(self):
        """The middle is the anchor, so it is centred and does not drift.

        This was `1fr auto 1fr`, then `auto minmax(0, 1fr) auto` once the
        middle held everything the topic was attached to and had to grow.
        U7 moved that out into the switcher menu, so the middle shrinks to
        its contents again - and with both flanks taking equal free space
        the name sits at the optical centre and stays there as counts and
        people arrive.
        """
        bar = self.SHARED_CSS.split("display: grid;", 1)[1].split("}", 1)[0]
        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)", bar,
        )

    def test_an_object_is_drawn_from_its_kind_and_nothing_else(self):
        """The caller names the object; Core owns the drawing (U8).

        `entityBadge` took an `icon` argument, and S-Team passed a key emoji
        for a trusteeship, an open diamond for a role and a filled one for a
        membership - three drawings chosen at three call sites for objects
        Core already had names for. The argument is gone: one object has one
        glyph because there is nowhere else for a second one to come from.
        """
        badge = SHARED_JS.split("entityBadge(options = {}) {", 1)[1].split(
            "\n  disclosure(", 1,
        )[0]
        self.assertIn("entityGlyph(kind)", badge)
        self.assertNotIn("options.icon", badge)
        # Role, Seat and Members are the distinction S-Team's domain turns
        # on - an office, that office filled, and people irrespective of
        # office - so they are three drawings, not one.
        for kind in ("team", "role", "seat", "trustee", "membership"):
            self.assertIn(f"{kind}: ICON_", SHARED_JS)
        # A section may carry the mark of the kind it holds, from the same
        # table, so a heading and its contents cannot diverge.
        disclosure = SHARED_JS.split("disclosure(title, options = {}) {", 1)[1].split(
            "\n  },", 1,
        )[0]
        self.assertIn("options.glyph ? entityGlyph(options.glyph) : null", disclosure)

    def test_the_name_clears_the_shared_field_min_height(self):
        """`.ui-editable-text` floors at 34px, and min-height beats height.

        Setting a height on the title in the bar therefore did nothing: it
        rendered in a box a third taller than the row and out of line with
        the mark beside it. Anything the bar shrinks has to clear the shared
        primitive's `min-*` floors, not merely set its sizes.
        """
        title = self.SHARED_CSS.split(".shell-bar .shell-topic-title {", 1)[1].split(
            "}", 1,
        )[0]
        self.assertIn("min-height: 0", title)
        self.assertIn("line-height:", title)

    def test_a_reference_you_do_not_hold_reads_as_an_offer(self):
        # Dashed and dimmed, not red and not hidden: following it reaches
        # whatever a peer is already publishing, so it is an invitation.
        # U7 moved it out of the bar and into the dialog that manages what
        # this topic is attached to - taking one up is an act, not a
        # destination, and it belongs where the acts are.
        unheld = self.SHARED_CSS.split(".shell-link-row.unheld {", 1)[1].split(
            "}", 1,
        )[0]
        self.assertIn("border-style: dashed", unheld)
        self.assertIn("opacity", unheld)
        self.assertIn("Add to Cockpit", SHARED_JS)
        # The navigation row and its menu list only what you hold: both are
        # places to go, and taking a reference up is an act, not a
        # destination.
        related = SHARED_JS.split("_buildRelatedMenu(button) {", 1)[1].split(
            "\n  },", 1,
        )[0]
        self.assertIn("filter((link) => link.held)", related)
        self.assertIn("Link related…", related)

    def test_the_navigation_row_orders_destinations_by_range(self):
        """Nearest first, widest last, with a rule where the range changes.

        The row is the whole of U7's middle below the name: what this topic
        names, then everything you hold. Only the names shrink - every
        control after them is `flex: none`, so a long list truncates itself
        rather than pushing the Cockpit off the bar.
        """
        row = SHARED_JS.split("_renderTopicContext() {", 1)[1].split(
            "\n  _contextLink(link) {", 1,
        )[0]
        self.assertLess(
            row.index("shell-context-links"), row.index("shell-related-menu"),
        )
        self.assertLess(
            row.index("shell-related-menu"), row.index("shell-cockpit-btn"),
        )
        # The chevron is unconditional; the Cockpit is not, because an
        # installation may register no aggregator.
        self.assertIn('(app) => app.role === "aggregator"', row)
        # And an aggregator draws no row at all - it already shows every
        # topic, so a few of them on a line would be a second mesh.
        self.assertIn('if (current && current.role === "aggregator") return;', row)
        self.assertIn("if (!this._options.topicUuid || !this._topic()) return;", row)
        links = self.SHARED_CSS.split(".shell-context-links {", 1)[1].split("}", 1)[0]
        self.assertIn("min-width: 0", links)
        self.assertIn("overflow: hidden", links)
        # Hover brightens rather than emboldens: a weight change reflows the
        # row and drags everything right of it sideways.
        hover = self.SHARED_CSS.split(".shell-context-link:hover {", 1)[1].split("}", 1)[0]
        self.assertIn("color:", hover)
        self.assertNotIn("font-weight", hover)


class ShippedExampleAssetTests(unittest.TestCase):
    """The example's assets are held to the rules every application follows.

    These used to check S-Team, which shipped inside Core. It became a
    product and moved out, so they check the minimal example that replaced it.
    """

    def setUp(self):
        self.notes = files("sovereign_example_notes.assets").joinpath(
            "notes.html",
        ).read_text(encoding="utf-8")

    def test_example_assets_are_packaged(self):
        assets = files("sovereign_example_notes.assets")
        self.assertTrue(assets.joinpath("notes.html").is_file())
        self.assertTrue(assets.joinpath("notes.css").is_file())

    def test_example_delegates_topic_creation_to_the_shell(self):
        self.assertNotIn("onCreateTopic", self.notes)
        self.assertIn("SovereignShell.setTopicName", self.notes)

    def test_example_never_navigates_to_the_bare_root_with_a_query(self):
        # "/" serves whichever application is primary, so a root-relative link
        # lands somewhere that depends on host configuration.
        for number, line in enumerate(self.notes.splitlines(), start=1):
            for pattern in ('href = `/?', 'href="/?', "href='/?"):
                self.assertNotIn(pattern, line, f"notes.html:{number}")


if __name__ == "__main__":
    unittest.main()
