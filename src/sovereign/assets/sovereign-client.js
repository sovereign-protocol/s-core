/* Headless browser binding for Core-owned generic scalar nodes. */
(function () {
  "use strict";

  class CoreBindingClient {
    constructor(baseUrl, capability, pollInterval) {
      this.baseUrl = baseUrl.replace(/\/$/, "");
      this.capability = capability;
      this.pollInterval = pollInterval;
    }

    async request(nodeUuid, values, method = "GET") {
      const path = `${this.baseUrl}/api/core/bindings/${encodeURIComponent(nodeUuid)}`;
      const options = {
        method,
        headers: {"X-Sovereign-Capability": this.capability},
      };
      let url = path;
      if (method === "GET") {
        url += `?${new URLSearchParams(values)}`;
      } else {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(values);
      }
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.status === "error") {
        throw new Error(payload.reason || `Core request failed (${response.status})`);
      }
      return payload;
    }

    bindField(element, options = {}) {
      if (!(element instanceof HTMLElement)) {
        throw new TypeError("bindField needs an input or textarea element");
      }
      const topicUuid = String(options.topicUuid || "");
      const nodeUuid = String(options.nodeUuid || "");
      const field = String(options.field || "");
      if (!topicUuid || !nodeUuid || !field) {
        throw new Error("bindField needs topicUuid, nodeUuid, and field");
      }
      if (typeof SovereignUI === "undefined") {
        throw new Error("bindField needs Core shared.js loaded first");
      }

      const parent = element.parentNode;
      const nextSibling = element.nextSibling;
      const surface = document.createElement("div");
      surface.className = `ui-bound-field ${options.className || ""}`.trim();
      parent.insertBefore(surface, element);
      surface.append(element);
      const reactions = document.createElement("div");
      reactions.className = "ui-bound-field-reactions";
      surface.append(reactions);

      const state = {
        confirmedValue: element.value,
        pendingValue: element.value,
        contentHash: "",
        dirty: false,
        transition: null,
        adoptionPolicy: null,
      };
      let disposed = false;
      let commitTimer = null;
      let refreshTimer = null;
      let committing = false;

      const scheduleRefresh = () => {
        window.clearTimeout(refreshTimer);
        if (!disposed) refreshTimer = window.setTimeout(refresh, this.pollInterval);
      };

      const render = (payload) => {
        state.confirmedValue = payload.value == null ? "" : String(payload.value);
        state.contentHash = payload.content_hash || "";
        state.transition = payload.transition || null;
        state.adoptionPolicy = payload.adoption_policy || null;
        if (!state.dirty && document.activeElement !== element) {
          element.value = state.confirmedValue;
          state.pendingValue = state.confirmedValue;
        }
        SovereignUI.decorateTransition(surface, state.transition);
        SovereignUI.decorateAdoptionPolicy(surface, state.adoptionPolicy, {
          transition: state.transition,
        });
        reactions.replaceChildren();
        const control = SovereignUI.reactionControl({
          info: state.transition,
          density: "inline",
          onReact: async (choice) => {
            await this.request(nodeUuid, {
              operation: "react",
              topic_uuid: topicUuid,
              source_addr: choice.peerAddr,
              reaction: choice.action,
              absent: choice.absent,
            }, "POST");
            state.dirty = false;
            await refresh();
          },
        });
        if (control) reactions.append(control);
        options.onStateChange?.({...state});
      };

      const refresh = async () => {
        if (disposed) return;
        try {
          const payload = await this.request(nodeUuid, {
            operation: "read", topic_uuid: topicUuid, field,
          });
          render(payload);
          options.onError?.(null);
        } catch (error) {
          options.onError?.(error);
        } finally {
          scheduleRefresh();
        }
      };

      const commit = async () => {
        window.clearTimeout(commitTimer);
        if (disposed || committing || !state.dirty) return;
        committing = true;
        try {
          await this.request(nodeUuid, {
            operation: "write",
            topic_uuid: topicUuid,
            field,
            value: state.pendingValue,
            expected_content_hash: state.contentHash,
          }, "POST");
          state.dirty = false;
          await refresh();
        } catch (error) {
          options.onError?.(error);
        } finally {
          committing = false;
        }
      };

      const onInput = () => {
        state.pendingValue = element.value;
        state.dirty = state.pendingValue !== state.confirmedValue;
        options.onStateChange?.({...state});
        if (Number.isFinite(options.debounceMs)) {
          window.clearTimeout(commitTimer);
          commitTimer = window.setTimeout(commit, Math.max(0, options.debounceMs));
        }
      };
      element.addEventListener("input", onInput);
      element.addEventListener("blur", commit);
      refresh();

      return {
        state,
        refresh,
        commit,
        unbind() {
          if (disposed) return;
          disposed = true;
          window.clearTimeout(commitTimer);
          window.clearTimeout(refreshTimer);
          element.removeEventListener("input", onInput);
          element.removeEventListener("blur", commit);
          SovereignUI.decorateTransition(surface, null);
          SovereignUI.decorateAdoptionPolicy(surface, null);
          if (nextSibling && nextSibling.parentNode === parent) {
            parent.insertBefore(element, nextSibling);
          } else {
            parent.append(element);
          }
          surface.remove();
        },
      };
    }
  }

  window.SovereignClient = Object.freeze({
    async connect(options = {}) {
      const baseUrl = String(options.baseUrl || "").trim();
      const capability = String(options.capability || "").trim();
      if (!baseUrl || !capability) {
        throw new Error("SovereignClient.connect needs baseUrl and capability");
      }
      return new CoreBindingClient(
        baseUrl,
        capability,
        Number(options.pollInterval) || 1500,
      );
    },
  });
})();
