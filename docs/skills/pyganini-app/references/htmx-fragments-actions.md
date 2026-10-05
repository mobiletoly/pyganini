# HTMX Fragments and Actions

Read this when editing partials, mutation endpoints, targets, or response headers.
Keep visible HTML and `hx-*` attributes in route-local Jinja. Handlers return
render values; declarations choose templates. Pyganini never chooses a swap,
target, redirect, history, validation, or status policy for the application.

## Add a form action

Starting with the [minimal app](project-setup.md), replace the root declaration,
handler, and page below, and add the result template. Keep the existing root
layout and dynamic route. This example echoes a name and performs no persistence.
Applications choose their validation and CSRF policy before real mutations; see
[Forms, CSRF, and dependencies](forms-csrf-dependencies.md).

### `app/routes/route.py`

```python
from pyganini import action, route

from .handlers import page, submit

Route = route(
    page=page,
    template="page.jinja",
    actions=(action("POST", "/submit", submit, template="result.jinja"),),
)
```

### `app/routes/handlers.py`

```python
from pyganini import FragmentResponse, Page, PageMetadata, hx
from starlette.requests import Request

from app._pyganini.urls import urls


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(
        context={"urls": app_urls},
        metadata=PageMetadata(title="Name form"),
    )


async def submit(request: Request) -> FragmentResponse:
    async with request.form(max_files=0, max_fields=8) as form:
        name = form.get("name")
    if not isinstance(name, str) or not name.strip():
        return FragmentResponse(
            context={"name": "", "error": "Name is required."},
            status_code=422,
        )
    return FragmentResponse(
        context={"name": name.strip(), "error": ""},
        headers={hx.HEADER_TRIGGER: "name:accepted"},
    )
```

### `app/routes/page.jinja`

```html
<main>
  <form method="post" action="{{ urls.submit.path }}"
        hx-post="{{ urls.submit.path }}" hx-target="#result"
        hx-swap="outerHTML" hx-status="422:swap">
    <label>Name <input name="name" required></label>
    <button type="submit">Submit</button>
  </form>
  <section id="result" aria-live="polite"></section>
</main>
```

### `app/routes/result.jinja`

```html
<section id="result">
  {% if error %}<p>{{ error }}</p>{% else %}<p>Hello {{ name }}</p>{% endif %}
</section>
```

Regenerate and check after changing the declaration. The page still uses its
layout; the returned action fragment has only `result.jinja`, including the root
required for `outerHTML`. The host application supplies HTMX 4 and its scripts;
these examples do not inject them. Ordinary form submission also receives this
fragment; add an explicit full-page response branch if the app requires one.

## GET fragments and response choices

A GET partial is declared explicitly, not discovered from a template filename:

```python
from pyganini import fragment_route, route

Route = route(
    fragments=(fragment_route("/", table, template="table.jinja"),),
)
```

Bind `table` before the declaration. An index fragment cannot share its GET/HEAD
path with a page. Page handlers return `Page` or a concrete Starlette response;
fragment handlers return `FragmentResponse` or a concrete response; actions can
return either render value or a concrete response. Direct responses bypass Jinja.
An action `Page` uses its declared template and the selected page layout chain.

Use `hx.is_request(request)` and related request helpers when application policy
needs them. Response constants such as `hx.HEADER_RETARGET`, `HEADER_RESWAP`,
`HEADER_TRIGGER`, `HEADER_PUSH_URL`, and `HEADER_REDIRECT` are header names, not
response builders. Supply them through render-value or Starlette headers. Use
generated URL paths for represented internal header destinations.

With stable HTMX 4, put expected status behavior on the element, as with
`hx-status="422:swap"` above, rather than installing a framework-global swap rule.
Use `innerHTML` for a slot whose response omits its root, or `outerHTML` when the
response replaces that root. Keep page-owned action/fragment routes local; child
route packages supporting a workflow do not need a standalone page.
