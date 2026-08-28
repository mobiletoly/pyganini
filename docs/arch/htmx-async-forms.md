# HTMX Form and Request-Data Architecture

This document describes the direct Starlette async form boundary and the
separate Pyganini synchronous request-data boundary. It does not add a route
model, request wrapper, form abstraction, response builder, middleware,
generated HTMX output, or runtime HTMX behavior.

## Owners

- `src/pyganini/hx.py` owns the plain HTMX header constants and typed request
  header readers. It imports only Starlette `Request` and uses no Pyganini
  internals.
- `src/pyganini/_render.py` remains the owner of immutable render values and
  response-header validation. HTMX response constants are ordinary names used
  with `Page` and `FragmentResponse`.
- `src/pyganini/_dispatch.py` and generated `app/_pyganini/asgi.py` remain the owners
  of request delivery and callable invocation. They do not inspect HTMX headers
  or parse forms before a direct async handler runs; explicit `request_data=`
  actions use the separate synchronous capture path below.
- Starlette owns URL-encoded and multipart parsing through
  `Request.form(...)`. Pyganini directly declares the compatible
  `python-multipart>=0.0.32,<0.0.33` dependency.
- The application owns validation, persistence, upload policy, total-body
  limits, CSRF, JavaScript, cache policy, and host error presentation.

## Public header boundary

`pyganini.hx` exports the locked request and response header names plus eight
request readers. Boolean readers compare the first matching header value with
the exact text `"true"`; text readers return the first value or an empty
string. The module has no response mutation functions, builder, mutable state,
Jinja global, or response type.

`Page`, `FragmentResponse`, and direct Starlette responses remain the response
owners. Existing header validation rejects reserved content and framing names;
the HTMX names do not create a second validation path.

## Direct Starlette async form boundary

Generated endpoints continue to pass the same Starlette `Request`. A handler
that reads a form directly is an async outer callable and keeps upload lifetime
inside the public context manager:

```python
async with request.form(
    max_files=8,
    max_fields=64,
    max_part_size=1_048_576,
) as form:
    value = form.get("name")
```

Repeated fields remain Starlette `FormData` values. Applications select field
types and multiplicity, read uploads before context exit, and own destinations
and cleanup. Starlette's parser enforces the explicit file, field, and
non-file-part limits. It does not enforce a total request-body limit or a file
content limit through `max_part_size`.

## Synchronous action request data

`pyganini.request_data` is a separate explicit boundary for mutation actions that
must remain synchronous. `capture_body(max_bytes=...)` produces an immutable
`Body`; `capture_form(...)` produces an ordered immutable `Form` whose uploads
are immutable `Upload` values. Only `action()` and `kit_action()` accept the
`request_data=` field, and the static graph accepts only direct unaliased
`capture_body(...)` or `capture_form(...)` calls with literal keyword integers.

The normalized capture value and its source position travel through
`ActionSurface`, `Endpoint`, and `iter_endpoints()`. Generated dispatch emits
the value as method-specific literals. Controlled import compares the runtime
declaration with that evidence and requires a synchronous action handler with
arity `(request, data)` or `(kit, request, data)`. Pages, fragments, creators,
async actions, and non-opted-in sync actions are unchanged.

Capture and upload cleanup happen on the ASGI side before worker offload. Body
capture consumes `Request.stream()` cumulatively. Form capture validates the
parsed media type, awaits `Request.form(...)` with explicit parser limits,
copies every distinct `UploadFile` in bounded chunks, reuses duplicate object
references, and closes each distinct upload once inside an AnyIO shield.
Starlette retains parser ownership when parsing fails before `FormData` is
returned. Pyganini preserves primary parser/read/cancellation failures with
cleanup notes and groups cleanup-only failures after every close attempt. This
boundary has no portal, request proxy, middleware, schema, validation, CSRF,
storage, or whole-request body policy.

Malformed parser input remains a Starlette error. The synchronous boundary
translates only missing or unsupported form media types to `HTTPException(415)`
and body or upload byte-limit failures to `HTTPException(413)`; the host owns
their final representation. It does not provide form validation, JSON binding,
or application upload storage.

## Route-local workflow

The route graph owns the page, GET fragment, and POST action. The application
passes a bound generated URL surface in explicit page or fragment context.
Jinja keeps `method`, `action`, `hx-post`, `hx-get`, `hx-target`, `hx-swap`, and
multipart encoding attributes visible. A page-owned slot normally receives
fragment HTML with `innerHTML`; an `outerHTML` response contains its target
root.

Validation redisplay is an ordinary `FragmentResponse` with an application
selected status and HTMX headers. Pyganini does not automatically branch on
`HX-Request`, choose a page or fragment template, add `Vary`, or install a
non-2xx swap policy. A direct Starlette response remains available for
redirects, streaming, repeated headers, and other low-level contracts.

The same visible HTMX contract applies when a route owner uses a shared route
kit. The owner binds its generated URL surface into the kit value, and the
shared page, fragment, or action template reads those explicit values. Pages,
fragments, and non-captured actions receive `(kit, request)`; a captured action
receives `(kit, request, body)` or `(kit, request, form)` synchronously. Direct
Starlette `FormData` and live `UploadFile` access remains an async-handler
workflow. Pyganini does not introduce a hidden dependency container or
client-side state layer.

## Static and host boundaries

The generated URL interface remains the only checked route-path source. Pyganini
does not parse Jinja expressions or resolve `href`, `action`, `formaction`,
`hx-*`, or `data-hx-*` values during `pyganini check`. The separate source-only
`pyganini routes refs` inspection inventories direct HTMX request attributes with
the route-inspection owner; it does not change HTMX ownership, render
templates, follow composition, or become a blocking check. Runtime tests
assert final HTML and send requests through the generated router.

The router works directly under Starlette and as a FastAPI mount. The
application selects `request.scope["root_path"]`, binds it through
`urls.with_base_path(...)`, and passes that value explicitly. FastAPI keeps
ownership of its routes, OpenAPI, dependency injection, lifespan, and outer
middleware. Pyganini adds no host adapter or implicit request state.
