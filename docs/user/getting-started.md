# Getting Started

Build a two-page Pyganini application with a shared layout, a generated URL
helper, and an application-owned Starlette host.

## Before You Start

Install CPython 3.13 or newer and [uv](https://docs.astral.sh/uv/). The commands
below use Python 3.14.

## Create the Project

Create the application packages:

```text
mkdir hello-pyganini
cd hello-pyganini
mkdir -p app/routes/users/by_user_id
touch app/__init__.py
touch app/routes/__init__.py
touch app/routes/users/__init__.py
touch app/routes/users/by_user_id/__init__.py
```

Create `pyproject.toml`:

```toml
[project]
name = "hello-pyganini"
version = "0.0.0"
requires-python = ">=3.13"
dependencies = [
    "pyganini==0.1.0",
    "starlette>=1.6.0,<1.7",
    "uvicorn>=0.52.4,<0.53",
]

[tool.pyganini]
```

Install the locked environment:

```text
uv lock
uv sync --locked --python 3.14
```

The empty `[tool.pyganini]` table marks the application root. Pyganini reads
routes below `app/routes` and writes generated modules below `app/_pyganini`.

## Add the Root Page

Create `app/routes/route.py`:

```python
from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

Pyganini scans the package-level `Route` assignment as source. It does not
import the handler during generation.

Create `app/routes/handlers.py`:

```python
from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return Page(
        context={"user_ids": ("ada", "grace"), "urls": app_urls},
        metadata=PageMetadata(
            title="Pyganini users",
            description="A two-page Pyganini application",
        ),
        layout={"home_url": app_urls.root.path, "section": "home"},
    )
```

The handler imports the URL interface that `pyganini generate` will create. The
application imports this handler only after generation.

Create `app/routes/page.jinja`:

```html
<main>
  <h1>Users</h1>
  <ul>
    {% for user_id in user_ids %}
      <li>
        <a href="{{ urls.users.by_user_id(user_id).path }}">{{ user_id }}</a>
      </li>
    {% endfor %}
  </ul>
</main>
```

The template calls a route-shaped helper. Renaming the route package and
regenerating changes the Python interface instead of leaving a string path in
the template.

## Add the Shared Layout

Create an empty `app/routes/layout.py` marker, then create
`app/routes/layout.jinja`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{{ metadata.description }}">
    <title>{{ metadata.title }}</title>
  </head>
  <body data-section="{{ layout.section }}">
    <nav><a href="{{ layout.home_url }}">Home</a></nav>
    {{ child }}
  </body>
</html>
```

The root layout wraps pages in the route subtree. Pyganini renders a page first
and passes that HTML to the layout as `child`. The layout also receives the
page metadata and layout mapping. Each handler binds the generated URL surface
to the request's effective `root_path`, so these links remain inside a
Starlette or FastAPI mount.

## Add a Dynamic User Page

The directory `app/routes/users/by_user_id` maps to
`/users/{user_id}`. Create `app/routes/users/by_user_id/route.py`:

```python
from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

Create `app/routes/users/by_user_id/handlers.py`:

```python
from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    user_id = request.path_params["user_id"]
    return Page(
        context={"user_id": user_id},
        metadata=PageMetadata(
            title=f"User {user_id}",
            description=f"Profile for {user_id}",
        ),
        layout={"home_url": app_urls.root.path, "section": "users"},
    )
```

Create `app/routes/users/by_user_id/page.jinja`:

```html
<main data-user-id="{{ user_id }}">
  <h1>User {{ user_id }}</h1>
  <p>This page inherited the root layout.</p>
</main>
```

Starlette places the decoded dynamic segment in `request.path_params`.

## Generate the Router and URL Helpers

Generate Pyganini-owned files after the source routes exist:

```text
uv run --locked pyganini generate
```

The command creates `app/_pyganini/asgi.py` and
`app/_pyganini/urls.py`. Keep these generated files in version control and do
not edit them by hand.

## Add the Starlette Host

Create `app/main.py` after generation:

```python
from starlette.applications import Starlette
from starlette.routing import Mount

from app._pyganini.asgi import router

app = Starlette(routes=[Mount("/", app=router)])
```

Pyganini supplies the router. The application owns Starlette, the ASGI server,
middleware, lifespan, and deployment settings.

## Check and Inspect the Application

Check generated state and inspect the source route graph:

```text
uv run --locked pyganini check
uv run --locked pyganini routes list
uv run --locked pyganini routes explain /users/ada
```

`check` reports stale or missing generated files without writing. `routes list`
shows both pages, and `routes explain` shows the dynamic parameter and inherited
layout selected for `/users/ada`.

## Run the Application

Start the application-owned Uvicorn process:

```text
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), then follow either user
link. The dynamic page renders inside the same root layout.

## Next Steps

- Add fragments and mutation actions with [Routes](routes.md) and
  [HTMX and async forms](htmx.md).
- Learn how pages and layouts compose in [Rendering and responses](rendering.md).
- Use generated route values across mounts with
  [Generated URL interfaces](urls.md).
- Explore the source graph through [Route inspection](route-inspection.md).
- Run the [full-feature example](../../examples/full_feature) to see route kits,
  navigation, assets, browser helpers, and error composition together.
