(function () {
  "use strict";

  if (window.__pyganiniTemplateInspectorCleanup) {
    window.__pyganiniTemplateInspectorCleanup();
  }
  if (window.__pyganiniTemplateInspectorPendingCleanup) {
    window.__pyganiniTemplateInspectorPendingCleanup();
  }

  function start() {
    if (!document.body) {
      var pendingStart = function () {
        if (window.__pyganiniTemplateInspectorPendingCleanup === pendingCleanup) {
          delete window.__pyganiniTemplateInspectorPendingCleanup;
        }
        start();
      };
      var pendingCleanup = function () {
        document.removeEventListener("DOMContentLoaded", pendingStart);
        if (window.__pyganiniTemplateInspectorPendingCleanup === pendingCleanup) {
          delete window.__pyganiniTemplateInspectorPendingCleanup;
        }
      };
      window.__pyganiniTemplateInspectorPendingCleanup = pendingCleanup;
      document.addEventListener("DOMContentLoaded", pendingStart, {once: true});
      return;
    }
    if (window.__pyganiniTemplateInspectorCleanup) {
      window.__pyganiniTemplateInspectorCleanup();
    }

    var owned = [];
    var listeners = [];
    var observer = null;
    var frame = 0;
    var pendingTimeouts = [];
    var drawing = false;
    var redrawRequested = false;
    var active = true;
    var selectedStart = null;
    var selectNextRequested = false;
    var currentUnits = [];
    var visibility = "all";
    var storageKey = "pyganini.template-inspector.visibility.v1";
    var cleanup;
    var colors = {
      layout: "#7c3aed",
      page: "#0284c7",
      fragment: "#059669",
      component: "#d97706"
    };

    try {
      visibility = window.localStorage.getItem(storageKey) === "off" ? "off" : "all";
    } catch (_) {
      visibility = "all";
    }

    function own(node) {
      node.setAttribute("data-pyganini-template-inspector", "");
      owned.push(node);
      return node;
    }

    function listen(target, name, handler, options) {
      target.addEventListener(name, handler, options);
      listeners.push([target, name, handler, options]);
    }

    function encode(value) {
      var allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/:._~{}";
      return Array.from(new TextEncoder().encode(value)).map(function (byte) {
        return allowed.indexOf(String.fromCharCode(byte)) >= 0
          ? String.fromCharCode(byte)
          : "%" + byte.toString(16).toUpperCase().padStart(2, "0");
      }).join("");
    }

    function decode(value) {
      if (!value || !/^(?:[A-Za-z0-9\/:._~{}]|%[0-9A-F]{2})+$/.test(value)) {
        return null;
      }
      try {
        var decoded = decodeURIComponent(value);
        return encode(decoded) === value ? decoded : null;
      } catch (_) {
        return null;
      }
    }

    function kindSurfaceMatches(values) {
      var accepted = {
        page: ["page", "action-page", "root-error-page", "matched-error-page"],
        layout: ["page", "action-page", "root-error-page", "matched-error-page"],
        fragment: ["fragment", "action-fragment", "embedded-fragment", "root-error-fragment", "matched-error-fragment"],
        component: ["component"]
      };
      return accepted[values[0]].indexOf(values[1]) >= 0;
    }

    function rotateRight(value, count) {
      return (value >>> count) | (value << (32 - count));
    }

    function sha256(input) {
      var constants = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
      ];
      var state = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
      ];
      var size = Math.ceil((input.length + 9) / 64) * 64;
      var data = new Uint8Array(size);
      data.set(input);
      data[input.length] = 0x80;
      var view = new DataView(data.buffer);
      var bitLength = input.length * 8;
      view.setUint32(size - 8, Math.floor(bitLength / 0x100000000));
      view.setUint32(size - 4, bitLength >>> 0);
      var words = new Uint32Array(64);
      for (var offset = 0; offset < size; offset += 64) {
        var index;
        for (index = 0; index < 16; index += 1) {
          words[index] = view.getUint32(offset + index * 4);
        }
        for (index = 16; index < 64; index += 1) {
          var lower = rotateRight(words[index - 15], 7) ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >>> 3);
          var upper = rotateRight(words[index - 2], 17) ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >>> 10);
          words[index] = (words[index - 16] + lower + words[index - 7] + upper) >>> 0;
        }
        var working = state.slice();
        for (index = 0; index < 64; index += 1) {
          var sumOne = rotateRight(working[4], 6) ^ rotateRight(working[4], 11) ^ rotateRight(working[4], 25);
          var choice = (working[4] & working[5]) ^ (~working[4] & working[6]);
          var temporaryOne = (working[7] + sumOne + choice + constants[index] + words[index]) >>> 0;
          var sumZero = rotateRight(working[0], 2) ^ rotateRight(working[0], 13) ^ rotateRight(working[0], 22);
          var majority = (working[0] & working[1]) ^ (working[0] & working[2]) ^ (working[1] & working[2]);
          var temporaryTwo = (sumZero + majority) >>> 0;
          working = [
            (temporaryOne + temporaryTwo) >>> 0,
            working[0], working[1], working[2],
            (working[3] + temporaryOne) >>> 0,
            working[4], working[5], working[6]
          ];
        }
        state = state.map(function (value, stateIndex) {
          return (value + working[stateIndex]) >>> 0;
        });
      }
      return state.map(function (value) {
        return value.toString(16).padStart(8, "0");
      }).join("");
    }

    function markerId(values) {
      var encoder = new TextEncoder();
      var chunks = [];
      var size = 0;
      values.forEach(function (value) {
        var raw = encoder.encode(value);
        var prefix = encoder.encode(String(raw.length) + ":");
        chunks.push(prefix, raw);
        size += prefix.length + raw.length;
      });
      var input = new Uint8Array(size);
      var offset = 0;
      chunks.forEach(function (chunk) {
        input.set(chunk, offset);
        offset += chunk.length;
      });
      return "u" + sha256(input);
    }

    var startPattern = /^pyganini:start id=(u[0-9a-f]{64}) kind=(page|layout|fragment|component) surface=(page|action%2Dpage|fragment|action%2Dfragment|embedded%2Dfragment|root%2Derror%2Dpage|root%2Derror%2Dfragment|matched%2Derror%2Dpage|matched%2Derror%2Dfragment|component) route=([^ ]+) template=([^ ]+) source=([^ ]+) declaration=([^ ]+) owner=([^ ]+) handler=([^ ]+) mount=([^ ]+)(?: label=([^ ]+))?$/;
    var endPattern = /^pyganini:end id=(u[0-9a-f]{64})$/;

    async function parse() {
      var walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
      var stack = [];
      var units = [];
      var node;
      while ((node = walker.nextNode())) {
        var startMatch = startPattern.exec(node.data);
        if (startMatch) {
          var values = startMatch.slice(2).map(function (value) {
            return value === undefined ? undefined : decode(value);
          });
          if (values.some(function (value) { return value === null; }) ||
              (values[0] === "component") !== (values[9] !== undefined && values[9] !== null)) {
            continue;
          }
          if (!kindSurfaceMatches(values)) { continue; }
          var identityValues = values.slice(0, 9);
          if (values[9] !== undefined) { identityValues.push(values[9]); }
          if (await markerId(identityValues) !== startMatch[1]) { continue; }
          stack.push({id: startMatch[1], start: node, values: values});
          continue;
        }
        var endMatch = endPattern.exec(node.data);
        if (!endMatch) {
          continue;
        }
        if (!stack.length) {
          continue;
        }
        if (stack[stack.length - 1].id !== endMatch[1]) {
          stack = [];
          continue;
        }
        var entry = stack.pop();
        entry.end = node;
        units.push(entry);
      }
      units.sort(function (a, b) {
        return a.start.compareDocumentPosition(b.start) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
      });
      return units;
    }

    function removeVisuals() {
      owned.slice().forEach(function (node) {
        if (node !== controls && node.parentNode) {
          listeners = listeners.filter(function (entry) {
            if (entry[0] !== node) { return true; }
            entry[0].removeEventListener(entry[1], entry[2], entry[3]);
            return false;
          });
          node.parentNode.removeChild(node);
          owned.splice(owned.indexOf(node), 1);
        }
      });
    }

    function detail(unit) {
      var names = ["kind", "surface", "route", "template", "source", "declaration", "owner", "handler", "mount", "label"];
      var panel = own(document.createElement("div"));
      panel.style.cssText = "position:fixed;box-sizing:border-box;z-index:2147483646;max-width:min(520px,calc(100vw - 16px));max-height:calc(100vh - 16px);padding:8px;background:#111827;color:white;font:12px/1.4 ui-monospace,monospace;overflow:auto;overflow-wrap:anywhere;border-radius:4px;";
      names.forEach(function (name, index) {
        if (unit.values[index] !== undefined) {
          var row = document.createElement("div");
          row.textContent = name + ": " + unit.values[index];
          panel.appendChild(row);
        }
      });
      var clipboard = null;
      var writeText = null;
      try {
        clipboard = navigator.clipboard;
        writeText = clipboard && clipboard.writeText;
      } catch (_) {
        clipboard = null;
        writeText = null;
      }
      if (clipboard && typeof writeText === "function") {
        var copy = document.createElement("button");
        copy.type = "button";
        copy.textContent = "Copy source path";
        listen(copy, "click", function () {
          try {
            Promise.resolve(writeText.call(clipboard, unit.values[4])).catch(function () {});
          } catch (_) {}
        });
        panel.appendChild(copy);
      }
      return panel;
    }

    function placeDetail(panel, box) {
      panel.style.left = "8px";
      panel.style.top = "8px";
      document.body.appendChild(panel);
      var panelBox = panel.getBoundingClientRect();
      panel.style.left = Math.max(8, Math.min(box.left, window.innerWidth - panelBox.width - 8)) + "px";
      panel.style.top = Math.max(8, Math.min(box.bottom + 4, window.innerHeight - panelBox.height - 8)) + "px";
    }

    function bounds(unit) {
      if (!unit.start.isConnected || !unit.end.isConnected) {
        return null;
      }
      var range = document.createRange();
      range.setStartAfter(unit.start);
      range.setEndBefore(unit.end);
      var rects = Array.prototype.filter.call(range.getClientRects(), function (rect) {
        return rect.width > 0 && rect.height > 0;
      });
      if (!rects.length) {
        return null;
      }
      return rects.reduce(function (box, rect) {
        return {
          left: Math.min(box.left, rect.left),
          top: Math.min(box.top, rect.top),
          right: Math.max(box.right, rect.right),
          bottom: Math.max(box.bottom, rect.bottom)
        };
      }, {left: rects[0].left, top: rects[0].top, right: rects[0].right, bottom: rects[0].bottom});
    }

    async function redraw() {
      removeVisuals();
      var units = await parse();
      if (!active) { return; }
      currentUnits = units.map(function (unit) {
        var box = bounds(unit);
        if (!box) { return null; }
        box = {
          left: Math.max(0, Math.min(window.innerWidth, box.left)),
          top: Math.max(0, Math.min(window.innerHeight, box.top)),
          right: Math.max(0, Math.min(window.innerWidth, box.right)),
          bottom: Math.max(0, Math.min(window.innerHeight, box.bottom))
        };
        return box.right > box.left && box.bottom > box.top
          ? {unit: unit, box: box}
          : null;
      }).filter(function (entry) { return entry !== null; });
      if (currentUnits.length && !controls.isConnected) {
        document.body.appendChild(controls);
      } else if (!currentUnits.length && controls.parentNode) {
        controls.parentNode.removeChild(controls);
      }
      if (visibility === "off") {
        selectedStart = null;
        selectNextRequested = false;
        updateButtons();
        return;
      }
      if (selectedStart && !currentUnits.some(function (entry) {
        return entry.unit.start === selectedStart;
      })) {
        selectedStart = null;
      }
      if (selectNextRequested) {
        var selectedIndex = currentUnits.findIndex(function (entry) {
          return entry.unit.start === selectedStart;
        });
        selectedStart = currentUnits.length
          ? currentUnits[(selectedIndex + 1) % currentUnits.length].unit.start
          : null;
        selectNextRequested = false;
      }
      currentUnits.forEach(function (entry) {
        var unit = entry.unit;
        var box = entry.box;
        if (selectedStart && selectedStart !== unit.start) { return; }
        var frameNode = own(document.createElement("div"));
        frameNode.setAttribute("aria-hidden", "true");
        frameNode.style.cssText = "position:fixed;pointer-events:none;box-sizing:border-box;z-index:2147483645;border:2px solid " + colors[unit.values[0]] + ";left:" + box.left + "px;top:" + box.top + "px;width:" + (box.right - box.left) + "px;height:" + (box.bottom - box.top) + "px;";
        document.body.appendChild(frameNode);
        if (selectedStart === unit.start) {
          var panel = detail(unit);
          placeDetail(panel, box);
        } else {
          var handle = own(document.createElement("div"));
          handle.tabIndex = 0;
          handle.setAttribute("aria-label", unit.values[0] + " render unit details");
          handle.style.cssText = "position:fixed;z-index:2147483646;width:12px;height:12px;border-radius:50%;background:" + colors[unit.values[0]] + ";left:" + Math.max(0, box.right - 12) + "px;top:" + Math.max(0, box.top) + "px;";
          document.body.appendChild(handle);
          var showDetail = function () {
            if (handle.__pyganiniDetail) { return; }
            var hoverPanel = detail(unit);
            placeDetail(hoverPanel, box);
            handle.__pyganiniDetail = hoverPanel;
            listen(hoverPanel, "mouseleave", hideDetail);
            listen(hoverPanel, "focusout", hideDetail);
          };
          var hideDetail = function () {
            var timeoutId = window.setTimeout(function () {
              pendingTimeouts = pendingTimeouts.filter(function (pending) {
                return pending !== timeoutId;
              });
              var hoverPanel = handle.__pyganiniDetail;
              if (!hoverPanel) { return; }
              if (handle === document.activeElement ||
                  hoverPanel.contains(document.activeElement) ||
                  handle.matches(":hover") || hoverPanel.matches(":hover")) {
                return;
              }
              if (hoverPanel.parentNode) {
                hoverPanel.parentNode.removeChild(hoverPanel);
              }
              handle.__pyganiniDetail = null;
            }, 0);
            pendingTimeouts.push(timeoutId);
          };
          listen(handle, "mouseenter", showDetail);
          listen(handle, "mouseleave", hideDetail);
          listen(handle, "focus", showDetail);
          listen(handle, "blur", hideDetail);
        }
      });
      updateButtons();
    }

    function schedule() {
      redrawRequested = true;
      if (frame || drawing || !active) { return; }
      frame = window.requestAnimationFrame(async function () {
        frame = 0;
        drawing = true;
        redrawRequested = false;
        await redraw();
        drawing = false;
        if (redrawRequested) { schedule(); }
      });
    }

    var controls = own(document.createElement("div"));
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "Pyganini template inspection");
    controls.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:2147483647;display:flex;flex-wrap:wrap;gap:4px;max-width:calc(100vw - 16px);padding:4px;background:#111827;border-radius:6px;";
    var buttons = {};
    [["all", "All"], ["off", "Off"], ["next", "Next"]].forEach(function (item) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = item[1];
      if (item[0] === "next") { button.setAttribute("aria-label", "Next render unit"); }
      button.style.cssText = "padding:4px 8px;border:2px solid transparent;border-radius:3px;";
      listen(button, "focus", function () { button.style.outline = "2px solid #facc15"; });
      listen(button, "blur", function () { button.style.outline = ""; });
      listen(button, "click", function () {
        if (item[0] === "next") {
          visibility = "all";
          selectNextRequested = true;
        } else {
          visibility = item[0];
          selectedStart = null;
          try { window.localStorage.setItem(storageKey, visibility); } catch (_) {}
        }
        schedule();
      });
      controls.appendChild(button);
      buttons[item[0]] = button;
    });
    function updateButtons() {
      buttons.all.setAttribute("aria-pressed", visibility === "all" && !selectedStart ? "true" : "false");
      buttons.off.setAttribute("aria-pressed", visibility === "off" ? "true" : "false");
      buttons.next.setAttribute("aria-pressed", selectedStart ? "true" : "false");
    }
    ["load", "resize", "htmx:afterSwap", "htmx:afterSettle"].forEach(function (name) {
      listen(window, name, schedule);
    });
    listen(document, "scroll", schedule, true);
    observer = new MutationObserver(function (records) {
      var applicationMutation = records.some(function (record) {
        return Array.prototype.concat.call(Array.from(record.addedNodes), Array.from(record.removedNodes)).some(function (node) {
          return !(node.nodeType === 1 && node.hasAttribute("data-pyganini-template-inspector"));
        });
      });
      if (applicationMutation) {
        schedule();
      }
    });
    observer.observe(document.body, {childList: true, subtree: true});

    cleanup = function () {
      active = false;
      if (observer) { observer.disconnect(); }
      listeners.forEach(function (entry) { entry[0].removeEventListener(entry[1], entry[2], entry[3]); });
      if (frame) { window.cancelAnimationFrame(frame); }
      pendingTimeouts.forEach(function (timeoutId) { window.clearTimeout(timeoutId); });
      pendingTimeouts = [];
      owned.forEach(function (node) { if (node.parentNode) { node.parentNode.removeChild(node); } });
      if (window.__pyganiniTemplateInspectorCleanup === cleanup) {
        delete window.__pyganiniTemplateInspectorCleanup;
      }
    };
    window.__pyganiniTemplateInspectorCleanup = cleanup;
    schedule();
  }

  start();
})();
