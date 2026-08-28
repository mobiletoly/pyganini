document.documentElement.dataset.pyganiniJs = "ready";

if (window.htmx) {
  // HTMX 4 uses noSwap for this policy. Keep validation 422 HTML swappable
  // while suppressing every other client error and all server-error responses.
  window.htmx.config.noSwap = [
    204,
    304,
    "40x",
    "41x",
    420,
    421,
    423,
    424,
    425,
    426,
    427,
    428,
    429,
    "43x",
    "44x",
    "45x",
    "46x",
    "47x",
    "48x",
    "49x",
    "5xx"
  ];
}
