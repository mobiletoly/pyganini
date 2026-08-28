# Browser Helper Architecture

`src/pyganini/browser` owns one installed-package resource boundary. The public
module exports four string constants and `create_app()`; the package root
exports only the `browser` module.

`create_app()` reads each required allowlisted basename through
`importlib.resources`, derives a strong quoted SHA-256 ETag from its exact
bytes, and returns a fresh Starlette app. One catch-all route compares only the
mount-relative basename. It never joins a request path to the filesystem,
lists a directory, follows traversal components, or reads application assets.
Missing required bytes fail app construction with the exact package-resource
`RuntimeError` instead of falling back to another source tree.

The private ASGI response path preserves GET representation length on HEAD and
omits both body and content length on 304. Conditional matching recognizes
`*`, the exact strong ETag, and uppercase `W/` plus that ETag after ASCII OWS
trimming. Range and modification-date headers have no effect. Starlette
`Mount` owns prefix and `root_path` composition; the helper neither generates
nor interprets an external URL.

The `pyganini-sse-event.js` hook changes only a matching named HTMX 4 SSE
message's `event` field to the empty string. It has no state, timers,
listeners, stream ownership, or generated integration.

`pyganini-template-inspector.js` uses the same package lookup, fixed allowlist,
response path, and ETag owner. Its document-level comment walk verifies
canonical field encoding, label placement, kind/surface compatibility, and the
exact SHA-256 identity before a start comment enters the pairing stack. It owns
only DOM nodes carrying
`data-pyganini-template-inspector` and stores one private cleanup hook. Its frames
are fixed-position and its redraw work is coalesced. Selection follows a live
start-comment occurrence and includes only drawable ranges. A queued `Next`
selection is resolved against the freshly parsed drawable set. Cleanup cancels
pre-body startup or disconnects observation, removes listeners and DOM, and
cancels every pending detail-dismiss timeout and animation-frame task. Neither
helper discovers routes or templates, fetches
graph data, or forms a client runtime.

The inspector creates no helper-owned DOM until at least one valid marker pair
has a non-empty, connected drawable range. A markerless, wholly invalid,
zero-area-only, or disconnected-only document therefore has no overlay
controls or other visible inspection UI. Losing the last drawable unit removes
the UI and resets selection; a later mutation that restores a drawable unit
recreates it.

Handle detail panels remain present while their handle or panel contains focus
or the pointer. Clipboard access is optional; lookup failures, synchronous
`writeText` failures, and rejected results are contained without a page error.
Detail panels use their final border-box dimensions when clamped to the
viewport, including at 390 by 844 with long metadata.
