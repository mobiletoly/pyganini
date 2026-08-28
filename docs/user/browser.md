# Browser Helpers

`pyganini.browser` contains optional fixed JavaScript resources that an
application may mount explicitly. Its public surface is exactly:

~~~python
from pyganini import browser

browser.SSE_EVENT_HELPER_PATH
browser.SSE_EVENT_EXTENSION_NAME
browser.SSE_EVENT_ATTRIBUTE
browser.TEMPLATE_INSPECTOR_HELPER_PATH
browser.create_app()
~~~

Mount the fresh Starlette app at an application-chosen prefix:

~~~python
from pyganini import browser
from starlette.applications import Starlette
from starlette.routing import Mount

app = Starlette(
    routes=[Mount("/pyganini", app=browser.create_app(), name="pyganini-browser")]
)
~~~

FastAPI can mount the same app. Pyganini does not register the mount, construct
its URL, inspect `root_path`, or inject scripts. The application keeps the
HTMX extension and helper visible in its template, followed by the visible
`hx-sse:connect`, `pyganini-sse-event`, and `hx-swap` attributes.

The fixed `/pyganini-sse-event.js` and `/pyganini-template-inspector.js`
representations are ASCII JavaScript with
`Content-Type: text/javascript; charset=utf-8`, `Cache-Control: no-cache`, a
strong SHA-256 ETag, and its exact content length. GET and HEAD support weak or
strong `If-None-Match` revalidation; matching requests return 304. Unknown
paths return 404 and unsupported methods return 405 with `Allow: GET, HEAD`.

This is not an application static server. It does not serve directories,
application assets, arbitrary paths, range requests, or modification-date
validators. The application owns URL choice, mounting, route ordering, CSP,
authorization, cache policy, proxy behavior, and deployment.

The template inspector is useful only with server markers selected through
`TemplateInspectionMode.COMMENTS` or `TemplateInspectionMode.OVERLAY`.
`OVERLAY` does not load the resource automatically. See
[Template inspection](template-inspection.md). The inspector shows UI only
while the document contains at least one valid marker pair with a connected,
non-empty drawable range.
