# Installation

Pyganini supports CPython 3.13 and newer. Install the 0.1.0 release with any
compliant Python package installer:

```text
python -m pip install pyganini==0.1.0
```

Maintainers can test a release candidate from built artifacts before
publication:

```text
python -m pip install ./dist/pyganini-0.1.0-py3-none-any.whl
python -m pip install ./dist/pyganini-0.1.0.tar.gz
```

The runtime distribution depends on compatible Starlette 1.6, Jinja 3, AnyIO
4.14, and python-multipart 0.0.32 releases:

```text
starlette>=1.6.0,<1.7
jinja2>=3.1.6,<4
anyio>=4.14.2,<4.15
python-multipart>=0.0.32,<0.0.33
```

Pyganini calls AnyIO directly to run synchronous route handlers and synchronous
Jinja rendering in worker threads with the framework's accepted cancellation
behavior. It uses the host's default thread limiter without changing it.
Starlette owns URL-encoded and multipart form parsing for async handlers;
applications choose explicit parser limits and upload policy.

uv is not a runtime requirement. Pyganini also does not install an ASGI server,
FastAPI, or deployment tooling. The application chooses its installer, ASGI
server, host framework, middleware, lifespan, dependencies, and deployment
configuration.

FastAPI is a tested development compatibility target rather than a Pyganini core
dependency. The generated public Starlette `Router` can serve directly, mount
under Starlette, or mount after more specific FastAPI routes. FastAPI retains
its API, dependency, and OpenAPI ownership; mounted Pyganini routes do not enter
the FastAPI schema.

Starlette mounts and trusted server proxy configuration compose the effective
decoded ASGI `root_path`. Generated request Navigation uses that value for
canonical hrefs. Applications pass the same value explicitly to generated URL
and asset helpers. Pyganini does not infer `Forwarded` or
`X-Forwarded-Prefix`; a header alone does not select a prefix.

Applications may add live route-tree middleware in
`app/routes/**/middleware.py`. Pyganini validates the direct tuple statically and
supplies it through Starlette's public per-route middleware boundary. The
application still owns middleware classes, state, authentication, dependencies,
and the outer host stack. For generated-route errors, the application may pass
an owned `RouteErrorHandler` to `create_router(error_handler=...)`; see
[Error composition](errors.md). Errors outside generated dispatch remain
host-owned.

The package contains inline type information and ships `pyganini/py.typed`.
