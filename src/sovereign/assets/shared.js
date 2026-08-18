/*
  Shared UI kit - loaded before each page's own inline <script>. Every page
  must provide:
    - <div id="toast" class="toast"></div>            (for showToast)
    - <dialog id="confirmModal"> with #confirmModalTitle, #confirmModalMessage,
      #confirmModalCancelBtn, #confirmModalConfirmBtn (for confirmAction)
  peerLabel() stays page-specific (each page's state shape differs) - these
  helpers just call the global peerLabel() the page itself defines.
*/

// Theme is a display preference for this machine, like the OS's own dark
// mode - deliberately not in the Core profile, which syncs to peers and
// would carry a cosmetic choice to every device you connect from.
const THEME_STORAGE_KEY = "sovereign.theme";
const THEMES = ["dark", "light"];
const DEFAULT_THEME = "dark";
// A snapshot is a document, not a medium: anything this size is somebody
// having chosen the wrong file, and reading it would freeze the tab first.
const SNAPSHOT_FILE_LIMIT = 50 * 1024 * 1024;

function storedTheme() {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.includes(value) ? value : DEFAULT_THEME;
  } catch (error) {
    // Private browsing and some embedded webviews throw on access rather
    // than returning null. A theme is not worth failing a page load over.
    return DEFAULT_THEME;
  }
}

function applyTheme(theme) {
  const resolved = THEMES.includes(theme) ? theme : DEFAULT_THEME;
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}

// Run at parse time, not on DOMContentLoaded: the attribute must be on
// <html> before first paint, or the page shows the default palette and then
// corrects itself - a flash that is worse than either theme on its own.
applyTheme(storedTheme());

const ICON_CLOSE = '<path d="M18 6 6 18"></path><path d="M6 6l12 12"></path>';
const ICON_CHEVRON_DOWN = '<path d="M6 9l6 6 6-6"></path>';
// A circle and eight ticks, not Feather's twenty-node gear: the bar renders
// this at 18px, where that path is a blob. U8.
const ICON_SETTINGS =
  '<circle cx="12" cy="12" r="3.2"></circle>' +
  '<path d="M12 3v2.4"></path><path d="M12 18.6V21"></path>' +
  '<path d="M3 12h2.4"></path><path d="M18.6 12H21"></path>' +
  '<path d="M5.6 5.6l1.7 1.7"></path><path d="M16.7 16.7l1.7 1.7"></path>' +
  '<path d="M18.4 5.6l-1.7 1.7"></path><path d="M7.3 16.7l-1.7 1.7"></path>';
const ICON_EXPAND =
  '<path d="M8 3H5a2 2 0 0 0-2 2v3"></path><path d="M21 8V5a2 2 0 0 0-2-2h-3"></path>' +
  '<path d="M3 16v3a2 2 0 0 0 2 2h3"></path><path d="M16 21h3a2 2 0 0 0 2-2v-3"></path>';
const ICON_COLLAPSE =
  '<path d="M8 3v3a2 2 0 0 1-2 2H3"></path><path d="M21 8h-3a2 2 0 0 1-2-2V3"></path>' +
  '<path d="M3 16h3a2 2 0 0 1 2 2v3"></path><path d="M16 21v-3a2 2 0 0 1 2-2h3"></path>';
const ICON_DELETE =
  '<path d="M4 7h16"></path><path d="M10 11v6"></path><path d="M14 11v6"></path>' +
  '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"></path>' +
  '<path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"></path>';
const ICON_SHARE =
  '<circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle>' +
  '<circle cx="18" cy="19" r="3"></circle>' +
  '<path d="M8.59 13.51 15.42 17.49"></path><path d="M15.41 6.51 8.59 10.49"></path>';

// The two controls the bar's left holds (U7). An ordered list of things to
// discuss, and changes moving between copies - each counting only the thing
// it is named for.
const ICON_AGENDA =
  '<circle cx="5" cy="7" r="1.1"></circle><circle cx="5" cy="12" r="1.1"></circle>' +
  '<circle cx="5" cy="17" r="1.1"></circle>' +
  '<path d="M9 7h10"></path><path d="M9 12h10"></path><path d="M9 17h6"></path>';
const ICON_CHANGES =
  '<path d="M4 9h13"></path><path d="M14 6l3 3-3 3"></path>' +
  '<path d="M20 15H7"></path><path d="M10 12l-3 3 3 3"></path>';
// Off my side, and reversible. Never the trash can, which destroys for
// everyone - see DESIGN_TOPIC_LINKS.md and U8.
const ICON_REMOVE =
  '<circle cx="12" cy="12" r="8.5"></circle><path d="M8.5 12h7"></path>';

