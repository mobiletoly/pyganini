# HTMX and Async Forms

Pyganini keeps HTMX visible in route-local Jinja templates. The application owns
the HTMX script, client extensions, response policy, validation rules, CSRF,
and persistence. Pyganini supplies generated URL values, typed request-header
helpers, response-header names, and the async Starlette form boundary.

## Visible attributes and generated URLs

Pass a generated URL surface explicitly to the page or fragment context:

```python
from app._pyganini.urls import urls
from pyganini import Page


def page(request):
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(context={"urls": app_urls, "name": ""})
```

Keep ordinary HTML and HTMX attributes on the element:

```html
<section id="users-directory">
  <form
    id="user-form"
    method="post"
    action="{{ urls.users.create.path }}"
    enctype="multipart/form-data"
    hx-encoding="multipart/form-data"
    hx-post="{{ urls.users.create.path }}"
    hx-target="#users-directory"
    hx-swap="outerHTML">
    <label for="contact-name">Name</label>
    <input id="contact-name" name="name" value="{{ name }}">
    <input id="avatar" type="file" name="avatar">
    {% if error %}<p id="name-error">{{ error }}</p>{% endif %}
    <button type="submit">Add contact</button>
  </form>
</section>

<button
  type="button"
  hx-get="{{ urls.users.table.path }}"
  hx-target="#users-table-slot"
  hx-swap="innerHTML">
  Refresh
</button>
```

Pyganini does not generate, inject, rewrite, or wrap these attributes. Jinja
autoescaping applies to URL values and application values. A page-owned slot
normally uses `hx-swap="innerHTML"`; an `outerHTML` response must include the
target root.

## Request and response headers

Import the small public header module from the package root:

```python
from pyganini import FragmentResponse, hx


async def table(request):
    return FragmentResponse(
        context={"rows": load_rows(request)},
        headers={hx.HEADER_TRIGGER: "users:refreshed"},
    )
```

The request helpers are `is_request`, `is_boosted`,
`is_history_restore_request`, `current_url`, `prompt`, `target`, `trigger_id`,
and `trigger_name`. Boolean helpers accept only the exact value `"true"`.
Text helpers return the first matching request header or `""` when it is
absent.

Response constants such as `hx.HEADER_RETARGET`, `hx.HEADER_RESWAP`,
`hx.HEADER_TRIGGER`, `hx.HEADER_REDIRECT`, and `hx.HEADER_REFRESH` are ordinary
string header names. Use them with
`Page`, `FragmentResponse`, or a direct Starlette response. Pyganini does not add
a response builder or mutation helper, and it does not choose target, swap,
redirect, refresh, cache, or history behavior.

## Async form parsing

Direct Starlette `FormData` and live `UploadFile` work belongs in an async route
handler. Starlette owns that parsing; Pyganini declares its
`python-multipart>=0.0.32,<0.0.33` runtime dependency so the public Starlette
parser is available. A mutation action can instead use
`request_data=capture_form(...)`, which materializes an immutable `Form` before
either a sync or async handler runs; see the captured request-data section
below:

```python
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app._pyganini.urls import urls
from pyganini import FragmentResponse, hx


async def create(request: Request) -> FragmentResponse:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    async with request.form(
        max_files=8,
        max_fields=64,
        max_part_size=1_048_576,
    ) as form:
        name = form.get("name")
        upload = form.get("avatar")
        if upload is not None and not isinstance(upload, UploadFile):
            raise ValueError("avatar must be an upload")
        filename = None
        if isinstance(upload, UploadFile):
            filename = upload.filename
            content = await upload.read()
            save_for_the_application(content)

    if not isinstance(name, str) or not name:
        return FragmentResponse(
            context={
                "urls": app_urls,
                "name": name if isinstance(name, str) else "",
                "error": "Name is required.",
            },
            status_code=422,
            headers={
                hx.HEADER_RETARGET: "#users-directory",
                hx.HEADER_RESWAP: "outerHTML",
            },
        )
    return FragmentResponse(
        context={"urls": app_urls, "name": name, "filename": filename},
        headers={
            hx.HEADER_RETARGET: "#users-directory",
            hx.HEADER_RESWAP: "outerHTML",
            hx.HEADER_TRIGGER: "user:created",
        },
    )
```

Use `form.getlist(name)` when repeated values matter. Copy, read, or persist
needed upload content before leaving the `async with` block. Starlette closes
parsed uploads when the context exits. Pyganini does not retain or materialize an
upload for a later task.

