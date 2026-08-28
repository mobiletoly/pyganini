# Signed-cookie CSRF helpers

`pyganini.csrf` is an optional public module. It owns one signed
double-submit-cookie format and a direct ASGI token middleware. It does not
depend on route declarations, the route graph, dispatch, rendering, request
data capture, or generated output. The application owns the secret, policy,
mounting, parsing, validation point, mutation ordering, and response.

## Public boundary

The module exports only its constants, typed validation exceptions, `Guard`,
`TokenMiddleware`, `token(request)`, and `headers(token)`. `pyganini.__init__`
exports the module object as `csrf`; it does not re-export the helper classes or
constants. The request-scope storage key is private and applications must use
`token(request)`.

`Guard` validates an immutable bytes secret with at least 32 bytes and strict
cookie policy at construction. `max_age` is limited to 1 through
`2_147_483_647` seconds so issuance does not depend on construction-time wall
clock timing. The default cookie is `pyganini_csrf`, path `/`, 12-hour `Max-Age`,
`HttpOnly`, and `SameSite=Lax`. `Secure` is configurable and `SameSite=None`
requires it. No default or generated production secret exists.

## Token and cookie flow

New tokens are ASCII:

```text
v1.<issued Unix seconds>.<raw URL-safe base64 nonce>.<raw URL-safe base64 signature>
```

The nonce is 32 random bytes. The signature is HMAC-SHA256 over the first
three fields. Nonce and signature are unpadded, URL-safe base64 with 43
characters each. Timestamps contain one to 20 non-negative ASCII digits.
Valid tokens expire only when their age is greater than `max_age`; timestamps
up to 60 seconds in the future are accepted for clock skew, and farther-future
tokens are bad.

`TokenMiddleware` is a direct ASGI wrapper. For HTTP scopes it reads only the
configured cookie occurrences without collapsing duplicates, validates one
occurrence without consuming the body, and either reuses it or issues a
replacement. Duplicate configured cookies are invalid evidence and cause
replacement without request rejection. The middleware copies the scope, stores
the token under the private key, calls downstream exactly once with the original
`receive`, and appends one `Set-Cookie` header to the first response-start
message only when it issued a token. Starlette's public
`Response.set_cookie()` serializes the cookie, including `Expires`, `Max-Age`,
`HttpOnly`, `Secure`, and `SameSite`. No Domain or Partitioned attribute is
selected.

Non-HTTP scopes pass through unchanged. The middleware does not buffer or
replace response bodies, alter status or existing headers, create tasks, call
`Guard.validate()`, or author an error response. Duplicate mounting raises a
configuration `RuntimeError` before the inner application runs. Exceptions
before response start retain identity and emit no middleware-authored response
or cookie.

## Validation and composition

`Guard.validate()` reads only the method, case-insensitive request headers, and
configured request cookie occurrences, plus the already parsed form string. It
never calls `body()`, `stream()`, `form()`, `json()`, or a Pyganini capture
operation. Duplicate token headers or configured cookies fail with
`BadTokenError` before order can select evidence. With singular evidence, the
sequence is safe-method bypass, header-over-form selection, missing evidence,
constant-time submitted/cookie comparison, wire parsing, constant-time HMAC
comparison, future-skew check, and expiry check. The incoming cookie remains the
evidence source even when middleware has scheduled a replacement cookie.

`Guard.validate()` receives one application-selected form string and does not
own form parsing. Applications using form evidence must require exactly one
textual value before validation and mutation.

The public failures are `MissingTokenError`, `MissingCookieError`,
`MalformedTokenError`, `BadTokenError`, and `ExpiredTokenError`, all under
`ValidationError`, with stable non-sensitive messages. Missing middleware is a
separate `TokenUnavailableError` so application composition failure is not
confused with hostile request evidence.

`headers(token)` is compact standard-library JSON for the visible
`X-CSRF-Token` HTMX header. It is a plain string, not trusted markup. Hidden
inputs, meta tags, `hx-*` attributes, Jinja context, parsing, and error HTML
remain application-owned. Direct Router, Starlette, FastAPI, host middleware,
and selected route middleware all use the same ASGI helper without an adapter.
