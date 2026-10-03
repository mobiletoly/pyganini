(function () {
  if (!window.htmx || !window.htmx.registerExtension) {
    return;
  }

  window.htmx.registerExtension("pyganini-sse-event", {
    htmx_sse_before_message: function (element, detail) {
      if (!element || !detail || !detail.message) {
        return;
      }

      var eventName = detail.message.event;
      if (!eventName) {
        return;
      }

      var swapEvent = element.getAttribute("pyganini-sse-event");
      if (!swapEvent) {
        return;
      }

      if (eventName === swapEvent.trim()) {
        detail.message.event = "";
      }
    }
  });
})();