The limits are explicit application choices. In Starlette 1.6.0,
`max_part_size` limits non-file multipart parts and URL-encoded fields; it does
not cap multipart file content. The parser does not impose a total request-body
limit. Spooling thresholds are Starlette implementation details, and filenames,
content types, and field values are untrusted client input. Applications own
content validation, storage, quotas, persistence, and any total-body policy.

Malformed input follows Starlette's parser and host error path. Pyganini does not
catch, rename, or convert parser exceptions. Applications may catch Starlette's
public exceptions when they need route-local error HTML.

## Validation and host policy

An action can return a `FragmentResponse` with an application-selected `422`
status and validation HTML. HTMX 4 beta6 swaps every response by default except
204 and 304, including error responses. An application that wants a bounded
validation workflow must configure and test its own `htmx.config.noSwap` policy;
the full-feature example permits the `422` redisplay while suppressing other
4xx and 5xx swaps. Pyganini installs no JavaScript, middleware, automatic CSRF
enforcement, `Vary`, cache, redirect, target, or swap policy. An application
may explicitly mount `pyganini.csrf.TokenMiddleware` and render its visible
`hx-headers` value; the application still chooses parsing, validation, and the
failed response. Pyganini rejects duplicate token headers or configured cookies;
form handlers must require exactly one textual token value. See
[CSRF helpers](csrf.md).

Use a separate fragment URL when a workflow has a stable partial boundary. An
application may use `hx.is_request(request)` to vary a handler's representation,
but Pyganini does not branch before the handler, select a template, or add cache
headers automatically.

`pyganini check` validates the route graph, templates, generated state, and URL
helper collisions. It does not parse Jinja or claim that an `href`, `action`,
`formaction`, `hx-*`, or `data-hx-*` expression matches the route graph. The
separate read-only `pyganini routes refs` command inventories only direct
`hx-get`, `hx-post`, `hx-put`, `hx-patch`, `hx-delete`, and `data-hx-*`
equivalents in graph-selected `.jinja` source. It is conservative inventory,
not blocking validation: dynamic values remain `dynamic`, templates are not
rendered, and includes, inheritance, and application data are not followed.
Pass generated URL values explicitly and test the final HTML and requests.

## Captured action request data

Use an explicit `request_data=` declaration when a mutation action needs one
bounded immutable request value. The public values live in
`pyganini.request_data` and contain no live Starlette resources:

```python
from starlette.requests import Request

from pyganini import FragmentResponse, action, route
from pyganini.request_data import Form, capture_form


async def create(request: Request, form: Form) -> FragmentResponse:
    await save_names(form.values("name"))
    return FragmentResponse(context={"names": form.values("name")})


Route = route(
    actions=(
        action(
            "POST",
            "/create",
            create,
            request_data=capture_form(
                max_files=1,
                max_fields=16,
                max_part_size=65_536,
                max_upload_size=2_000_000,
            ),
        ),
    ),
)
```

`capture_body(max_bytes=N)` supplies `Body` to `(request, body)`. The body is
read from `Request.stream()` on the ASGI side and raises `413` when its
cumulative bytes exceed `N`. `capture_form(...)` supplies `Form` to
`(request, form)` and accepts only URL-encoded or multipart content types. Its
parser limits are passed to Starlette; `max_upload_size` bounds each copied
upload. Repeated text values and uploads retain source order. Use
`form.items` when interleaving matters, `form.values(name)` for text, and
`form.uploads(name)` for immutable `Upload` values.

An opted-in route-kit action receives `(kit, request, form)` or
`(kit, request, body)`. The creator runs before capture. Every parsed upload is
copied to bytes and closed before the handler runs; duplicate references
reuse one value and one close attempt. Cleanup is cancellation-shielded. A
primary parser or read failure remains primary with cleanup notes, while
cleanup-only failures are raised as an ordered exception group.

Async captured handlers run on the ASGI event loop and may await application
work after capture. Sync captured handlers run in the AnyIO worker and must not
call async body, stream, JSON, form, or upload methods on the original
`Request`. Use direct Starlette parsing instead of captured data when the
application needs streaming, `FormData`, live `UploadFile`, or another async
request API. These declarations do not add validation, CSRF, storage, or a
whole-request body policy: those remain application- or host-owned. Unsupported
form media types produce `415`, and the application owns final error
presentation through the host or optional generated-route callback. See
[Error composition](errors.md).

The [full-feature example](../../examples/full_feature) demonstrates an
application-owned multipart action, a shared route-kit page and table with a
full `/users` owner and read-only `/settings/users` owner, CSRF boundary, `422`
response policy, local HTMX asset, and ordinary HTML fallback using these
public contracts. The captured shared action receives `(kit, request, form)`
and keeps its visible HTMX attributes in the shared Jinja template.