function iconButton(svgInner, label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-btn";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">${svgInner}</svg>`;
  button.onclick = (event) => {
    event.stopPropagation();
    action();
  };
  return button;
}

// Reusable visual primitives. They deliberately stop short of prescribing an
// application's workflow: Core supplies the same disclosure, entity and add
// controls; each application decides where and when to use them.
let uiDisclosureSequence = 0;
const SovereignUI = Object.freeze({
  avatar(person = {}, options = {}) {
    const avatar = document.createElement("span");
    avatar.className = `ui-avatar ${options.className || ""}`.trim();
    avatar.dataset.owner = String(Boolean(options.owner));
    avatar.dataset.self = String(Boolean(options.self));
    const name = String(person.name || options.name || "?").trim() || "?";
    const picture = person.picture || options.picture || "";
    if (picture) {
      const image = document.createElement("img");
      image.src = picture;
      image.alt = "";
      avatar.append(image);
    } else {
      avatar.textContent = name.slice(0, 2).toUpperCase();
    }
    avatar.title = options.title || name;
    return avatar;
  },

  entityBadge(options = {}) {
    const interactive = Boolean(options.interactive);
    const badge = document.createElement(interactive ? "button" : "span");
    if (interactive) badge.type = "button";
    const kind = options.kind || "role";
    badge.className = [
      "ui-entity-badge",
      options.compact ? "is-compact" : "",
      options.className || "",
    ]
      .filter(Boolean)
      .join(" ");
    badge.dataset.entityKind = kind;
    if (options.status) badge.dataset.status = options.status;
    if (kind === "person") {
      badge.append(
        this.avatar(options.person || {}, {
          owner: options.owner,
          self: options.self,
          title: options.title,
        }),
      );
    } else {
      const icon = document.createElement("span");
      icon.className = "ui-entity-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = options.icon || (kind === "team" ? "▤" : "◇");
      badge.append(icon);
    }
    if (!options.compact && options.label) {
      const label = document.createElement("span");
      label.className = "ui-entity-label";
      label.textContent = options.label;
      badge.append(label);
    }
    if (options.title) badge.title = options.title;
    if (interactive && options.onClick) badge.onclick = options.onClick;
    return badge;
  },

  disclosure(title, options = {}) {
    const section = document.createElement(options.tag || "section");
    section.className = `ui-disclosure ${options.className || ""}`.trim();
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "ui-disclosure-toggle";
    const label = document.createElement("span");
    label.textContent = title;
    const chevron = document.createElement("span");
    chevron.className = "ui-disclosure-chevron";
    chevron.textContent = ">";
    chevron.setAttribute("aria-hidden", "true");
    const content = document.createElement("div");
    content.className = "ui-disclosure-content";
    const contentId = `ui-disclosure-${++uiDisclosureSequence}`;
    content.id = contentId;
    toggle.setAttribute("aria-controls", contentId);
    toggle.append(label, chevron);
    section.append(toggle, content);

    const setExpanded = (expanded, notify = false) => {
      const open = Boolean(expanded);
      section.dataset.expanded = String(open);
      toggle.setAttribute("aria-expanded", String(open));
      content.hidden = !open;
      if (notify && options.onToggle) options.onToggle(open);
    };
    toggle.onclick = () => setExpanded(section.dataset.expanded !== "true", true);
    setExpanded(Boolean(options.expanded));
    return { section, toggle, content, setExpanded };
  },

  editableText(options = {}) {
    const element = options.element || document.createElement(options.tag || "span");
    const existing = element._sovereignEditableText;
    if (existing) {
      existing.update(options);
      return element;
    }

    let settings = {};
    let original = "";
    let cancelled = false;
    let committing = false;
    const valueFromElement = () => String(element.innerText || "")
      .replace(/\r/g, "")
      .replace(/\n+$/, "")
      .trim();
    const show = (value) => {
      original = String(value ?? "");
      element.textContent = original;
      if (settings.titleFromValue) element.title = original;
    };
    const editable = () => (
      settings.editable !== false && typeof settings.onCommit === "function"
    );
    const begin = () => {
      if (!editable() || committing || element.isContentEditable) return;
      cancelled = false;
      element.contentEditable = "true";
      element.dataset.editing = "true";
      element.focus();
      const range = document.createRange();
      range.selectNodeContents(element);
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    };
    const update = (next = {}) => {
      settings = {...settings, ...next};
      element.classList.add("ui-editable-text");
      if (settings.className) element.classList.add(settings.className);
      element.dataset.multiline = String(Boolean(settings.multiline));
      element.dataset.editable = String(editable());
      element.dataset.placeholder = String(settings.placeholder || "");
      element.setAttribute(
        "aria-label",
        settings.ariaLabel || settings.placeholder || "Editable text",
      );
      if (editable()) element.tabIndex = 0;
      else element.removeAttribute("tabindex");
      if (
        Object.prototype.hasOwnProperty.call(next, "value")
        && !element.isContentEditable
        && document.activeElement !== element
      ) {
        show(next.value);
      }
    };

    element.onclick = begin;
    element.onkeydown = (event) => {
      if (!element.isContentEditable) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          begin();
        }
        return;
      }
      if (event.key === "Enter" && (!settings.multiline || !event.shiftKey)) {
        event.preventDefault();
        element.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelled = true;
        element.textContent = original;
        element.contentEditable = "false";
        element.blur();
      }
    };
    element.onpaste = (event) => {
      if (!element.isContentEditable) return;
      event.preventDefault();
      const text = event.clipboardData?.getData("text/plain") || "";
      document.execCommand("insertText", false, text);
    };
    element.onblur = async () => {
      if (!element.isContentEditable && !element.dataset.editing) return;
      element.contentEditable = "false";
      delete element.dataset.editing;
      if (cancelled) {
        cancelled = false;
        return;
      }
      const value = valueFromElement();
      if ((!value && !settings.allowEmpty) || value === original) {
        element.textContent = original;
        return;
      }
      committing = true;
      element.dataset.busy = "true";
      try {
        await settings.onCommit(value);
        show(value);
        if (settings.onChanged) await settings.onChanged(value);
      } catch (error) {
        element.textContent = original;
        if (settings.onError) settings.onError(error);
        else showToast(error.message, true);
      } finally {
        committing = false;
        delete element.dataset.busy;
      }
    };

    element._sovereignEditableText = { update };
    update(options);
    if (!Object.prototype.hasOwnProperty.call(options, "value")) {
      show(element.textContent || "");
    }
    return element;
  },

  reorderHandle(options = {}) {
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = `ui-reorder-handle ${options.className || ""}`.trim();
    handle.textContent = options.text || "\u283f";
    const label = options.label || "Reorder item";
    handle.title = label;
    handle.setAttribute("aria-label", label);
    return handle;
  },

  // Reorder direct children without knowing what they contain or how an
  // application persists them. The list owns pointer/keyboard behaviour and
  // the optimistic DOM move; the application supplies only identity and save.
  reorderableList(options = {}) {
    const container = options.container;
    if (!container) throw new Error("reorderableList requires a container");
    const existing = container._sovereignReorderableList;
    if (existing) {
      existing.update(options);
      return existing;
    }

    let settings = {};
    let source = null;
    let placement = null;
    let committing = false;
    const handles = () => settings.handleSelector || ".ui-reorder-handle";
    const items = () => [...container.children].filter((item) =>
      item.matches(settings.itemSelector || "[data-reorder-id]"),
    );
    const idOf = (item) => String(
      settings.getId ? settings.getId(item) : item.dataset.reorderId || "",
    );
    const itemFor = (node) => {
      let item = node;
      while (item && item.parentElement !== container) item = item.parentElement;
      return item && items().includes(item) ? item : null;
    };
    const itemForHandle = (handle) => {
      const item = itemFor(handle);
      const owner = handle.closest("[data-reorder-id]");
      return item && owner?.dataset.reorderId === idOf(item) ? item : null;
    };
    const clearPlacement = () => {
      for (const item of items()) {
        item.classList.remove("ui-drop-before", "ui-drop-after");
      }
      placement = null;
    };
    const finishInteraction = () => {
      clearPlacement();
      source?.classList.remove("ui-reordering");
      source = null;
      if (!committing) delete container.dataset.reordering;
    };
    const targetAt = (clientX, clientY) => {
      clearPlacement();
      const target = itemFor(document.elementFromPoint(clientX, clientY));
      if (!target || target === source) return null;
      const bounds = target.getBoundingClientRect();
      const horizontal = settings.axis === "horizontal";
      const after = horizontal
        ? clientX > bounds.left + bounds.width / 2
        : clientY > bounds.top + bounds.height / 2;
      target.classList.add(after ? "ui-drop-after" : "ui-drop-before");
      placement = {target, after};
      return placement;
    };
    const commit = async (item, index) => {
      const before = items();
      const fromIndex = before.indexOf(item);
      if (fromIndex < 0 || index === fromIndex || committing) return;
      const originalNext = item.nextSibling;
      const without = before.filter((entry) => entry !== item);
      const reference = without[index]
        || without[without.length - 1]?.nextSibling
        || null;
      container.insertBefore(item, reference);
      committing = true;
      container.dataset.reordering = "true";
      item.dataset.reorderBusy = "true";
      let saved = false;
      try {
        await settings.onMove?.({
          id: idOf(item), index, fromIndex, item,
        });
        saved = true;
        delete container.dataset.reordering;
        if (settings.onChanged) await settings.onChanged();
      } catch (error) {
        if (!saved) container.insertBefore(item, originalNext);
        if (settings.onError) settings.onError(error);
        else showToast(error.message, true);
      } finally {
        committing = false;
        delete item.dataset.reorderBusy;
        delete container.dataset.reordering;
      }
    };
    const moveFromPlacement = async () => {
      if (!source || !placement) {
        finishInteraction();
        return;
      }
      const item = source;
      const remaining = items().filter((entry) => entry !== item);
      let index = remaining.indexOf(placement.target);
      if (index < 0) {
        finishInteraction();
        return;
      }
      if (placement.after) index += 1;
      finishInteraction();
      await commit(item, index);
    };
    const onMouseDown = (event) => {
      const handle = event.target.closest(handles());
      if (!handle || !container.contains(handle) || event.button !== 0 || committing) return;
      const item = itemForHandle(handle);
      if (!item || !idOf(item)) return;
      event.preventDefault();
      event.stopPropagation();
      source = item;
      source.classList.add("ui-reordering");
      container.dataset.reordering = "true";
      const move = (moveEvent) => targetAt(moveEvent.clientX, moveEvent.clientY);
      const up = async (upEvent) => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        targetAt(upEvent.clientX, upEvent.clientY);
        await moveFromPlacement();
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    };
    const onKeyDown = async (event) => {
      const handle = event.target.closest(handles());
      if (!handle || !container.contains(handle) || committing) return;
      const item = itemForHandle(handle);
      if (!item) return;
      const ordered = items();
      const fromIndex = ordered.indexOf(item);
      const previous = settings.axis === "horizontal" ? "ArrowLeft" : "ArrowUp";
      const next = settings.axis === "horizontal" ? "ArrowRight" : "ArrowDown";
      if (event.key !== previous && event.key !== next) return;
      const index = fromIndex + (event.key === previous ? -1 : 1);
      if (index < 0 || index >= ordered.length) return;
      event.preventDefault();
      event.stopPropagation();
      await commit(item, index);
    };
    const onClick = (event) => {
      const handle = event.target.closest(handles());
      if (!handle || !itemForHandle(handle)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    const refresh = () => {
      container.classList.add("ui-reorderable-list");
      container.dataset.reorderAxis = settings.axis === "horizontal" ? "horizontal" : "vertical";
      const ordered = items();
      for (const item of ordered) item.classList.add("ui-reorderable-item");
      for (const handle of container.querySelectorAll(handles())) {
        const item = itemForHandle(handle);
        if (!item) continue;
        handle.hidden = ordered.length < 2;
        handle.setAttribute("aria-keyshortcuts",
          settings.axis === "horizontal" ? "ArrowLeft ArrowRight" : "ArrowUp ArrowDown");
      }
    };
    const update = (next = {}) => {
      settings = {...settings, ...next};
      refresh();
    };

    container.addEventListener("mousedown", onMouseDown);
    container.addEventListener("keydown", onKeyDown);
    container.addEventListener("click", onClick);
    const control = {update, refresh};
    container._sovereignReorderableList = control;
    update(options);
    return control;
  },

  addComposer(options = {}) {
    const noun = String(options.noun || "item").trim();
    const control = document.createElement("div");
    control.className = `ui-add-control ${options.className || ""}`.trim();
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ui-button ui-button-small ui-add-trigger";
    trigger.textContent = options.triggerLabel || `+ Add ${noun}`;
    const form = document.createElement("form");
    form.className = "ui-inline-composer";
    form.hidden = true;
    const input = document.createElement("input");
    input.className = "ui-text-field";
    input.placeholder = options.placeholder || `${noun[0]?.toUpperCase() || ""}${noun.slice(1)}`;
    input.setAttribute("aria-label", options.inputLabel || input.placeholder);
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "ui-button ui-button-primary ui-button-small";
    submit.textContent = options.submitLabel || "Add";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ui-button ui-button-small";
    cancel.textContent = "Cancel";
    form.append(input, submit, cancel);
    const formHost = options.formHost || control;
    if (formHost !== control) {
      formHost.classList.add("ui-add-form-host");
      formHost.hidden = true;
      control.append(trigger);
      formHost.append(form);
    } else {
      control.append(trigger, form);
    }

    const close = () => {
      form.hidden = true;
      if (formHost !== control) formHost.hidden = true;
      trigger.hidden = false;
      input.value = "";
    };
    const open = () => {
      trigger.hidden = true;
      if (formHost !== control) formHost.hidden = false;
      form.hidden = false;
      input.focus();
    };
    trigger.onclick = open;
    cancel.onclick = close;
    input.onkeydown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    form.onsubmit = async (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value || !options.onSubmit) return;
      submit.disabled = true;
      cancel.disabled = true;
      try {
        await options.onSubmit(value);
        close();
      } catch (error) {
        if (options.onError) options.onError(error);
      } finally {
        submit.disabled = false;
        cancel.disabled = false;
      }
    };
    return control;
  },

  // One closed presentation for native selects. The transparent native
  // control covers it, so opening, selection, validation and keyboard use
  // remain the browser's while the value and chevron look the same everywhere.
  selectControl(select, options = {}) {
    if (!select) throw new Error("selectControl requires a select element");
    let api = select._sovereignSelectControl;
    if (!api) {
      const control = document.createElement("span");
      control.className = "ui-select-control";
      const value = document.createElement("span");
      value.className = "ui-select-value";
      value.setAttribute("aria-hidden", "true");
      const toggle = document.createElement("span");
      toggle.className = "ui-select-toggle";
      toggle.setAttribute("aria-hidden", "true");
      toggle.innerHTML = (
        `<svg viewBox="0 0 24 24" class="icon-svg">${ICON_CHEVRON_DOWN}</svg>`
      );
      if (select.parentNode) select.replaceWith(control);
      select.classList.add("ui-select", "ui-select-native");
      control.append(value, toggle, select);
      const update = () => {
        const selected = select.selectedOptions[0];
        value.textContent = selected?.textContent || "";
        value.title = selected?.textContent || "";
        control.dataset.disabled = String(select.disabled);
        control.dataset.busy = String(select.getAttribute("aria-busy") === "true");
      };
      api = {control, value, toggle, update};
      select._sovereignSelectControl = api;
      select.addEventListener("change", () => {
        update();
        // Application handlers sometimes reset action-selects to their
        // placeholder. They run after this listener, so reflect that reset.
        queueMicrotask(update);
      });
      new MutationObserver(update).observe(select, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }
    api.control.dataset.variant = options.variant || api.control.dataset.variant || "field";
    if (options.controlClass) {
      api.control.classList.add(...options.controlClass.split(/\s+/).filter(Boolean));
    }
    api.update();
    return api;
  },

  refreshSelect(select) {
    select?._sovereignSelectControl?.update();
    return select;
  },

  // Native selection controls are intentionally distinct from action menus.
  // This helper owns their repeated option population and states.
  selectOptions(select, items = [], options = {}) {
    if (!select) throw new Error("selectOptions requires a select element");
    const priorValue = select.value;
    const hasRequestedValue = Object.prototype.hasOwnProperty.call(options, "value");
    const requestedValue = hasRequestedValue
      ? String(options.value ?? "")
      : priorValue;
    select.classList.add("ui-select");
    select.replaceChildren();

    const appendOption = (host, item) => {
      const normalized = Array.isArray(item)
        ? {value: item[0], label: item[1]}
        : (typeof item === "object" && item !== null
          ? item
          : {value: item, label: item});
      const option = document.createElement("option");
      option.value = String(normalized.value ?? "");
      option.textContent = String(normalized.label ?? normalized.value ?? "");
      option.disabled = Boolean(normalized.disabled);
      if (normalized.dataset) {
        for (const [key, value] of Object.entries(normalized.dataset)) {
          option.dataset[key] = String(value ?? "");
        }
      }
      host.append(option);
      return option;
    };

    if (options.loading) {
      appendOption(select, {value: "", label: options.loadingLabel || "Loading…"});
      select.disabled = true;
      select.setAttribute("aria-busy", "true");
      this.selectControl(select, options).update();
      return select;
    }
    select.removeAttribute("aria-busy");
    select.disabled = Boolean(options.disabled);

    if (options.placeholder) {
      appendOption(select, {
        value: "",
        label: options.placeholder,
        disabled: options.placeholderDisabled !== false,
      });
    } else if (Object.prototype.hasOwnProperty.call(options, "emptyLabel")) {
      appendOption(select, {value: "", label: options.emptyLabel});
    }

    const groups = new Map();
    for (const item of items) {
      const groupName = !Array.isArray(item) && item && typeof item === "object"
        ? item.group
        : "";
      if (!groupName) {
        appendOption(select, item);
        continue;
      }
      let group = groups.get(groupName);
      if (!group) {
        group = document.createElement("optgroup");
        group.label = groupName;
        groups.set(groupName, group);
        select.append(group);
      }
      appendOption(group, item);
    }
    if (
      hasRequestedValue
      || [...select.options].some((option) => option.value === requestedValue)
    ) select.value = requestedValue;
    this.selectControl(select, options).update();
    return select;
  },

  selectionControl(options = {}) {
    const select = options.select || document.createElement("select");
    if (options.id) select.id = options.id;
    if (options.name) select.name = options.name;
    if (Object.prototype.hasOwnProperty.call(options, "required")) {
      select.required = Boolean(options.required);
    }
    if (options.ariaLabel) select.setAttribute("aria-label", options.ariaLabel);
    if (options.title) select.title = options.title;
    if (options.selectClass) {
      select.classList.add(...options.selectClass.split(/\s+/).filter(Boolean));
    }
    this.selectOptions(select, options.items || [], options);
    if (options.onChange) select.addEventListener("change", options.onChange);
    const control = select._sovereignSelectControl.control;
    return {
      select,
      input: select,
      control,
      setOptions: (items, state = {}) => this.selectOptions(select, items, state),
    };
  },

  selectionField(options = {}) {
    const field = document.createElement("label");
    field.className = `ui-selection-field ${options.className || ""}`.trim();
    const caption = document.createElement("span");
    caption.className = "ui-field-label";
    caption.textContent = options.label || "";
    const selection = this.selectionControl(options);
    const {select, control} = selection;
    field.append(caption, control);

    const describedBy = [];
    const addMessage = (className, text, suffix) => {
      if (!text) return null;
      const message = document.createElement("small");
      message.className = className;
      message.textContent = text;
      if (select.id) {
        message.id = `${select.id}-${suffix}`;
        describedBy.push(message.id);
      }
      field.append(message);
      return message;
    };
    const help = addMessage("ui-field-help", options.help, "help");
    const error = addMessage("ui-field-error", options.error, "error");
    if (describedBy.length) select.setAttribute("aria-describedby", describedBy.join(" "));
    if (error) select.setAttribute("aria-invalid", "true");
    return {
      ...selection,
      field,
      label: field,
      help,
      error,
    };
  },

  // Action menus choose an operation, not a value. They share one popup so
  // dismissal, positioning, focus and keyboard navigation are fixed once.
  actionMenu(options = {}) {
    const button = options.button || document.createElement("button");
    button.type = "button";
    if (options.label) button.textContent = options.label;
    if (options.className) button.classList.add(...options.className.split(/\s+/).filter(Boolean));
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    const items = () => typeof options.items === "function" ? options.items() : options.items || [];
    const open = () => openActionMenu(button, items(), options);
    const close = (restoreFocus = false) => closeActionMenu(restoreFocus);
    button.onclick = (event) => {
      event.stopPropagation();
      if (uiActionMenuAnchor === button && !uiActionMenu.hidden) close();
      else open();
    };
    return {button, open, close};
  },

  // One shape for "there is a difference here, what do you want to do about
  // it", wherever it appears. A single available reaction is a button that
  // names the act, because a button reading "React" hides an answer the
  // reader could have given in one click; several become a menu, because a
  // button cannot name four acts at once.
  //
  // Which nodes are offered a control stays with the application - auto-adopt
  // rules and container-only divergences are its judgement, not Core's. This
  // decides only what the control looks like once one is called for, and
  // returns null when the transition leaves nothing to react to.
  reactionControl(options = {}) {
    const choices = reactionChoices(options.info);
    if (!choices.length || !options.onReact) return null;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `ui-react-button ${options.className || ""}`.trim();
    button.title = options.title || transitionLabel(options.info);
    const react = async (choice) => {
      button.disabled = true;
      try {
        await options.onReact(choice);
      } finally {
        // The reaction usually rebuilds the tree this button is in, so it is
        // gone before this runs. Re-enabling matters for the case where it
        // failed and the button is still on screen.
        button.disabled = false;
      }
    };
    if (choices.length === 1) {
      const [only] = choices;
      button.textContent = only.label;
      button.onclick = (event) => {
        event.stopPropagation();
        react(only);
      };
      return button;
    }
    button.textContent = options.menuLabel || "React";
    button.setAttribute("aria-label", "React to differences");
    this.actionMenu({
      button,
      items: choices.map((choice) => ({
        label: choice.label,
        onSelect: () => react(choice),
      })),
    });
    return button;
  },
});

let toastTimer = null;
function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", !!isError);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.textContent = "";
  }, 3500);
}

function confirmAction(title, message, action) {
  const modal = document.getElementById("confirmModal");
  if (!modal) {
    // Loud, and naming what is missing. A page that asks to confirm and has
    // nowhere to do it is a mistake in that page, not something to paper over
    // by running the action unconfirmed.
    throw new Error("confirmAction() needs the shared confirm-modal markup on this page");
  }
  document.getElementById("confirmModalTitle").textContent = title;
  document.getElementById("confirmModalMessage").textContent = message;
  document.getElementById("confirmModalConfirmBtn").onclick = async () => {
    modal.close();
    await action();
  };
  modal.showModal();
}

// Carrying the confirm modal is an application's choice - S-Flow uses no
// confirmations and has none. Binding this unconditionally at load time made
// that an unwritten requirement: the assignment threw on a page without the
// element, so the rest of this file never ran, `SovereignShell` was never
// defined, and every application page missing the markup failed to render
// with nothing in the console to say why.
const sharedConfirmCancelBtn = document.getElementById("confirmModalCancelBtn");
if (sharedConfirmCancelBtn) {
  sharedConfirmCancelBtn.onclick = () => document.getElementById("confirmModal").close();
}

function dedupe(items) {
  return [...new Set(items)];
}

// Pages that model people define peerLabel(); ones that do not - a minimal
// application, or any page before its first load - must still be able to
// render a transition rather than throwing a ReferenceError.
function safePeerLabel(addr) {
  if (typeof peerLabel === "function") return peerLabel(addr);
  return String(addr || "a peer");
}

// Who authored the change being described - "me" when this client did.
// Distinct from transitionActorLabel, which names the peer on the other end
// of the comparison: a rollback target is "my previous version held by
// <peer>", so that wording needs the counterpart even when I am the author.
const LOCALLY_AUTHORED_TYPES = ["local_made_changes", "peer_missing_node"];

function transitionAuthorLabel(info) {
  if (LOCALLY_AUTHORED_TYPES.includes(info?.type)) return "me";
  return transitionActorLabel(info);
}

// The one sentence both sides compose from the same change record, each from
// their own end: "Card deleted by me" and "Card deleted by Ana" are the same
// fact, and neither reads as an accusation of divergence. The author sits
// between the act and its detail, so a modification reads "Card modified by
// me: Ana added" rather than leaving "by me" dangling off the detail.
function authoredPhrase(info, author) {
  const changes = (info?.events || [info]).flatMap((event) => event?.changes || []);
  const acts = dedupe(changes.map((c) => c.authored_act).filter(Boolean));
  if (!acts.length) return "";
  const node = changes.find((c) => c.node_label)?.node_label || "Item";
  const details = dedupe(changes.map((c) => c.authored_detail).filter(Boolean));
  // A suffix belongs to the verb and follows the author directly; a detail
  // is a list of what changed and sits behind a colon. "Card moved by me to
  // Doing" reads, "Card moved by me: to Doing" does not.
  const suffixes = dedupe(changes.map((c) => c.authored_suffix).filter(Boolean));
  const head = [`${node} ${acts.join(" and ")} by ${author}`, ...suffixes].join(" ");
  return details.length ? `${head}: ${details.join("; ")}` : head;
}

function transitionActorLabel(info) {
  const sourceType = info.type;
  const originDescribesIncomingRevision = [
    "peer_made_changes",
    "local_missing_node",
    "divergence",
  ].includes(sourceType);
  if (
    originDescribesIncomingRevision &&
    info.origin_identity &&
    typeof userForParticipant === "function"
  ) {
    const user = userForParticipant(info.origin_identity);
    if (user && user.name && user.name !== "?") return user.name;
  }
  return safePeerLabel(info.peer_addr);
}

// A difference still in flight reads the same whatever its relation is: the
// peer has not had the chance to answer yet. Only reached when a change
// carries no describable act - otherwise the sentence names the act instead.
function transitionKey(event) {
  return event?.stage === "in_flight" ? "in_flight" : event?.type;
}

// Where a difference stands, written from the reader's own position. Both
// screens describe one fact, each naming its own obligation: the author is
// told nobody has answered yet, the recipient that the decision is theirs.
// Everyone this difference is still waiting on, not just whichever peer
// happened to be named first. One change against three clients is one
// situation, so the events merge - and the merged event carries every peer
// in delivery_peer_addrs while peer_addr keeps only one of them.
function transitionPeerLabels(info) {
  const addrs = info?.delivery_peer_addrs?.length ? info.delivery_peer_addrs : [info?.peer_addr];
  return dedupe(addrs.filter(Boolean).map(safePeerLabel)).join(", ") || transitionActorLabel(info);
}

function transitionStanding(info) {
  const peers = transitionPeerLabels(info);
  return (
    {
      in_flight: `not yet seen by ${peers}`,
      awaiting_peer: `not yet adopted by ${peers}`,
      awaiting_me: "not yet adopted by me",
      conflict: `also changed by ${transitionActorLabel(info)}`,
    }[info?.stage] || ""
  );
}

// A conflict is the one case with two authors, so it is the one case the
// act clause cannot describe on its own: naming a single side then adding
// "also changed by them" repeats that side and never mentions mine.
function conflictPhrase(info) {
  const changes = info?.changes || [];
  const acts = dedupe(changes.map((c) => c.authored_act).filter(Boolean));
  if (!acts.length) return "";
  const node = changes.find((c) => c.node_label)?.node_label || "Item";
  const join = (key) => {
    const parts = dedupe(changes.map((c) => c[key]).filter(Boolean));
    return parts.length ? ` ${parts.join(" ")}` : "";
  };
  // authored_suffix describes the peer's side here, because a divergence is
  // not locally authored; counter_suffix is mine.
  return (
    `${node} ${acts.join(" and ")} by me${join("counter_suffix")}` +
    `, and by ${transitionActorLabel(info)}${join("authored_suffix")}`
  );
}

// One difference as one sentence: what happened, who did it, where it stands.
function transitionSentence(info) {
  const standing = transitionStanding(info);
  if (info?.stage === "conflict") {
    const both = conflictPhrase(info);
    if (both) return both;
  }
  const authored = authoredPhrase(info, transitionAuthorLabel(info));
  if (authored) return standing ? `${authored}, ${standing}` : authored;
  const peer = transitionActorLabel(info);
  const fallback =
    {
      in_agreement: "No open changes",
      peer_made_changes: `Changes from ${peer}`,
      local_made_changes: `My changes not in ${peer}`,
      local_missing_node: `Only in ${peer}`,
      peer_missing_node: `Missing in ${peer}`,
      divergence: `Diverged from ${peer}`,
      in_flight: `Waiting for ${peer} to process this change`,
    }[transitionKey(info)] || "Difference";
  return standing ? `${fallback}, ${standing}` : fallback;
}

function transitionLabel(info) {
  const events = (info.events || [info]).filter((event) => event.stage !== "settled");
  // Deliberately no second, peer-relative line. Saying "Card created by me"
  // and then "B: card exists only in your version" states one fact twice,
  // the second time from the far end - which is what made the old tooltips
  // read as though the peer had done something.
  if (events.length > 1) {
    return dedupe(events.map(transitionSentence)).join("\n");
  }
  return transitionSentence(info);
}

// The same act named for a button. Rollback is offered to the author and
// adopt to whoever has to decide, so each is phrased from that side.
function transitionReactionLabel(event) {
  const changes = event?.changes || [];
  const nouns = dedupe(changes.map((c) => c.authored_noun).filter(Boolean));
  const node = changes.find((c) => c.node_label)?.node_label || "item";
  const what = `${node.toLowerCase()} ${nouns.join(" and ") || "change"}`;
  // Worded by who authored the change, not by which endpoint settles it.
  // Those differ: undoing my own edit is served by adopting the version a
  // peer still holds, which is a rollback to me however it is implemented,
  // and "Adopt card move from me" describes the mechanism at the reader.
  return LOCALLY_AUTHORED_TYPES.includes(event?.type) || event?.reaction === "rollback"
    ? `Take back my ${what}`
    : `Adopt ${what} from ${transitionAuthorLabel(event)}`;
}

// Every act available on one node, one per contributing peer. A transition
// carries the peers that differ in `events`; an application whose grouping
// keeps only the leading event has the record itself as its single entry.
//
// `absent` is read from the event type rather than from whether the node can
// be found in a cached peer tree: absence tells the server to delete the
// local node, and a peer root that has not arrived yet is not the same fact
// as a peer that does not have the node.
function reactionChoices(info) {
  const events = (info?.events || (info ? [info] : [])).filter(
    (event) =>
      event &&
      event.type &&
      event.type !== "in_agreement" &&
      !["settled", "in_flight"].includes(event.stage) &&
      event.peer_addr,
  );
  return events.map((event) => ({
    label: transitionReactionLabel(event),
    action: event.reaction || "adopt",
    peerAddr: event.peer_addr,
    absent: event.type === "peer_missing_node",
    event,
  }));
}

// One body-level popup serves every action menu. Applications provide only
// the button and operations; Core owns accessibility and interaction details.
let uiActionMenu = null;
let uiActionMenuAnchor = null;

function closeActionMenu(restoreFocus = false) {
  if (!uiActionMenu) return;
  uiActionMenu.hidden = true;
  uiActionMenu.replaceChildren();
  uiActionMenuAnchor?.setAttribute("aria-expanded", "false");
  if (restoreFocus) uiActionMenuAnchor?.focus();
  uiActionMenuAnchor = null;
}

function actionMenuButtons() {
  return uiActionMenu
    ? [...uiActionMenu.querySelectorAll('[role^="menuitem"]')].filter(
      (item) => !item.disabled,
    )
    : [];
}

function ensureActionMenu() {
  if (uiActionMenu) return uiActionMenu;
  uiActionMenu = document.createElement("div");
  uiActionMenu.id = "sovereignActionMenu";
  uiActionMenu.className = "ui-action-menu";
  uiActionMenu.setAttribute("role", "menu");
  uiActionMenu.hidden = true;
  document.body.append(uiActionMenu);
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (
      !target?.closest(".ui-action-menu")
      && !uiActionMenuAnchor?.contains(target)
    ) closeActionMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (uiActionMenu.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeActionMenu(true);
      return;
    }
    if (event.key === "Tab") {
      closeActionMenu();
      return;
    }
    const buttons = actionMenuButtons();
    if (!buttons.length) return;
    const current = buttons.indexOf(document.activeElement);
    let next = null;
    if (event.key === "ArrowDown") next = buttons[(current + 1) % buttons.length];
    else if (event.key === "ArrowUp") {
      next = buttons[(current - 1 + buttons.length) % buttons.length];
    } else if (event.key === "Home") next = buttons[0];
    else if (event.key === "End") next = buttons[buttons.length - 1];
    if (next) {
      event.preventDefault();
      next.focus();
    }
  });
  window.addEventListener("resize", () => closeActionMenu());
  window.addEventListener("scroll", () => closeActionMenu(), true);
  return uiActionMenu;
}

function openActionMenu(anchor, items = [], options = {}) {
  const menu = ensureActionMenu();
  const choices = items.filter(Boolean);
  if (!choices.length) {
    closeActionMenu();
    if (options.emptyMessage) showToast(options.emptyMessage, true);
    return;
  }
  closeActionMenu();
  uiActionMenuAnchor = anchor;
  anchor.setAttribute("aria-controls", menu.id);
  anchor.setAttribute("aria-expanded", "true");
  menu.style.minWidth = options.minWidth || "";
  for (const item of choices) {
    if (item.separator) {
      const separator = document.createElement("div");
      separator.className = "ui-action-menu-separator";
      separator.setAttribute("role", "separator");
      menu.append(separator);
      continue;
    }
    // Names a group without being one of its choices: not focusable, and
    // skipped by the arrow keys, which walk buttons only.
    if (item.heading) {
      const heading = document.createElement("div");
      heading.className = "ui-action-menu-heading";
      heading.setAttribute("role", "presentation");
      heading.textContent = item.heading;
      menu.append(heading);
      continue;
    }
    const choice = document.createElement("button");
    choice.type = "button";
    choice.className = `ui-action-menu-option ${item.danger ? "is-danger" : ""}`.trim();
    choice.setAttribute("role", item.role || "menuitem");
    if (item.checked !== undefined) {
      choice.setAttribute("aria-checked", String(Boolean(item.checked)));
    }
    choice.textContent = item.label;
    choice.disabled = Boolean(item.disabled);
    choice.onclick = async (event) => {
      event.stopPropagation();
      closeActionMenu();
      try {
        await (item.onSelect || item.action)?.(item);
      } catch (error) {
        if (options.onError) options.onError(error);
        else showToast(error.message, true);
      }
    };
    menu.append(choice);
  }
  menu.hidden = false;
  const rect = anchor.getBoundingClientRect();
  const margin = 8;
  const alignedLeft = options.align === "end"
    ? rect.right - menu.offsetWidth
    : rect.left;
  menu.style.left = `${Math.max(
    margin,
    Math.min(alignedLeft, window.innerWidth - menu.offsetWidth - margin),
  )}px`;
  let top = rect.bottom + 4;
  if (top + menu.offsetHeight > window.innerHeight - margin) {
    top = Math.max(margin, rect.top - menu.offsetHeight - 4);
  }
  menu.style.top = `${top}px`;
  if (options.focus !== false) actionMenuButtons()[0]?.focus();
}

/*
  Sovereign host shell - the collaboration surface every application shares.

  Core owns this because everything in it is a Core concept: identities,
  peers, channels, connect tokens, and mailbox targets. An application that
  built its own would be reimplementing Core's vocabulary, and the copies
  would drift - which is exactly how a renamed token field broke pasting in
  two applications at once.

  Navigation is host-driven. The shell asks GET /api/core/applications, so
  no application ever names another application's identifier or URL, and
  deactivating one removes a link instead of breaking it.

  Mount with SovereignShell.mount({...}); the shell injects its own dialogs,
  so a page needs no markup contract beyond the container it passes in.
*/
const SovereignShell = {
  _applications: null,
  _dialogs: false,
  _options: {},
  _headerSharingTopic: "",
  _headerSharingPendingTopic: "",

  async applications() {
    if (this._applications) return this._applications;
    try {
      const response = await fetch("/api/core/applications");
      const payload = await response.json();
      this._applications = payload.applications || [];
    } catch (error) {
      this._applications = [];
    }
    return this._applications;
  },

  async _post(path, body, options = {}) {
    return SovereignApi.request(path, body || {}, options);
  },

  // options: { container, applicationId, topicUuid(), state(), onChanged(),
  //            describeNode(uuid), revealNode(uuid), reactNode(uuid, choice),
  //            canReact(uuid) }
  //
  // reactNode carries out one reaction chosen from a divergence row. The
  // shell decides how the choice is offered - Core owns that vocabulary -
  // and the application performs it, because only it knows its own routes.
  async mount(options) {
    this._options = options;
    this._buildHeader(options.container, options);
    const applications = await this.applications();
    const current = applications.find((app) => app.application_id === options.applicationId);
    if (current) {
      // The application you are in is named, not linked to itself.
      document.getElementById("shellAppName").textContent = current.display_name;
      if (current.icon) {
        const mark = document.getElementById("shellAppMark");
        mark.textContent = "";
        mark.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">' + current.icon + "</svg>";
      }
    }
    // The Cockpit entry on the navigation row is composed from what the host
    // reports, so the row cannot be drawn until that has arrived.
    this._renderTopicContext();
    this.refresh();
    this.refreshAvatar();
    if (!this._sharingRefreshTimer) {
      // Relay liveness changes without an application mutation. Keep the
      // header current in desktop WebViews, where there is no browser reload
      // button to force a fresh presence query.
      this._sharingRefreshTimer = window.setInterval(() => this.refreshSharingHeader(), 3000);
    }
  },

  refresh() {
    this.refreshDisagreements();
    this.refreshSharingHeader();
    this.refreshCollaborationPane();
    this.refreshSiblingAlarms();
  },

  // ---- sibling alarms ------------------------------------------------
  //
  // Another client of this same user published something this client's own
  // unpublished work was not built on. Nothing syncs on that topic until the
  // person answers, and the answer is theirs: no automation, and no export -
  // they copy the storage file if they want to keep this side.
  // See DESIGN_MULTI_CLIENT_PAIRING.md 4.4.

  async refreshSiblingAlarms() {
    try {
      const response = await fetch("/api/core/siblings/alarms");
      if (!response.ok) return;
      const payload = await response.json();
      this._renderSiblingAlarms(payload.alarms || [], payload.storage_file || "");
    } catch (error) {
      // A failed poll is not an alarm. Leave whatever is already shown.
    }
  },

  _ensureSiblingAlarmBar() {
    let bar = document.getElementById("shellSiblingAlarms");
    if (bar) return bar;
    bar = document.createElement("div");
    bar.id = "shellSiblingAlarms";
    bar.className = "shell-sibling-alarms";
    bar.hidden = true;
    document.body.prepend(bar);
    return bar;
  },

  _renderSiblingAlarms(alarms, storageFile) {
    const bar = this._ensureSiblingAlarmBar();
    if (!alarms.length) {
      bar.hidden = true;
      bar.replaceChildren();
      document.body.classList.remove("shell-sibling-alarm-open");
      return;
    }
    bar.replaceChildren();
    for (const alarm of alarms) {
      bar.append(this._siblingAlarmRow(alarm, storageFile));
    }
    bar.hidden = false;
    document.body.classList.add("shell-sibling-alarm-open");
  },

  _siblingAlarmRow(alarm, storageFile) {
    const row = document.createElement("div");
    row.className = "shell-sibling-alarm";

    const text = document.createElement("div");
    text.className = "shell-sibling-alarm-text";
    const title = document.createElement("strong");
    title.textContent = alarm.title || "A topic";
    const explanation = document.createElement("span");
    explanation.textContent =
      " was changed on another of your clients, and this client has changes" +
      " that were not built on it. Nothing is being synced until you choose.";
    text.append(title, explanation);
    if (storageFile) {
      const note = document.createElement("p");
      note.className = "shell-note";
      note.textContent =
        "Taking the other version discards this client's copy. To keep it," +
        ` copy this file first: ${storageFile}`;
      text.append(note);
    }

    const actions = document.createElement("div");
    actions.className = "shell-sibling-alarm-actions";
    actions.append(
      this._siblingAlarmButton(
        "Use the other client's version",
        alarm.topic_uuid,
        "take_sibling",
        "danger",
      ),
      this._siblingAlarmButton(
        "Keep this client's version",
        alarm.topic_uuid,
        "keep_local",
        "primary",
      ),
    );
    row.append(text, actions);
    return row;
  },

  _siblingAlarmButton(label, topicUuid, decision, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.onclick = async () => {
      button.disabled = true;
      try {
        await this._post("/api/core/siblings/alarms/resolve", {
          topic_uuid: topicUuid,
          decision,
        });
        await this._changed();
        await this.refreshSiblingAlarms();
      } catch (error) {
        button.disabled = false;
        showToast(error.message, true);
      }
    };
    return button;
  },

  _renderSharingHeader(people, errorMessage = "") {
    const button = document.getElementById("shellConnectionBtn");
    if (!button) return;
    // Never disabled, not even with no topic selected: accepting an invite
    // token is how a fresh install gets its first topic, and the token form
    // lives behind this button. Disabling it made first run a dead end.
    button.replaceChildren();
    button.className = people.length ? "peer-cluster" : "peer-cluster local";
    if (!people.length) {
      button.textContent = errorMessage ? "Sharing" : "Private";
      button.title = errorMessage || "Private — no one else is involved";
      return;
    }
    for (const info of people.slice(0, 4)) {
      const addr = info.address || "";
      const avatar = document.createElement("span");
      const online = !info.status || info.status.state !== "offline";
      avatar.className = "header-avatar " + (online ? "status-online" : "status-offline");
      if (info.picture) {
        avatar.style.backgroundImage = 'url("' + info.picture + '")';
      } else {
        const source = info.name || addr.replace(/^relay:/, "");
        avatar.textContent = (source.slice(0, 2) || "?").toUpperCase();
      }
      const label = info.name || addr;
      avatar.title = info.channel ? label + " (" + info.channel + ")" : label;
      button.append(avatar);
    }
    if (people.length > 4) {
      const more = document.createElement("span");
      more.className = "header-avatar more";
      more.textContent = "+" + (people.length - 4);
      button.append(more);
    }
    button.title = people
      .map((info) => {
        const label = info.name || info.address || "Unknown";
        return label + (info.channel ? " [" + info.channel + "]" : "");
      })
      .join("\n");
  },

  async refreshSharingHeader() {
    const topic = this._topic();
    if (!topic) {
      this._headerSharingTopic = "";
      this._renderSharingHeader([]);
      return;
    }
    if (this._headerSharingTopic !== topic) {
      this._headerSharingTopic = topic;
      this._renderSharingHeader([]);
    }
    if (this._headerSharingPendingTopic === topic) return;
    this._headerSharingPendingTopic = topic;
    try {
      const response = await fetch(`/api/core/topics/${encodeURIComponent(topic)}/sharing`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.reason || "Could not read sharing status.");
      }
      if (this._topic() === topic) {
        this._renderSharingHeader(payload.people || []);
      }
    } catch (error) {
      if (this._topic() === topic) {
        this._renderSharingHeader([], error.message);
      }
    } finally {
      if (this._headerSharingPendingTopic === topic) {
        this._headerSharingPendingTopic = "";
      }
    }
  },

  async _changed() {
    if (this._options.onChanged) await this._options.onChanged();
  },
};

/*
  Shell additions: a fixed header layout, the Core profile editor, and the
  disagreement pane.

  The header has stable regions so every application looks the same and
  nothing jumps as state changes:

    LEFT    collaboration, topic name, topic switcher, topic status
    MIDDLE  application icon and name, navigation, [+] new topic
    RIGHT   connect area, own avatar

  The topic comes first because the topic is what you are working on; the
  application is only where you are. Topic status sits beside the topic name
  rather than off in the actions, so agreement state is read where the topic
  is read.

  The topic region is filled by the application until Core owns topic
  selection. When Core owns it, the shell fills the same region and nothing
  else moves.
*/
Object.assign(SovereignShell, {
  _profileReady: false,

  _buildHeader(container, options) {
    container.classList.add("shell-bar");
    container.replaceChildren();

    // ---- left: collaboration -------------------------------------------
    //
    // Two controls, each counting the thing it is named for. A setting and a
    // status count never share one, which is what the auto-adopt indicator
    // beside a divergence count used to be (U7).
    const left = document.createElement("div");
    left.className = "shell-left";

    const agenda = this._countButton("shellAgendaBtn", ICON_AGENDA, "Agenda");
    const changes = this._countButton("shellChangesBtn", ICON_CHANGES, "Changes");
    left.append(agenda, changes);

    // ---- middle: navigation ---------------------------------------------
    //
    // The anchor of the bar, and the only thing in it on two lines. The mark
    // alone and not the application's name: beside a topic's own name the
    // wordmark is the redundant half, and an icon says which application
    // this is without competing to be read.
    const middle = document.createElement("div");
    middle.className = "shell-middle";

    const lockup = document.createElement("div");
    lockup.className = "shell-lockup";

    const mark = document.createElement("span");
    mark.className = "shell-app-mark";
    mark.id = "shellAppMark";
    mark.textContent = (options.applicationId || "?").slice(0, 1).toUpperCase();
    // Named for a screen reader, which cannot see what the mark shows. The
    // element stays for `mount` to fill; it is not drawn.
    const name = document.createElement("span");
    name.className = "shell-app-name";
    name.id = "shellAppName";

    const topic = document.createElement("div");
    topic.className = "shell-topic";
    topic.id = "shellTopicRegion";

    lockup.append(mark, name, topic);

    // Where else you can go, nearest first: what this topic names, then
    // everything you hold. The title line says what you are looking at and
    // holds two elements only, which is what lets it read as the anchor;
    // every destination lives on this row instead.
    const context = document.createElement("div");
    context.className = "shell-context";
    context.id = "shellTopicContext";

    middle.append(lockup, context);

    // ---- right: connections ---------------------------------------------
    const actions = document.createElement("div");
    actions.className = "shell-actions";

    const connection = document.createElement("button");
    connection.type = "button";
    connection.id = "shellConnectionBtn";
    connection.className = "peer-cluster local";
    connection.textContent = "Private";
    connection.onclick = () => this.openConnectionPanel();

    const avatar = document.createElement("button");
    avatar.type = "button";
    avatar.id = "shellAvatarBtn";
    avatar.className = "header-avatar-btn";
    avatar.title = "Edit your profile";
    avatar.onclick = () => this.openProfile();

    actions.append(connection, avatar);
    container.append(left, middle, actions);
  },

  // One shape for both left-hand controls: a mark, and the count of what it
  // is named for. No count means no number, not a zero - a zero is a fact
  // nobody needs and it makes an empty bar look busy.
  _countButton(id, icon, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.id = id;
    button.className = "shell-count-btn";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.onclick = () => this.openCollab();
    button.innerHTML =
      `<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">${icon}</svg>` +
      '<span class="shell-count"></span>';
    return button;
  },

  _setCount(id, count, label) {
    const button = document.getElementById(id);
    if (!button) return;
    const slot = button.querySelector(".shell-count");
    slot.textContent = count > 0 ? String(count) : "";
    button.setAttribute("aria-label", count > 0 ? `${label}: ${count}` : label);
  },

  theme() {
    return document.documentElement.getAttribute("data-theme") || DEFAULT_THEME;
  },

  setTheme(theme) {
    const resolved = applyTheme(theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, resolved);
    } catch (error) {
      // Unwritable storage means the choice lasts for this window only,
      // which is still better than refusing to switch at all.
    }
    return resolved;
  },

  toggleTheme() {
    return this.setTheme(this.theme() === "dark" ? "light" : "dark");
  },

  // The topic region and the application-actions slot are the two places an
  // application puts its own controls. Everything else in the bar is Core's.
  setTopicRegion(node) {
    const region = document.getElementById("shellTopicRegion");
    if (!region) return;
    region.replaceChildren();
    if (node) region.append(node);
  },

  // The name of what you are looking at, edited in place where the
  // application allows it. Nothing beside it selects another one: a list of
  // an application's own topics in its own header was a second navigation
  // mesh, and the Cockpit is the first. See DESIGN_UI_CONSISTENCY U3.
  setTopicName(options = {}) {
    const region = document.getElementById("shellTopicRegion");
    if (!region) return;
    let title = region.querySelector(".shell-topic-title");
    if (!title) {
      title = document.createElement("span");
      title.className = "shell-topic-title";
      region.replaceChildren(title);
    }
    // The label is the kind - "Initiative", "Organization", "Flow" - and it
    // names the field rather than being drawn beside the name. The mark to
    // its left already says which application this is, so a word saying the
    // same thing is the redundant half, exactly as U3 found for the wordmark.
    SovereignUI.editableText({
      element: title,
      value: options.title || "",
      placeholder: options.label || "Name",
      ariaLabel: options.label || "Name",
      editable: Boolean(options.title && options.onRename),
      onCommit: async (value) => {
        if (options.onRename) await options.onRename(value);
      },
    });
    this._renderTopicContext();
    // Re-attached here rather than only once at mount: this method builds
    // the region's contents on first use, so anything appended before that
    // would be lost with them.
    this._attachTopicActions();
  },

  // Where another application's topic is opened. Composed from what the host
  // reports about active applications, so no application knows another one's
  // route - and one deactivated here removes its entry instead of leaving a
  // link that goes nowhere.
  topicHref(applicationId, topicUuid) {
    const application = (this._applications || []).find(
      (entry) => entry.application_id === String(applicationId || ""),
    );
    if (!application || !topicUuid) return "";
    return `${application.asset_prefix}?topic=${encodeURIComponent(topicUuid)}`;
  },

  // What this topic is attached to: the team an initiative belongs to, the
  // flows it runs, the work a team has taken on. Core draws them and carries
  // out the two acts that are Core's - taking up a reference you do not hold
  // yet, and removing one. The application says which links exist and what
  // making one calls; it does not say who may remove one, because that is
  // not a rule anybody sets: a link is adopted same-origin, so the only one
  // you can take off is the one you put up.
  //
  // Only links on the topic itself belong here. A card naming the process it
  // waits on belongs beside the card - in the bar it would be a fact about
  // something you cannot see.
  //
  // links  [{uuid, topic_uuid, application_id, label, title, held, mine}]
  // make   [{label, onSelect}] - a kind that can be made and linked at once
  // link   [{label, onSelect}] - one of your own topics, not referenced here
  //
  // U7 split this in two. Going somewhere is the switcher menu beside the
  // name; managing what this is attached to - taking up a reference, letting
  // one go, making a new one - is the dialog behind "Link related...". They
  // were one row of chips because navigating and administering look alike
  // from the outside; they are different frames, and the frame you enter
  // deliberately is the one that stays closed.
  setTopicLinks(options = {}) {
    this._topicLinks = options;
    this._renderTopicContext();
    if (document.getElementById("shellRelateDialog")?.open) this._renderRelateDialog();
  },

  // Beneath the name: where else you can go, nearest range first. What this
  // topic names, then everything you hold, with the rule between them saying
  // the range changed - which is the one thing whitespace cannot state.
  //
  // Names only. The kind is what a chip used to announce in small capitals,
  // and it earned nothing: the destination says what it is the moment you
  // arrive, and a line that is uniformly one class of thing can be uniformly
  // clickable. Hover brightens rather than emboldens, because a weight
  // change reflows the row and drags everything right of it sideways.
  _renderTopicContext() {
    const context = document.getElementById("shellTopicContext");
    if (!context) return;
    context.replaceChildren();

    // An aggregator draws nothing here: it already shows every topic you
    // hold, so a row offering to take you to some of them, and to the
    // aggregator itself, is the second navigation mesh Core has refused
    // since U3. With no topic selected there is likewise nothing to place.
    const current = (this._applications || []).find(
      (app) => app.application_id === this._options.applicationId,
    );
    if (current && current.role === "aggregator") return;
    if (!this._options.topicUuid || !this._topic()) return;

    const held = ((this._topicLinks || {}).links || []).filter((link) => link.held);
    // Only the names shrink. The controls after them are `flex: none`, so a
    // long list truncates itself rather than pushing them off the bar.
    const names = document.createElement("div");
    names.className = "shell-context-links";
    for (const [index, link] of held.entries()) {
      if (index) {
        const dot = document.createElement("span");
        dot.className = "shell-context-dot";
        dot.setAttribute("aria-hidden", "true");
        dot.textContent = "·";
        names.append(dot);
      }
      names.append(this._contextLink(link));
    }
    context.append(names);

    // Always present, never a count. "Link related…" has to be reachable
    // whether or not anything overflowed, and a control that appears only
    // sometimes is one nobody learns. Its menu lists every related topic, so
    // overflow is not a case the reader has to be told about.
    const more = document.createElement("button");
    more.type = "button";
    more.className = "shell-related-menu";
    more.title = "Related";
    more.setAttribute("aria-label", "Related");
    more.innerHTML =
      `<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">${ICON_CHEVRON_DOWN}</svg>`;
    this._buildRelatedMenu(more);
    context.append(more);

    // The widest range, and the last thing on the row. Absent where no
    // application registered as an aggregator - the wording that names it
    // has nothing to name then either (DESIGN_VOCABULARY.md).
    const cockpit = (this._applications || []).find((app) => app.role === "aggregator");
    if (cockpit && cockpit.application_id !== this._options.applicationId) {
      const pipe = document.createElement("span");
      pipe.className = "shell-context-pipe";
      pipe.setAttribute("aria-hidden", "true");

      const link = document.createElement("a");
      link.className = "shell-cockpit-btn";
      link.href = cockpit.asset_prefix;
      link.title = `Open ${cockpit.display_name}`;
      link.setAttribute("aria-label", `Open ${cockpit.display_name}`);
      link.innerHTML = cockpit.icon
        ? `<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">${cockpit.icon}</svg>`
        : cockpit.display_name.slice(0, 1).toUpperCase();
      context.append(pipe, link);
    }
  },

  _contextLink(link) {
    const href = this.topicHref(link.application_id, link.topic_uuid);
    const anchor = document.createElement("a");
    anchor.className = "shell-context-link";
    anchor.textContent = link.title || "Untitled";
    anchor.title = link.label ? `${link.label}: ${anchor.textContent}` : anchor.textContent;
    if (href) anchor.href = href;
    return anchor;
  },

  // Every related topic, whether or not it fitted on the row, and the one
  // act that is not a destination. References you have not taken up are
  // deliberately absent: taking one up is an act, and it lives in the dialog
  // with the other acts rather than among places to go.
  _buildRelatedMenu(button) {
    SovereignUI.actionMenu({
      button,
      align: "start",
      // Read when the menu opens, not when the button was made: what this is
      // attached to changes with every sync.
      items: () => {
        const links = ((this._topicLinks || {}).links || []).filter((link) => link.held);
        const items = [];
        if (links.length) {
          items.push({heading: "Related"});
          for (const link of links) {
            items.push({
              label: link.title || "Untitled",
              onSelect: () => {
                const href = this.topicHref(link.application_id, link.topic_uuid);
                if (href) window.location.href = href;
              },
            });
          }
          items.push({separator: true});
        }
        items.push({label: "Link related…", onSelect: () => this.openRelateDialog()});
        return items;
      },
    });
  },

  // Everything about what this topic is attached to that is not going there:
  // taking up a reference somebody else made, letting one of mine go, and
  // making a new one.
  openRelateDialog() {
    if (!this._relateReady) {
      const host = document.createElement("div");
      host.innerHTML = [
        '<dialog id="shellRelateDialog" class="shell-dialog">',
        '<div class="shell-pane-header">',
        "<strong>Related</strong>",
        '<button type="button" id="shellRelateClose" class="shell-pane-close" aria-label="Close">&times;</button>',
        "</div>",
        '<div class="shell-dialog-body">',
        '<div id="shellRelateRows" class="shell-link-rows"></div>',
        '<div id="shellRelateActions" class="shell-row"></div>',
        "</div></dialog>",
      ].join("");
      document.body.append(...host.children);
      this._relateReady = true;
      document.getElementById("shellRelateClose").onclick = () =>
        document.getElementById("shellRelateDialog").close();
    }
    this._renderRelateDialog();
    document.getElementById("shellRelateDialog").showModal();
  },

  _renderRelateDialog() {
    const rows = document.getElementById("shellRelateRows");
    const actions = document.getElementById("shellRelateActions");
    if (!rows) return;
    const current = this._topicLinks || {};
    rows.replaceChildren();
    const links = current.links || [];
    if (!links.length) {
      const empty = document.createElement("p");
      empty.className = "shell-note";
      empty.textContent = "Nothing is linked to this yet.";
      rows.append(empty);
    }
    for (const link of links) rows.append(this._relateRow(link));

    actions.replaceChildren();
    const offers = [...(current.make || []), ...(current.link || [])].filter(Boolean);
    for (const offer of offers) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ui-button";
      button.textContent = offer.label;
      button.onclick = async () => {
        document.getElementById("shellRelateDialog").close();
        await offer.onSelect(offer);
      };
      actions.append(button);
    }
  },

  _relateRow(link) {
    const row = document.createElement("div");
    row.className = `shell-link-row${link.held ? "" : " unheld"}`;

    const label = document.createElement("span");
    label.className = "shell-link-label";
    label.textContent = link.label || "";

    const title = document.createElement("span");
    title.className = "shell-link-title";
    title.textContent = String(link.title || "Untitled");
    row.append(label, title);

    const act = document.createElement("button");
    act.type = "button";
    act.className = "ui-button shell-link-act";
    if (link.held) {
      // One reference, gone. What it points at is untouched, and so is
      // everybody else's reference to it - which is why this asks nothing.
      // The minus, never the trash can: this is off my side, not destroyed.
      act.innerHTML =
        `<svg viewBox="0 0 24 24" aria-hidden="true" class="icon-svg">${ICON_REMOVE}</svg>`;
      act.title = "Remove from my Cockpit. What it points at is kept";
      act.setAttribute("aria-label", "Remove from my Cockpit");
      act.hidden = link.mine === false;
      act.onclick = async () => {
        await this._actOnTopicLink("onRemove", link);
        this._renderRelateDialog();
      };
    } else {
      // Not broken - an invitation. Following it reaches only what a peer is
      // already publishing here, so it resolves or it says nobody is.
      act.textContent = "Add to Cockpit";
      act.onclick = async () => {
        await this._actOnTopicLink("onFollow", link);
        this._renderRelateDialog();
      };
    }
    row.append(act);
    return row;
  },

  async _actOnTopicLink(kind, link) {
    const handler = (this._topicLinks || {})[kind];
    if (!handler) return;
    try {
      await handler(link);
    } catch (error) {
      showToast(error.message, true);
    }
  },

  // A decision about the topic itself belongs beside the topic's name, not
  // in the far corner with the application-level actions. Adopting a
  // renamed board is about the thing the title shows, and a control that
  // far from it reads as belonging to something else entirely.
  setTopicActions(node) {
    this._topicActions = node || null;
    this._attachTopicActions();
  },

  _attachTopicActions() {
    const node = this._topicActions;
    if (!node) return;
    const region = document.getElementById("shellTopicRegion");
    if (!region) return;
    const host = region.querySelector(".shell-topic-picker") || region;
    if (node.parentElement !== host) host.append(node);
  },

  // ---- making a topic ----------------------------------------------------
  //
  // Making a topic has one shape wherever it starts from: a name, what it
  // starts from, and a snapshot file as an alternative to both. There were
  // four of these - three in the Cockpit and one in S-Team - identical but
  // for the noun, and the S-Team one was the only place a snapshot could
  // not be loaded. That is U1's argument arriving on schedule: the dialog
  // is Core's functionality, so its appearance and its rules are Core's.
  //
  // What each entry means stays the application's. Core knows a template is
  // a value with a label; whether that value is a board to copy, a team to
  // clone or a workflow definition is not its business, and neither is what
  // creating actually calls.

  _ensureNewTopicDialog() {
    if (this._newTopicReady) return;
    const host = document.createElement("div");
    host.innerHTML = [
      '<dialog id="shellNewTopicModal" class="shell-dialog">',
      '<form method="dialog" class="shell-panel" id="shellNewTopicForm">',
      '<h2 id="shellNewTopicHeading">New topic</h2>',
      '<label for="shellNewTopicName">Name</label>',
      '<input id="shellNewTopicName" class="ui-text-field">',
      '<div id="shellNewTopicTemplateRow" class="shell-new-topic-row">',
      '<label for="shellNewTopicTemplate">Create from</label>',
      '<select id="shellNewTopicTemplate" class="ui-select"></select>',
      '<p id="shellNewTopicTemplateNote" class="shell-note"></p>',
      "</div>",
      '<div id="shellNewTopicSnapshotRow" class="shell-new-topic-row">',
      '<button type="button" id="shellNewTopicSnapshotBtn">Load snapshot file…</button>',
      '<input type="file" id="shellNewTopicSnapshotFile"',
      ' accept=".s-snapshot,application/json" hidden>',
      '<p id="shellNewTopicSnapshotNote" class="shell-note"></p>',
      "</div>",
      "<menu>",
      '<button type="button" id="shellNewTopicCancelBtn">Cancel</button>',
      '<button type="submit" class="primary">Create</button>',
      "</menu></form></dialog>",
    ].join("");
    document.body.append(...host.children);
    this._newTopicReady = true;

    const file = document.getElementById("shellNewTopicSnapshotFile");
    document.getElementById("shellNewTopicCancelBtn").onclick = () =>
      document.getElementById("shellNewTopicModal").close();
    document.getElementById("shellNewTopicSnapshotBtn").onclick = () => {
      // Cleared first so choosing the same file twice still fires change.
      file.value = "";
      file.click();
    };
    file.onchange = () => this._loadSnapshotChoice(file.files?.[0] || null);
    document.getElementById("shellNewTopicTemplate").onchange = () =>
      this._showTemplateDescription();
    document.getElementById("shellNewTopicForm").onsubmit = (event) => {
      event.preventDefault();
      this._submitNewTopic();
    };
  },

  // noun               what is being made, for the heading and the placeholder
  // templates          [{value, label, group, description}], as selectOptions
  // templateRequired   a flow has no meaning without one; an initiative does
  // blankLabel         what starting from nothing is called
  // snapshotType       the item_type a snapshot file must carry, or omitted
  //                    where this application cannot make one from a file
  // onCreate           ({name, template, option, snapshot}) - the application's
  openNewTopicDialog(options = {}) {
    this._ensureNewTopicDialog();
    const noun = String(options.noun || "Topic").toLowerCase();
    this._newTopic = {options, noun, snapshot: null};

    document.getElementById("shellNewTopicHeading").textContent = `New ${noun}`;
    const name = document.getElementById("shellNewTopicName");
    name.value = "";
    name.placeholder = `Untitled ${noun}`;

    const templates = options.templates || [];
    const required = Boolean(options.templateRequired);
    const select = document.getElementById("shellNewTopicTemplate");
    select.required = required;
    SovereignUI.selectOptions(
      select,
      templates,
      required
        ? {value: templates[0]?.value ?? ""}
        : {emptyLabel: options.blankLabel || "Start empty", value: ""},
    );
    // Nothing to choose and nothing required is not an empty menu, it is no
    // question: an application with no templates asks only for a name.
    document.getElementById("shellNewTopicTemplateRow").hidden =
      !templates.length && !required;
    document.getElementById("shellNewTopicSnapshotRow").hidden =
      !options.snapshotType;

    this._clearSnapshotChoice();
    this._showTemplateDescription();
    document.getElementById("shellNewTopicModal").showModal();
  },

  _clearSnapshotChoice() {
    if (this._newTopic) this._newTopic.snapshot = null;
    document.getElementById("shellNewTopicSnapshotFile").value = "";
    this._note("shellNewTopicSnapshotNote", "");
    const select = document.getElementById("shellNewTopicTemplate");
    select.disabled = false;
    SovereignUI.refreshSelect(select);
  },

  async _loadSnapshotChoice(chosen) {
    if (!chosen) return;
    const state = this._newTopic || {noun: "topic", options: {}};
    const select = document.getElementById("shellNewTopicTemplate");
    const name = document.getElementById("shellNewTopicName");
    try {
      if (chosen.size > SNAPSHOT_FILE_LIMIT) {
        throw new Error("Snapshot file is too large.");
      }
      const snapshot = JSON.parse(await chosen.text());
      // The server checks this too and is the authority. Reading it here is
      // so the wrong file is refused while the dialog is still open, rather
      // than after a create that had nowhere to go.
      if (
        snapshot?.format !== "s-protocol.item-snapshot"
        || snapshot?.format_version !== 1
        || snapshot?.item_type !== String(state.options.snapshotType || "")
        || typeof snapshot?.content !== "object"
        || snapshot.content === null
      ) {
        throw new Error(`This file does not hold a ${state.noun} snapshot.`);
      }
      this._clearSnapshotChoice();
      state.snapshot = snapshot;
      this._note(
        "shellNewTopicSnapshotNote", `Loaded: ${snapshot.name || chosen.name}`,
      );
      // A snapshot is what it starts from, so there is nothing left to
      // choose. Disabled rather than quietly ignored.
      select.disabled = true;
      SovereignUI.refreshSelect(select);
      if (!name.value.trim() && snapshot.source_name) {
        name.value = snapshot.source_name;
      }
    } catch (error) {
      this._clearSnapshotChoice();
      this._note(
        "shellNewTopicSnapshotNote",
        error instanceof SyntaxError
          ? "Snapshot file is not valid JSON."
          : error.message,
      );
    }
  },

  _showTemplateDescription() {
    const select = document.getElementById("shellNewTopicTemplate");
    this._note(
      "shellNewTopicTemplateNote",
      select.selectedOptions[0]?.dataset.description || "",
    );
  },

  _submitNewTopic() {
    const state = this._newTopic;
    if (!state) return;
    const select = document.getElementById("shellNewTopicTemplate");
    const name =
      document.getElementById("shellNewTopicName").value.trim()
      || `Untitled ${state.noun}`;
    const snapshot = state.snapshot;
    const option = snapshot ? null : select.selectedOptions[0] || null;
    document.getElementById("shellNewTopicModal").close();
    if (state.options.onCreate) {
      state.options.onCreate({
        name, snapshot, option, template: snapshot ? "" : select.value,
      });
    }
  },

  // ---- profile -----------------------------------------------------------

  _ensureProfileDialog() {
    if (this._profileReady) return;
    const host = document.createElement("div");
    host.innerHTML = [
      '<dialog id="shellProfileModal" class="shell-dialog">',
      '<form method="dialog" class="shell-panel" id="shellProfileForm">',
      "<h2>Profile</h2>",
      '<label for="shellProfileName">Name</label>',
      '<input id="shellProfileName">',
      '<label for="shellProfilePicture">Profile picture</label>',
      '<input id="shellProfilePicture" type="file" accept="image/png,image/jpeg,image/gif,image/webp">',
      '<img id="shellProfilePreview" class="shell-avatar-preview" alt="">',
      '<p class="shell-note">PNG, JPEG, GIF or WebP. The picture is shared with everyone you collaborate with.</p>',
      // Everything above is the shared profile and saves on Save. The theme
      // is neither: it is a display preference for this device, so it is
      // separated by a rule, applies the moment it changes, and is not
      // undone by Cancel. Saying so here is cheaper than the surprise.
      '<hr class="shell-profile-divider">',
      '<label for="shellThemeSelect">Theme</label>',
      '<select id="shellThemeSelect" class="ui-select">',
      '<option value="dark">Dark</option>',
      '<option value="light">Light</option>',
      "</select>",
      '<p class="shell-note">Applies to this device only and takes effect immediately. Not shared with anyone.</p>',
      '<p id="shellProfileNote" class="shell-note"></p>',
      "<menu>",
      '<button type="button" id="shellRemoveAvatarBtn" class="danger">Remove picture</button>',
      '<button type="button" id="shellProfileCancelBtn">Cancel</button>',
      '<button type="submit" class="primary">Save</button>',
      "</menu></form></dialog>",
    ].join("");
    document.body.append(...host.children);
    this._profileReady = true;
    SovereignUI.selectControl(document.getElementById("shellThemeSelect"));

    document.getElementById("shellProfileCancelBtn").onclick = () =>
      document.getElementById("shellProfileModal").close();
    document.getElementById("shellProfilePicture").onchange = () => {
      const file = document.getElementById("shellProfilePicture").files[0];
      if (!file) return;
      const preview = document.getElementById("shellProfilePreview");
      preview.src = URL.createObjectURL(file);
      preview.style.display = "block";
    };
    document.getElementById("shellProfileForm").onsubmit = (event) => {
      event.preventDefault();
      this._saveProfile();
    };
    document.getElementById("shellRemoveAvatarBtn").onclick = () =>
      this._saveProfile({ removePicture: true });
    // Not part of the form's submit: the theme is local, so it applies on
    // change rather than waiting for a Save that only concerns the profile.
    document.getElementById("shellThemeSelect").onchange = (event) =>
      this.setTheme(event.target.value);
  },

  async _profileView() {
    const response = await fetch("/api/core/profile");
    return response.json();
  },

  async openProfile() {
    this._ensureProfileDialog();
    this._note("shellProfileNote", "");
    let view = {};
    try {
      view = await this._profileView();
    } catch (error) {
      this._note("shellProfileNote", "Could not read your profile.");
    }
    document.getElementById("shellProfileName").value = view.display_name || "";
    const themeSelect = document.getElementById("shellThemeSelect");
    themeSelect.value = this.theme();
    SovereignUI.refreshSelect(themeSelect);
    document.getElementById("shellProfilePicture").value = "";
    const preview = document.getElementById("shellProfilePreview");
    preview.src = view.picture || "";
    preview.style.display = view.picture ? "block" : "none";
    document.getElementById("shellRemoveAvatarBtn").hidden = !view.picture;
    document.getElementById("shellProfileModal").showModal();
  },

  async _uploadBlob(file) {
    const response = await fetch("/api/blob", {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": file.name,
      },
      body: file,
    });
    const payload = await response.json();
    if (!response.ok || payload.status === "error") {
      throw new Error(payload.reason || "Upload failed");
    }
    return payload;
  },

  async _saveProfile(options) {
    const request = options || {};
    const name = document.getElementById("shellProfileName").value;
    const file = document.getElementById("shellProfilePicture").files[0];
    try {
      await this._post("/api/core/profile", { name });
      if (request.removePicture) {
        await this._post("/api/core/profile/avatar", { remove: true });
      } else if (file) {
        const uploaded = await this._uploadBlob(file);
        await this._post("/api/core/profile/avatar", {
          attachment: {
            id:
              globalThis.crypto && globalThis.crypto.randomUUID
                ? globalThis.crypto.randomUUID()
                : String(Date.now()) + "-" + file.name,
            role: "avatar",
            blob_id: uploaded.blob_id,
            name: file.name,
            size: uploaded.size,
            mime: uploaded.mime,
          },
        });
      }
      document.getElementById("shellProfileModal").close();
      await this._changed();
      this.refreshAvatar();
    } catch (error) {
      this._note("shellProfileNote", error.message);
    }
  },

  async refreshAvatar() {
    const button = document.getElementById("shellAvatarBtn");
    if (!button) return;
    let view = {};
    try {
      view = await this._profileView();
    } catch (error) {
      return;
    }
    button.replaceChildren();
    const avatar = document.createElement("span");
    avatar.className = "header-avatar status-online";
    if (view.picture) {
      avatar.style.backgroundImage = 'url("' + view.picture + '")';
    } else {
      const source = view.display_name || "?";
      avatar.textContent = source.slice(0, 2).toUpperCase();
    }
    button.title = (view.display_name || "You") + " - edit your profile";
    button.append(avatar);
  },

  // ---- disagreements -----------------------------------------------------

  // Both applications already publish transition_events and
  // transition_by_node in the same shape, because Session decides what a
  // transition is. Reading them here means neither has to render agreement
  // state itself.
  _disagreements() {
    const state = this._options.state ? this._options.state() : {};
    const grouped = state.transition_by_node || {};
    return Object.keys(grouped)
      .map((uuid) => Object.assign({ node_uuid: uuid }, grouped[uuid]))
      .filter((item) => item.type && item.type !== "in_agreement");
  },

  // One number, and it counts what a decision is owed on: a conflict, or a
  // change of somebody else's waiting for me. Not what is still travelling -
  // a count that includes what you cannot act on is a count you learn to
  // ignore. Travelling is still visible: the control pulses (U7).
  refreshDisagreements() {
    const changes = document.getElementById("shellChangesBtn");
    if (!changes) return;
    const state = this._options.state ? this._options.state() : {};
    this._setCount("shellAgendaBtn", (state.agenda_items || []).length, "Agenda");

    // Agreement state is a property of one topic. An application that shows
    // many at once - an overview - has no single answer, so the control
    // stands down rather than claiming one.
    if (!this._options.topicUuid || !this._topic()) {
      changes.disabled = true;
      changes.classList.remove("has-conflict", "is-moving");
      this._setCount("shellChangesBtn", 0, "Changes");
      changes.title = "Select one first";
      return;
    }
    changes.disabled = false;
    const items = this._disagreements();
    const conflicts = items.filter((item) => item.stage === "conflict").length;
    const mine = items.filter((item) => item.stage === "awaiting_me").length;
    const moving = items.length - conflicts - mine;
    const owed = conflicts + mine;
    this._setCount("shellChangesBtn", owed, "Changes");
    changes.classList.toggle("has-conflict", conflicts > 0);
    changes.classList.toggle("is-moving", moving > 0);
    changes.title = owed
      ? `${conflicts} in conflict, ${mine} needing your review`
      : moving
        ? "Waiting on others"
        : "No open changes";
  },

  // Rendering the unsettled list is separate from where it is shown, so the
  // collaboration pane and the standalone dialog draw the same thing.
  _renderDisagreementList(list) {
    if (!list) return;
    list.replaceChildren();
    const items = this._disagreements();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "shell-note";
      empty.textContent = "No open changes.";
      list.append(empty);
      return;
    }
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "shell-disagreement-row";
      row.dataset.status = item.stage;
      const label = document.createElement("span");
      label.className = "shell-disagreement-label";
      label.textContent = transitionLabel(item);
      const where = document.createElement("span");
      where.className = "shell-note";
      const describe = this._options.describeNode;
      where.textContent = describe ? describe(item.node_uuid) || "" : "";
      row.append(label, where);
      const actions = document.createElement("div");
      actions.className = "shell-disagreement-actions";
      if (this._options.revealNode) {
        const reveal = document.createElement("button");
        reveal.type = "button";
        reveal.textContent = "Show";
        reveal.onclick = () => {
          this.closeCollab();
          this._options.revealNode(item.node_uuid);
        };
        actions.append(reveal);
      }
      // The list of what is unsettled is also the shortest way to settle it:
      // the same control the node carries in the document, so the pane can be
      // walked top to bottom without opening anything.
      //
      // canReact is for an application that shows several topics: the Cockpit
      // can settle a board node and only link to a team's, and offering a
      // button it cannot honour would be worse than offering none.
      const reactable = this._options.canReact ? this._options.canReact(item.node_uuid) : true;
      if (this._options.reactNode && reactable) {
        const control = SovereignUI.reactionControl({
          info: item,
          onReact: (choice) => this._options.reactNode(item.node_uuid, choice),
        });
        if (control) actions.append(control);
      }
      if (actions.childElementCount) row.append(actions);
      list.append(row);
    }
  },

  openDisagreements() {
    // The header button opens the whole collaboration pane; what is not in
    // agreement is one section of it, beside the agenda it belongs with.
    this.openCollab();
  },
});

/*
  The collaboration pane - the same surface in every application.

  Sections, in the order S-Initiative established: what I want to discuss, what
  everyone wants to discuss, what is not yet Aligned, and the settings
  that govern adoption. All four are Core concepts, so all four live here and
  no application renders them itself.

  Agendas are Session's: an agenda item is a child of the topic root, and
  every application's topic is a root. An application supplies only the API
  paths it exposes them on, because route namespacing is per application.
*/

Object.assign(SovereignShell, {
  _collabReady: false,

  // One merged agenda, not two. The list is a topic's whole agenda; splitting
  // "mine" from "everyone's" duplicated every row you authored and made the
  // pane twice as tall for no information gain. The add-topic form moves to
  // the bottom, after what already exists, not before it.
  _ensureCollabPane() {
    if (this._collabReady) return;
    const host = document.createElement("div");
    host.innerHTML = [
      '<div id="shellCollabOverlay" class="shell-pane-overlay" hidden></div>',
      '<aside id="shellCollabPane" class="shell-pane shell-pane-left" hidden>',
      '<div class="shell-pane-header">',
      "<strong>Collaboration</strong>",
      '<button type="button" id="shellCollabCloseBtn" class="shell-pane-close" aria-label="Close">&times;</button>',
      "</div>",
      '<div class="shell-pane-section">',
      "<h3>Agenda</h3>",
      '<div id="shellAgendaList" class="shell-agenda-list"></div>',
      '<form id="shellAgendaForm" class="shell-row">',
      '<input id="shellAgendaText" placeholder="Add an agenda item">',
      '<button type="submit">Add</button>',
      "</form>",
      "</div>",
      '<div class="shell-pane-section">',
      '<h3 id="shellNotAlignedTitle">Changes</h3>',
      '<div id="shellDisagreementList" class="shell-disagreement-list"></div>',
      // The standing rule sits under the queue it governs: the list is what
      // the rule did not decide. It was in the connections pane, where it
      // read as a property of the channel rather than of how arriving work
      // is handled (U7).
      '<div id="shellCollabAutoAdopt" class="shell-pane-subsection">',
      "<h4>Incoming changes</h4>",
      '<div id="shellCollabAutoAdoptControl"></div>',
      "</div>",
      "</div>",
      "</aside>",
    ].join("");
    document.body.append(...host.children);
    this._collabReady = true;

    document.getElementById("shellCollabCloseBtn").onclick = () => this.closeCollab();
    document.getElementById("shellCollabOverlay").onclick = () => this.closeCollab();
    document.getElementById("shellAgendaForm").onsubmit = (event) => {
      event.preventDefault();
      this._addAgendaItem();
    };
  },

  closeCollab() {
    const pane = document.getElementById("shellCollabPane");
    const overlay = document.getElementById("shellCollabOverlay");
    if (pane) pane.hidden = true;
    if (overlay) overlay.hidden = true;
    document.body.classList.remove("shell-pane-open-left");
  },

  _agendaRoutes() {
    const routes = this._options.agendaRoutes;
    return typeof routes === "function" ? routes() : routes || null;
  },

  async _addAgendaItem() {
    const routes = this._agendaRoutes();
    const field = document.getElementById("shellAgendaText");
    const text = field.value.trim();
    const topic = this._topic();
    if (!routes || !text || !topic) return;
    const sessionView = this._options.sessionView;
    const optimisticUuid = globalThis.crypto?.randomUUID
      ? `optimistic:${globalThis.crypto.randomUUID()}`
      : `optimistic:${Date.now()}:${Math.random()}`;
    const selected = this._options.state ? this._options.state().selected_topic : null;
    const applicationId = selected?.uuid === topic ? selected.application_id : "";
    field.value = "";
    try {
      if (sessionView && typeof sessionView.mutate === "function") {
        await sessionView.mutate({
          key: `agenda:${topic}`,
          command: "create-agenda-item",
          arguments: { topic, text, optimisticUuid, applicationId },
          invalidates: ["tiles", "context"],
          action: (context) =>
            this._post(
              routes.create,
              {
                [routes.topicKey]: topic,
                text,
                mutation_id: context.mutationId,
              },
              { signal: context.signal },
            ),
          project: (draft, change) => {
            const items = draft.agenda_items || [];
            if (!items.some((item) => item.uuid === change.optimisticUuid)) {
              draft.agenda_items = [
                ...items,
                {
                  uuid: change.optimisticUuid,
                  data: {
                    type: "agenda_item",
                    text: change.text,
                    priority: null,
                    author: draft.identity_uuid || "",
                  },
                  perspective: {
                    identity_uuid: draft.identity_uuid || "",
                    local: true,
                    addresses: [],
                    conflict: false,
                  },
                },
              ];
            }
            const topics = change.applicationId === "team" ? draft.teams || [] : draft.boards || [];
            const tile = topics.find((entry) => entry.uuid === change.topic);
            if (tile) tile.agenda_count = Number(tile.agenda_count || 0) + 1;
            return draft;
          },
        });
      } else {
        await this._post(routes.create, { [routes.topicKey]: topic, text });
        await this._changed();
      }
      this.openCollab();
    } catch (error) {
      field.value = text;
      showToast(error.message, true);
    }
  },

  // Identity is Core's. known_identities (Session.known_identities) is the
  // one place every application - even one with no user model of its own,
  // like S-Team - can resolve an author uuid to a name and a picture.
  _identityFor(uuid) {
    const state = this._options.state ? this._options.state() : {};
    const known = state.known_identities || [];
    return known.find((entry) => entry.uuid === uuid) || null;
  },

  _identityAvatar(identity, addr) {
    const avatar = document.createElement("span");
    avatar.className = "header-avatar shell-peer-avatar status-online";
    if (identity && identity.picture) {
      avatar.style.backgroundImage = 'url("' + identity.picture + '")';
    } else {
      const source = (identity && identity.name) || addr || "?";
      avatar.textContent = source.slice(0, 2).toUpperCase();
    }
    avatar.title = (identity && identity.name) || addr || "Unknown";
    return avatar;
  },

  _agendaRow(item) {
    const state = this._options.state ? this._options.state() : {};
    const me = state.identity_uuid || (state.user_profile && state.user_profile.uuid) || "";
    const mine = item.perspective
      ? item.perspective.local === true
      : item.data.author === me;
    const routes = this._agendaRoutes();

    const row = document.createElement("div");
    row.className = "shell-agenda-item";
    row.dataset.priority = item.data.priority || "";
    row.dataset.itemUuid = item.uuid;
    row.dataset.reorderId = item.uuid;

    if (mine && routes?.move) {
      row.classList.add("has-drag");
      row.append(SovereignUI.reorderHandle({
        label: "Reorder agenda item",
      }));
    }

    const text = document.createElement("span");
    text.className = "shell-agenda-text";
    text.textContent = item.data.text || "";
    if (mine && routes?.update) {
      SovereignUI.editableText({
        element: text,
        value: item.data.text || "",
        placeholder: "Discussion topic",
        ariaLabel: "Discussion topic",
        onCommit: (value) => this._post(routes.update, {
          item_uuid: item.uuid,
          text: value,
        }),
        onChanged: async () => {
          await this._changed();
          this.openCollab();
        },
      });
    }
    row.append(text);

    const actions = document.createElement("span");
    actions.className = "shell-agenda-actions";

    // Only the originator may steer their own item; everyone else reads it.
    // That rule is Session's, and the view simply reflects it. Priority and
    // delete stay out of the way until you are looking at your own row.
    if (mine && routes) {
      const {control: priorityControl} = SovereignUI.selectionControl({
        items: [
          ["", "No priority"],
          ["high", "High"],
          ["medium", "Medium"],
          ["low", "Low"],
        ],
        value: item.data.priority || "",
        variant: "compact",
        ariaLabel: "Priority for " + (item.data.text || "agenda topic"),
        selectClass: "shell-agenda-priority-control",
        onChange: async ({currentTarget: priority}) => {
          row.dataset.priority = priority.value || "";
          try {
            await this._post(routes.setPriority, {
              item_uuid: item.uuid,
              priority: priority.value || null,
            });
            await this._changed();
            this.openCollab();
          } catch (error) {
            showToast(error.message, true);
          }
        },
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "shell-agenda-delete shell-agenda-hover";
      remove.textContent = "Delete";
      remove.onclick = async () => {
        try {
          await this._post(routes.delete, { item_uuid: item.uuid });
          await this._changed();
          this.openCollab();
        } catch (error) {
          showToast(error.message, true);
        }
      };
      actions.append(remove, priorityControl);
    } else {
      const priority = document.createElement("span");
      priority.className = "shell-agenda-priority-label";
      priority.textContent =
        {
          high: "High",
          medium: "Medium",
          low: "Low",
        }[item.data.priority] || "No priority";
      actions.append(priority);
    }

    const sourceIdentity = item.perspective?.identity_uuid || item.data.author;
    const identity = this._identityFor(sourceIdentity);
    actions.append(this._identityAvatar(identity, sourceIdentity));
    row.append(actions);
    return row;
  },

  _renderAgenda() {
    const state = this._options.state ? this._options.state() : {};
    const items = state.agenda_items || [];
    const list = document.getElementById("shellAgendaList");
    if (!list) return;
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "shell-note";
      empty.textContent = "No agenda items yet.";
      list.append(empty);
    }
    for (const item of items) list.append(this._agendaRow(item));
    const routes = this._agendaRoutes();
    SovereignUI.reorderableList({
      container: list,
      itemSelector: ".shell-agenda-item",
      onMove: ({id, index}) => this._post(routes.move, {item_uuid: id, index}),
      onChanged: async () => {
        await this._changed();
        this.openCollab();
      },
    });
    document.getElementById("shellAgendaForm").hidden = !routes;
  },

  refreshCollaborationPane() {
    const pane = document.getElementById("shellCollabPane");
    if (!pane || pane.hidden) return;

    const agenda = document.getElementById("shellAgendaList");
    const agendaIsActive =
      agenda?.dataset.reordering === "true"
      || (agenda && agenda.contains(document.activeElement));
    if (!agendaIsActive) this._renderAgenda();

    this._renderDisagreementList(document.getElementById("shellDisagreementList"));
  },

  // Labels for the two universal modes. An application offering more supplies
  // its own labels; Core shows the raw mode rather than inventing wording for
  // a policy it does not interpret.
  AUTO_ADOPT_LABELS: {
    always: "Adopt incoming changes automatically",
    never: "Review each change first",
  },
  AUTO_ADOPT_DESCRIPTIONS: {
    always: "Changes from other people are adopted automatically.",
    never: "Changes from other people wait for you to review and adopt them.",
  },

  _autoAdoptControl() {
    const configured = this._options.autoAdoptRoute;
    const route = typeof configured === "function" ? configured() : configured;
    const topic = this._topic();
    if (!route || !topic) return null;
    const state = this._options.state ? this._options.state() : {};
    const modes = state.auto_adopt_modes || ["always", "never"];
    const labels = Object.assign({}, this.AUTO_ADOPT_LABELS, this._options.autoAdoptLabels || {});
    const descriptions = Object.assign(
      {},
      this.AUTO_ADOPT_DESCRIPTIONS,
      this._options.autoAdoptDescriptions || {},
    );

    const wrap = document.createElement("div");
    wrap.className = "shell-auto-adopt-setting";
    const row = document.createElement("div");
    row.className = "shell-auto-adopt-row";
    const indicator = document.createElement("span");
    indicator.className = "shell-auto-adopt-indicator";
    indicator.setAttribute("aria-hidden", "true");
    const {select, control} = SovereignUI.selectionControl({
      items: modes.map((mode) => [mode, labels[mode] || mode]),
      value: state.auto_adopt_mode || "always",
      ariaLabel: "Automatic adoption",
      onChange: async () => {
        renderSelection();
        try {
          await this._post(route.path, {
            [route.topicKey]: topic,
            mode: select.value,
          });
          await this._changed();
        } catch (error) {
          showToast(error.message, true);
        }
      },
    });
    const description = document.createElement("p");
    description.className = "shell-note shell-auto-adopt-description";
    const renderSelection = () => {
      indicator.replaceChildren();
      if (this._options.renderAutoAdoptIndicator) {
        this._options.renderAutoAdoptIndicator(indicator, select.value);
      } else {
        const filled = select.value === "always" ? 4 : 0;
        for (let index = 0; index < 4; index += 1) {
          const cell = document.createElement("span");
          cell.className = "shell-auto-adopt-cell";
          if (index < filled) cell.classList.add("filled");
          indicator.append(cell);
        }
      }
      description.textContent = descriptions[select.value] || "";
    };
    row.append(indicator, control);
    wrap.append(row, description);
    renderSelection();
    return wrap;
  },

  openCollab() {
    this._ensureCollabPane();
    this._renderAgenda();
    this._renderDisagreementList(document.getElementById("shellDisagreementList"));
    const adoptSection = document.getElementById("shellCollabAutoAdopt");
    const adoptControl = document.getElementById("shellCollabAutoAdoptControl");
    adoptControl.replaceChildren();
    const adopt = this._autoAdoptControl();
    if (adopt) adoptControl.append(adopt);
    adoptSection.hidden = !adopt;
    document.getElementById("shellCollabOverlay").hidden = false;
    document.getElementById("shellCollabPane").hidden = false;
    // The page insets beside the pane instead of being covered by it.
    document.body.classList.add("shell-pane-open-left");
  },

  // ---- connections: the right-hand pane -----------------------------

  _connReady: false,
  _sharingRefreshTimer: null,
  _sharing: { people: [], channels: [] },
  _channelCatalog: { types: [], channels: [] },

  _topic() {
    return this._options.topicUuid ? this._options.topicUuid() : "";
  },

  _ensureConnectionsPane() {
    if (this._connReady) return;
    const host = document.createElement("div");
    host.innerHTML = [
      '<div id="shellConnOverlay" class="shell-pane-overlay" hidden></div>',
      '<aside id="shellConnPane" class="shell-pane shell-pane-right" hidden>',
      '<div class="shell-pane-header">',
      "<strong>People and channels</strong>",
      '<button type="button" id="shellConnCloseBtn" class="shell-pane-close" aria-label="Close">&times;</button>',
      "</div>",
      '<div class="shell-pane-section">',
      "<h3>People</h3>",
      '<div id="shellPeersList" class="shell-peers-list"></div>',
      "</div>",
      '<div class="shell-pane-section">',
      "<h3>Channels</h3>",
      '<div id="shellConnTargetList" class="shell-target-list"></div>',
      '<div id="shellChannelActions" class="shell-row shell-channel-actions">',
      '<button type="button" id="shellUseTokenBtn">Use a token</button>',
      '<button type="button" id="shellManageChannelsBtn">Manage channels</button>',
      "</div>",
      '<fieldset id="shellTokenFieldset" class="shell-token-form" hidden>',
      "<legend>Use a token</legend>",
      '<label for="shellTokenInput">Invite or pairing token</label>',
      '<input id="shellTokenInput" placeholder="Paste a token">',
      '<div class="shell-row">',
      '<button type="button" id="shellConnectBtn" class="primary">Connect</button>',
      '<button type="button" id="shellCancelTokenBtn">Cancel</button>',
      "</div>",
      '<p id="shellTokenNote" class="shell-note"></p>',
      "</fieldset>",
      '<p id="shellTargetsNote" class="shell-note"></p>',
      "</div>",
      "</aside>",
      '<dialog id="shellChannelManager" class="shell-dialog">',
      '<div class="shell-pane-header">',
      "<strong>Manage Channels</strong>",
      '<button type="button" id="shellChannelManagerClose" class="shell-pane-close" aria-label="Close">&times;</button>',
      "</div>",
      // The header is full-bleed and sticky; everything below it is inset,
      // so no row runs into the dialog's own border. .shell-pairing-section
      // already assumes this container exists - it drops its own horizontal
      // padding to avoid doubling up.
      '<div class="shell-dialog-body">',
      '<p class="shell-note">Channels belong to this session and are available to every topic.</p>',
      '<p id="shellIdentityHomeNote" class="shell-note"></p>',
      '<div id="shellManagedChannelList" class="shell-target-list"></div>',
      '<button type="button" id="shellAddChannelBtn" class="ui-button">+ Add channel</button>',
      '<fieldset id="shellChannelForm" class="shell-target-form" hidden>',
      "<legend>Add channel</legend>",
      '<label for="shellChannelType">Channel type</label>',
      '<select id="shellChannelType" class="ui-select"></select>',
      '<div id="shellChannelFields" class="shell-target-form-full"></div>',
      '<div class="shell-row shell-target-form-full">',
      '<button type="button" id="shellTestChannelBtn">Test</button>',
      '<button type="button" id="shellSaveChannelBtn" class="primary">Save</button>',
      '<button type="button" id="shellCancelChannelBtn">Cancel</button>',
      "</div>",
      "</fieldset>",
      // Pairing lives here, beside the channel list, because that is what it
      // is about: a pairing token carries this client's channels, not the
      // board that happens to be open. It is deliberately not a channel row
      // action - an invite token connects you to another person, a pairing
      // token makes a second machine into *you*, and side by side as row
      // actions those read as variations of one thing.
      '<div class="shell-pane-section shell-pairing-section">',
      "<h3>My other clients</h3>",
      '<p class="shell-note">A paired client is not another person: it' +
        " publishes as you, over the channels above, and everything you own" +
        " follows it.</p>",
      '<button type="button" id="shellPairClientBtn">Generate pairing token</button>',
      '<p class="shell-note">Paste it into the other client under' +
        " &quot;Use a token&quot;. Pair a client that has nothing on it yet -" +
        " content already there cannot be merged, only chosen between." +
        " Generating a token again later adds any new channels to the ones" +
        " the paired client already has.</p>",
      '<p id="shellPairingNote" class="shell-note"></p>',
      "</div>",
      '<p id="shellChannelManagerNote" class="shell-note"></p>',
      "</div>",
      "</dialog>",
    ].join("");
    document.body.append(...host.children);
    this._connReady = true;

    document.getElementById("shellConnCloseBtn").onclick = () => this.closeConnections();
    document.getElementById("shellConnOverlay").onclick = () => this.closeConnections();
    document.getElementById("shellUseTokenBtn").onclick = () => this._toggleTokenForm(true);
    document.getElementById("shellCancelTokenBtn").onclick = () => this._toggleTokenForm(false);
    document.getElementById("shellManageChannelsBtn").onclick = () => this._openChannelManager();
    document.getElementById("shellChannelManagerClose").onclick = () =>
      document.getElementById("shellChannelManager").close();
    document.getElementById("shellAddChannelBtn").onclick = () => this._toggleChannelForm(true);
    document.getElementById("shellCancelChannelBtn").onclick = () => this._toggleChannelForm(false);
    document.getElementById("shellChannelType").onchange = () => this._renderChannelFields();
    document.getElementById("shellTestChannelBtn").onclick = () => this._testChannelForm();
    document.getElementById("shellSaveChannelBtn").onclick = () => this._saveChannel();
    document.getElementById("shellConnectBtn").onclick = () => this._connect();
    document.getElementById("shellPairClientBtn").onclick = () => this._copyPairingToken();
  },

  async _copyPairingToken() {
    try {
      const token = await this._post("/api/core/siblings/pairing", {});
      await navigator.clipboard.writeText(btoa(JSON.stringify(token)));
      this._note(
        "shellPairingNote",
        "Pairing token copied. It carries this client's identity and every" +
          " topic you own, so treat it like the key to everything.",
      );
    } catch (error) {
      this._note("shellPairingNote", error.message);
    }
  },

  async _acceptPairingToken(token, field) {
    try {
      await this._post("/api/core/siblings/pairing/accept", { token });
      field.value = "";
      this._note(
        "shellTokenNote",
        "Paired. This client now publishes as the same participant as the" +
          " one that issued the token.",
      );
      await this._changed();
      this._toggleTokenForm(false);
      await this._loadSharing();
    } catch (error) {
      this._note("shellTokenNote", error.message);
    }
  },

  closeConnections() {
    const pane = document.getElementById("shellConnPane");
    const overlay = document.getElementById("shellConnOverlay");
    if (pane) pane.hidden = true;
    if (overlay) overlay.hidden = true;
    document.body.classList.remove("shell-pane-open-right");
  },

  _note(id, message) {
    document.getElementById(id).textContent = message;
  },

  async openConnectionPanel() {
    this._ensureConnectionsPane();

    // With no topic there is nothing to share yet, so the one thing the pane
    // can still do - join someone else's topic - is opened straight away.
    this._toggleTokenForm(!this._topic());
    document.getElementById("shellConnOverlay").hidden = false;
    document.getElementById("shellConnPane").hidden = false;
    document.body.classList.add("shell-pane-open-right");
    try {
      await this._loadSharing();
    } catch (error) {
      this._note("shellTargetsNote", error.message);
    }
  },

  async _loadSharing() {
    const topic = this._topic();
    if (!topic) {
      this._sharing = { people: [], channels: [] };
      this._renderPeersList();
      this._renderConnTargets();
      this._note("shellTargetsNote", "No topic yet. Paste an invite token to join one.");
      return;
    }
    try {
      const response = await fetch(`/api/core/topics/${encodeURIComponent(topic)}/sharing`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.reason || "Could not read sharing.");
      this._sharing = payload;
      if (this._topic() === topic) {
        this._headerSharingTopic = topic;
        this._renderSharingHeader(payload.people || []);
      }
      this._note("shellTargetsNote", "");
    } catch (error) {
      this._sharing = { people: [], channels: [] };
      this._note("shellTargetsNote", error.message);
    }
    this._renderPeersList();
    this._renderConnTargets();
  },

  _renderPeersList() {
    const list = document.getElementById("shellPeersList");
    if (!list) return;
    list.replaceChildren();
    const peers = this._sharing.people || [];
    if (!peers.length) {
      const empty = document.createElement("p");
      empty.className = "shell-note";
      empty.textContent = "No one else is on this topic yet.";
      list.append(empty);
      return;
    }
    for (const info of peers) {
      const addr = info.address || "";
      const online = !info.status || info.status.state !== "offline";
      const row = document.createElement("div");
      row.className = "shell-peer-row";
      const avatar = document.createElement("span");
      avatar.className =
        "header-avatar shell-peer-avatar " + (online ? "status-online" : "status-offline");
      if (info.picture) {
        avatar.style.backgroundImage = 'url("' + info.picture + '")';
      } else {
        const source = info.name || addr.replace(/^relay:/, "");
        avatar.textContent = (source.slice(0, 2) || "?").toUpperCase();
      }
      const name = document.createElement("span");
      name.className = "shell-peer-name";
      name.textContent = info.name || addr;
      const status = document.createElement("span");
      status.className = "shell-note shell-peer-status";
      status.textContent =
        (online ? "Online" : "Offline") + (info.channel ? " (" + info.channel + ")" : "");
      row.append(avatar, name, status);
      list.append(row);
    }
  },

  async _setTopicChannel(channelRef, action) {
    const topic = this._topic();
    if (!topic) throw new Error("Select a topic first.");
    await this._post(`/api/core/topics/${encodeURIComponent(topic)}/channels`, {
      channel_ref: channelRef,
      action,
    });
    await this._changed();
    await this._loadSharing();
  },

  async _copyToken(channelRef = "http", channelName = "Direct") {
    const topic = this._topic();
    if (!topic) {
      this._note("shellTargetsNote", "Select a topic before creating a token.");
      return;
    }
    try {
      const token = await this._post("/api/core/invitations", {
        topic_uuid: topic,
        channel_ref: channelRef,
      });
      await navigator.clipboard.writeText(btoa(JSON.stringify(token)));
      // _loadSharing clears this note on success, so saying it first said it
      // to nobody: the button looked like it had done nothing at all.
      await this._loadSharing();
      this._note("shellTargetsNote", `${channelName} invite token copied to your clipboard.`);
    } catch (error) {
      this._note("shellTargetsNote", error.message);
    }
  },

  async _connect() {
    const field = document.getElementById("shellTokenInput");
    let token;
    try {
      token = JSON.parse(atob(field.value.trim()));
    } catch (error) {
      this._note("shellTokenNote", "That is not a share token.");
      return;
    }
    // One paste field, two kinds. The server refuses each token on the other
    // path, so routing here is a convenience rather than the safeguard.
    if (token.token_kind === "pairing") {
      await this._acceptPairingToken(token, field);
      return;
    }
    // Core serializes token_version; the channel descriptor carries its own
    // descriptor_version. Testing the wrong one rejects every valid token.
    if (
      token.token_version !== 3 ||
      !Array.isArray(token.topic_uuids) ||
      !token.topic_uuids.length
    ) {
      this._note("shellTokenNote", "Unrecognized token version.");
      return;
    }
    try {
      await this._post("/api/core/invitations/accept", { token });
      field.value = "";
      this._note("shellTokenNote", "Connected.");
      await this._changed();
      this._toggleTokenForm(false);
      await this._loadSharing();
    } catch (error) {
      this._note("shellTokenNote", error.message);
    }
  },

  _targetStatus(label, className = "") {
    const badge = document.createElement("span");
    badge.className = "shell-channel-badge " + className;
    badge.textContent = label;
    return badge;
  },

  _channelAction(label, action, className = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (className) button.className = className;
    button.onclick = action;
    return button;
  },

  async _renderConnTargets() {
    const list = document.getElementById("shellConnTargetList");
    if (!list) return;
    list.replaceChildren();
    const channels = this._sharing.channels || [];
    if (!channels.length) {
      const empty = document.createElement("p");
      empty.className = "shell-note";
      empty.textContent = this._topic()
        ? "No channels are available."
        : "Channels appear once you have a topic to share.";
      list.append(empty);
      return;
    }
    for (const channel of channels) {
      const row = document.createElement("div");
      row.className = "shell-target-row";
      const identity = document.createElement("div");
      identity.className = "shell-target-identity";
      const name = document.createElement("span");
      name.className = "shell-target-name";
      name.textContent = channel.name;
      const kind = document.createElement("span");
      kind.className = "shell-note";
      kind.textContent = channel.description || channel.type;
      identity.append(name, kind);
      const statuses = document.createElement("div");
      statuses.className = "shell-channel-statuses";
      statuses.append(
        this._targetStatus(
          channel.available ? "Available" : "Unavailable",
          channel.available ? "is-available" : "",
        ),
      );
      if (channel.in_use) {
        statuses.append(this._targetStatus("In use", "is-in-use"));
      }
      const actions = document.createElement("div");
      actions.className = "shell-target-actions";
      if (channel.in_use) {
        actions.append(
          this._channelAction("Stop using", async () => {
            try {
              await this._setTopicChannel(channel.ref, "stop");
              this._note("shellTargetsNote", `${channel.name} is no longer used for this topic.`);
            } catch (error) {
              this._note("shellTargetsNote", error.message);
            }
          }),
        );
      } else {
        actions.append(
          this._channelAction("Use for this topic", async () => {
            try {
              await this._setTopicChannel(channel.ref, "use");
              this._note("shellTargetsNote", `${channel.name} is now in use for this topic.`);
            } catch (error) {
              this._note("shellTargetsNote", error.message);
            }
          }),
        );
      }
      // Only for a channel this topic is actually on. Inviting someone to a
      // channel is a decision to publish here, and that decision is the
      // "Use for this topic" above - taken first, and revocable from the
      // same row.
      if (channel.in_use) {
        actions.append(
          this._channelAction(
            "Get invitation",
            () => this._copyToken(channel.ref, channel.name),
            "primary",
          ),
        );
      }
      row.append(identity, statuses, actions);
      list.append(row);
    }
  },

  _toggleTokenForm(show) {
    const fieldset = document.getElementById("shellTokenFieldset");
    fieldset.hidden = !show;
    document.getElementById("shellUseTokenBtn").hidden = !!show;
    if (show) {
      document.getElementById("shellTokenInput").value = "";
      this._note("shellTokenNote", "");
      document.getElementById("shellTokenInput").focus();
    }
  },

  async _openChannelManager() {
    try {
      const response = await fetch("/api/core/channels");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.reason || "Could not read channels.");
      this._channelCatalog = payload;
      this._renderManagedChannels();
      this._populateChannelTypes();
      this._toggleChannelForm(false);
      this._note("shellChannelManagerNote", "");
      document.getElementById("shellChannelManager").showModal();
    } catch (error) {
      this._note("shellTargetsNote", error.message);
    }
  },

  _renderManagedChannels() {
    const list = document.getElementById("shellManagedChannelList");
    list.replaceChildren();
    const homeRef = this._channelCatalog.identity_channel_ref || "";
    const home = (this._channelCatalog.channels || []).find((channel) => channel.ref === homeRef);
    this._note(
      "shellIdentityHomeNote",
      home
        ? `Your identity's home channel is ${home.name}.`
        : "Your identity has no home channel. Choose one before inviting.",
    );
    for (const channel of this._channelCatalog.channels || []) {
      const row = document.createElement("div");
      row.className = "shell-target-row";
      const identity = document.createElement("div");
      identity.className = "shell-target-identity";
      const name = document.createElement("span");
      name.className = "shell-target-name";
      name.textContent = channel.name;
      const kind = document.createElement("span");
      kind.className = "shell-note";
      kind.textContent = channel.description || channel.type;
      identity.append(name, kind);
      const status = document.createElement("div");
      status.className = "shell-channel-statuses";
      status.append(
        this._targetStatus(
          channel.available ? "Available" : "Unavailable",
          channel.available ? "is-available" : "",
        ),
      );
      if (channel.identity_home) {
        status.append(this._targetStatus("Identity home", "is-in-use"));
      }
      const assigned = channel.assigned_topics || [];
      if (assigned.length) {
        const usage = document.createElement("span");
        usage.className = "shell-note";
        usage.textContent = `Used by: ${assigned.map((topic) => topic.title).join(", ")}`;
        identity.append(usage);
      }
      const actions = document.createElement("div");
      actions.className = "shell-target-actions";
      if (!channel.identity_home) {
        actions.append(
          this._channelAction("Use for my identity", () => {
            const move = () => this._setIdentityHome(channel);
            if (!homeRef) {
              move();
              return;
            }
            confirmAction(
              `Move your identity home to ${channel.name}?`,
              "People invited through the previous identity channel will" +
                " no longer see current profile data.",
              move,
            );
          }),
        );
      }
      if (assigned.length) {
        actions.append(
          this._channelAction(
            "Stop all use",
            () =>
              confirmAction(
                `Stop all use of ${channel.name}?`,
                "This removes the identity home and every topic assignment." +
                  " The channel remains available.",
                () => this._stopChannel(channel),
              ),
            "danger",
          ),
        );
      }
      if (channel.removable) {
        actions.append(
          this._channelAction(
            "Delete",
            () =>
              confirmAction(
                `Delete ${channel.name}?`,
                channel.identity_home
                  ? "This is your identity's home. Deleting it breaks previous" +
                      " invitations and removes every topic using the channel."
                  : "Deleting it removes every topic using the channel.",
                () => this._deleteChannel(channel),
              ),
            "danger",
          ),
        );
      }
      row.append(identity, status, actions);
      list.append(row);
    }
  },

  _populateChannelTypes() {
    const select = document.getElementById("shellChannelType");
    SovereignUI.selectOptions(
      select,
      (this._channelCatalog.types || [])
        .filter((item) => item.action === "configure")
        .map((type) => [`${type.kind}:${type.id}`, type.name]),
    );
    this._renderChannelFields();
  },

  _selectedChannelType() {
    const value = document.getElementById("shellChannelType").value;
    return (this._channelCatalog.types || []).find((item) => `${item.kind}:${item.id}` === value);
  },

  _renderChannelFields() {
    const host = document.getElementById("shellChannelFields");
    host.replaceChildren();
    const type = this._selectedChannelType();
    for (const field of (type && type.fields) || []) {
      const label = document.createElement("label");
      label.textContent = field.label;
      const input = document.createElement("input");
      input.dataset.channelField = field.name;
      input.type = field.type || "text";
      input.required = !!field.required;
      if (field.default !== undefined) input.value = field.default;
      label.append(input);
      host.append(label);
    }
  },

  _toggleChannelForm(show) {
    const form = document.getElementById("shellChannelForm");
    form.hidden = !show;
    document.getElementById("shellAddChannelBtn").hidden = !!show;
    if (show) {
      this._populateChannelTypes();
      const first = document.querySelector("[data-channel-field]");
      if (first) first.focus();
    }
  },

  _channelFormValues() {
    const type = this._selectedChannelType();
    if (!type) throw new Error("Choose a channel type.");
    const values = { kind: type.kind, type: type.id };
    for (const input of document.querySelectorAll("[data-channel-field]")) {
      if (input.required && !input.value.trim()) {
        throw new Error(`${input.parentElement.firstChild.textContent} is required.`);
      }
      if (input.value) {
        values[input.dataset.channelField] =
          input.type === "number" ? Number(input.value) : input.value;
      }
    }
    return values;
  },

  async _testChannelForm() {
    try {
      const values = this._channelFormValues();
      this._note("shellChannelManagerNote", `Testing ${values.name || "channel"}...`);
      await this._post("/api/core/channels/test", values);
      this._note("shellChannelManagerNote", "Channel is reachable.");
    } catch (error) {
      this._note("shellChannelManagerNote", error.message);
    }
  },

  async _saveChannel() {
    try {
      const values = this._channelFormValues();
      this._note("shellChannelManagerNote", "Verifying the channel...");
      const saved = await this._post("/api/core/channels", values);
      this._toggleChannelForm(false);
      await this._refreshChannelManager();
      await this._loadSharing();
      const savedRef = `${values.kind}:${saved.value || ""}`;
      const becameIdentityHome = this._channelCatalog.identity_channel_ref === savedRef;
      this._note(
        "shellChannelManagerNote",
        becameIdentityHome
          ? `${values.name} added and set as your identity home.`
          : `${values.name} added.`,
      );
      await this._changed();
    } catch (error) {
      this._note("shellChannelManagerNote", error.message);
    }
  },

  async _deleteChannel(channel) {
    try {
      await this._post("/api/core/channels/delete", { channel_ref: channel.ref });
      await this._refreshChannelManager();
      await this._loadSharing();
      this._note("shellChannelManagerNote", `${channel.name} deleted.`);
      await this._changed();
    } catch (error) {
      this._note("shellChannelManagerNote", error.message);
    }
  },

  async _stopChannel(channel) {
    try {
      await this._post("/api/core/channels/stop", { channel_ref: channel.ref });
      await this._refreshChannelManager();
      await this._loadSharing();
      this._note("shellChannelManagerNote", `${channel.name} is no longer in use.`);
      await this._changed();
    } catch (error) {
      this._note("shellChannelManagerNote", error.message);
    }
  },

  async _setIdentityHome(channel) {
    const topic = this._channelCatalog.identity_topic_uuid || "";
    if (!topic) {
      this._note("shellChannelManagerNote", "Identity topic not found.");
      return;
    }
    try {
      await this._post(`/api/core/topics/${encodeURIComponent(topic)}/channels`, {
        channel_ref: channel.ref,
        action: "use",
      });
      await this._refreshChannelManager();
      await this._loadSharing();
      this._note("shellChannelManagerNote", `${channel.name} is now your identity's home channel.`);
      await this._changed();
    } catch (error) {
      this._note("shellChannelManagerNote", error.message);
    }
  },

  async _refreshChannelManager() {
    const response = await fetch("/api/core/channels");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.reason || "Could not read channels.");
    this._channelCatalog = payload;
    this._renderManagedChannels();
  },

  async _changed() {
    if (this._options.onChanged) await this._options.onChanged();
  },
});
