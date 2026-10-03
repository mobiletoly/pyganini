# Content Pages

Build documentation, guides, articles, and application information from trusted
Markdown and HTML files. Pyganini renders these bodies through your application's
layouts. You can add a page without writing a handler for it.

Keep content in external files to update it without rebuilding or restarting
the server, or include it as application package data for deployment. Your
application owns the files, assets, cache policy, and error presentation.

Content authors must be trusted like template authors. Pyganini preserves
authored HTML, including HTML inside Markdown, and does not sanitize it. Public
uploads and other untrusted content are unsupported.

## Add Your First Content Page

Start with a working Pyganini application, such as the one from
[Getting Started](getting-started.md). This walkthrough adds
`/guides/getting-started` to that application. Run the commands from the
application root, beside `pyproject.toml`.

Stop the server before changing its bootstrap. Enable the `content` extra on
your existing Pyganini dependency. For the Getting Started project, change
`"pyganini==0.1.1"` to `"pyganini[content]==0.1.1"`, then update the environment:

```text
uv lock
uv sync --locked --python 3.14
```

The extra provides the Markdown parser, plugins, and linkifier. Core imports
and generated routers work without it. Importing `pyganini.content` without
the complete extra raises an `ImportError` naming `pyganini[content]`.

### Write the Page

Keep content outside `app/`. Create a directory:

```text
mkdir -p content/guides/getting-started
```

Create `content/guides/getting-started/page.json`:

```json
{
  "title": "Getting started",
  "description": "Your first steps with our application."
}
```

The title and optional description become page metadata. The Getting Started
root layout uses them for the browser tab and description meta tag.

Create `content/guides/getting-started/body.md`:

```markdown
# Getting started

Welcome to our product guides.

## First steps

1. Explore the application.
2. Try the example workflow.

[Return to the home page](/)
```

The directory determines the URL: `/guides/getting-started`, without a `content`
prefix or file extension.

### Connect Content to Your Server

Replace the Getting Started application's `app/main.py` with:

```python
from dataclasses import replace
from pathlib import Path

from pyganini import AdditionalPage, content
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

from app._pyganini.asgi import create_router
from app._pyganini.urls import urls

CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content"


def create_app(*, content_root: Path = CONTENT_ROOT) -> Starlette:
    pages = content.new(content.Config(root=content_root))

    def source(request: Request) -> AdditionalPage | None:
        page = pages.resolve(request)
        if page is None:
            return None
        raw = request.scope.get("root_path", "")
        base = raw if isinstance(raw, str) else ""
        app_urls = urls.with_base_path(base)
        return replace(
            page,
            layout={
                "home_url": app_urls.root.path,
                "section": "content",
                "base": app_urls.root.path.removesuffix("/"),
            },
        )

    router = create_router(additional_page_source=source)
    return Starlette(routes=[Mount("/", app=router)])
```

Keep your existing host middleware, static mounts, lifespan, and router options
when adding content to another application.

`content.new` validates the complete tree at startup and captures an absolute
root. The generated router calls `pages.resolve` after an ordinary route miss.
The resolver reads the requested page, converts Markdown to HTML, and supplies
its metadata. The `source` wrapper adds the layout values expected by the
Getting Started root layout: `home_url` and `section`. It also supplies `base`
for the content links used below.

Pyganini does not infer navigation, authentication, assets, dependencies, or
layout data. Supply the values your own layouts need in the same way.

### Open the Page

Generate current router wiring, check it, and start the host factory:

```text
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/guides/getting-started](http://127.0.0.1:8000/guides/getting-started).
You should see the heading, numbered list, and home link inside the root layout.
The browser tab should show `Getting started`. The existing home and user pages
still use their declared handlers.

Edit a sentence in `body.md`, save, and refresh the browser. The next request
reads the changed file. Adding another complete content page requires no route
generation or server restart.

## Add More Pages

Each page directory contains `page.json` and exactly one body file: `body.md`
for Markdown or `body.html` for HTML. You can mix formats across a tree:

```text
content/
  guides/
    page.json                /guides
    body.md
    getting-started/
      page.json              /guides/getting-started
      body.md
    installation/
      page.json              /guides/installation
      body.html
  articles/
    first-release/
      page.json              /articles/first-release
      body.md
```

A directory can have its own page and child pages. A directory without page
files groups its children: `articles/` above creates no `/articles` page. Add
metadata and a body to create that index page. Keep the home page in
`app/routes`; the content root cannot represent `/` or contain page files.

For an HTML page, create `content/guides/installation/page.json`:

```json
{"title": "Installation"}
```

Create `content/guides/installation/body.html`:

```html
<h1>Installation</h1>
<p>Follow these steps to set up your application.</p>
```

Write the body. Your Jinja layout supplies the surrounding HTML document.
Pyganini treats content as finished HTML; it does not evaluate Jinja expressions
inside an authored body. Use a declared route and template when you need that
behavior.

### Link to Content Pages

Use ordinary content paths in Markdown or HTML:

```html
<a href="/guides/getting-started">Getting started</a>
```

For Jinja links in a mounted application, use the `base` value from the tutorial's
source wrapper:

```html
<a href="{{ layout.base }}/guides/getting-started">Getting started</a>
```

Include the public mount prefix in authored body links when you serve the site
under one. Pyganini does not rewrite Markdown or HTML links.

Content pages have no generated URL helpers, navigation entries, or rows in
`pyganini routes list`. Those describe declared routes. Use generated URL values
for declared endpoints, as the tutorial does for its home link.

## Use Layouts, Styles, and Images

Content pages use the root layout and matching static route-tree layouts. To
add shared navigation for `/guides` and its content descendants, stop the server
and create a layout package:

```text
mkdir -p app/routes/guides
touch app/routes/guides/__init__.py
touch app/routes/guides/layout.py
```

The empty `layout.py` marks layout ownership. Create
`app/routes/guides/layout.jinja`:

```html
<nav aria-label="Guides">
  <a href="{{ layout.base }}/guides/getting-started">Getting started</a>
  <a href="{{ layout.base }}/guides/installation">Installation</a>
</nav>
<section>
  {{ child }}
</section>
```

This directory needs no `route.py` because it supplies only a layout. Generate
its wiring and restart the application:

```text
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open `/guides/getting-started` again. The root layout wraps the guides layout,
which wraps the content. New layout or middleware ownership requires generation;
edits to external content do not. See [Rendering](rendering.md) for the layout
contract and [Middleware](middleware.md) for route-local middleware.

Static live middleware applies to matching content pages, including directories
without endpoints. Layouts and middleware below dynamic route directories do
not apply. Reusable mounted-source layouts do not apply either; content follows
original live static ancestry. Use host middleware for authentication that must
cover the whole application.

### Style the Body

Pyganini wraps rendered content in `<article class="pyganini-content">`.
Add styles to your application. For a preview, place this inside the root
layout's `<head>`:

```html
<style>
  .pyganini-content {
    max-width: 70ch;
    margin-inline: auto;
    line-height: 1.6;
  }
  .pyganini-content img {
    max-width: 100%;
    height: auto;
  }
</style>
```

Move these rules into your stylesheet as the application grows. Serve images
through your static asset handler or image host, then reference their public
URLs in content. Pyganini ignores other ordinary files beside the body; it does
not serve them as assets. See [Assets](assets.md).

## Use Markdown Features

Markdown supports common syntax, tables, strikethrough, disabled task inputs,
HTTP(S), www and email autolinks, and raw HTML. For example:

```markdown
## Release checklist

- [x] Write the guide
- [ ] Publish the release

| Format   | Body file |
| -------- | --------- |
| Markdown | body.md   |
| HTML     | body.html |

~~Old instructions~~
```

Markdown headings receive IDs. `Release checklist` produces
`release-checklist`; a duplicate in the same body produces `release-checklist-1`.
You can link to `/guides/getting-started#first-steps` from the tutorial. Heading
counters reset for each document. Raw HTML headings retain the IDs you author.

Inspect rendered headings before linking to punctuation-heavy titles. Pyganini
does not promise exact GitHub slugs or byte-identical Goldmark output. Authored
link and image protocols are trusted. The built-in content package supplies no
highlighting, math, footnotes, or parser plugin API.

## Edit and Preview Content

The sync resolver reads the requested entry on each GET or HEAD request without
walking unrelated subtrees. External edits, new nested pages, and repaired saves
appear on the next request.

Multi-file saves are not transactional. Saving a body before its metadata, or
saving invalid metadata, raises `ContentError` until you repair the entry.
Pyganini keeps no last-known-good copy. Validate a complete tree before replacing
deployed content.

For browser refresh on save, the repository's content-pages example includes an
application-owned development command. From the repository root:

```text
cd examples/content_pages
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 python dev.py --port 8000 --reload-path content
```

Stop another server using that port before running the command. Open
[http://127.0.0.1:8000/privacy/part-one](http://127.0.0.1:8000/privacy/part-one),
then edit the example's content. The browser refreshes on content and existing
Jinja saves while the server keeps its PID. Invalid saves show the example's
error page; repairing them refreshes the valid response.

`dev.py` belongs to the example, rather than the installed Pyganini CLI. See
[Application-owned development](development.md) to add the same pattern to your
own application. The shared supervisor supports macOS and Linux; native Windows
process-tree supervision remains unsupported.

## Choose External or Packaged Content

| Task | External files | Application package data |
| --- | --- | --- |
| Update content | Save files; the next request reads them | Rebuild and restart the application |
| Deploy | Ship the content directory | Include data in the application package |
| Preview edits | Refresh or use an application watcher | Rebuild to change packaged data |

The tutorial locates `content/` relative to `app/main.py`, so the server's working
directory does not select its root. Keep that directory available while the
application runs. The application owns permissions, updates, deployment, and
rollback.

For immutable packaged content, include the tree in a separate application
package, such as `site_data/content/`. Use standard-library resources to obtain
a filesystem directory. From an application-owned launch script, keep the
extraction context open while Uvicorn serves the tutorial's factory:

```python
from importlib import resources

import uvicorn

from app.main import create_app

with resources.as_file(resources.files("site_data").joinpath("content")) as root:
    uvicorn.run(create_app(content_root=root), host="127.0.0.1", port=8000)
```

Configure your application build to include those resource files. Closing the
context before the server exits can remove extracted content. Rebuild and
restart after packaged edits; watching an extraction directory does not update
the packaged data. Pyganini provides no resource registry or extraction cache.

## Rules and Troubleshooting

### Files and URLs

- `page.json` contains one UTF-8 JSON object. Its `title` must be a nonblank
  string; `description` is an optional string. Unknown or duplicate fields,
  nulls, wrong types, malformed JSON, and trailing values are errors.
- Each page needs exactly one `body.md` or `body.html`. A directory with any
  recognized source claims a page and must be complete. A directory with none
  of these sources groups children.
- Metadata is limited to 16 KiB, source bodies to 512 KiB, and rendered Markdown
  to 2 MiB before the article wrapper. Limits are inclusive and count UTF-8
  bytes. Invalid UTF-8 and blank bodies fail.
- Directory names use lowercase ASCII letters and digits separated by single
  hyphens, such as `getting-started`. Use exact URLs without a trailing slash.
  Escaped content segments, empty or dot segments, backslashes, non-ASCII
  identifiers, and normalization attempts do not resolve.
- Symlinks, reparse points, and special files are forbidden, including
  unrecognized entries. Other ordinary files are ignored. The configured root
  and descendants are checked; operating-system aliases above it are allowed.

### A Page Does Not Appear

Compare the URL with its directory, confirm the metadata and body exist, and
check the configured root. A container directory has no page of its own.

Look for a declared static, dynamic, or mounted route at the same URL. That
route owns its match, method mismatch, and errors, including an endpoint 404.
It does not fall through to content. The source runs at most once on an
ordinary HTTP miss and handles only GET and HEAD. Missing entries, containers,
invalid identifiers, and other methods decline with `None`.

### An Edit Produces an Error

Check metadata types and body completeness first. `ContentError.path` names a
source-relative file or directory; `rule` describes the failure. Diagnostics
retain the cause without including body bytes or an absolute content root.

Source failures are terminal and reach the configured `RouteErrorHandler`.
An error `Page` uses the root error template and live root layouts, rather than
a nested content layout; error fragments have no layouts. The application owns
logging and public error messages. See [Error composition](errors.md) and the
[content-pages example](../../examples/content_pages) for a generic error page.

### Check Content Before Serving It

`content.new` validates the complete tree at startup. To check content without
starting a server, call `content.check` with the same root. For the tutorial,
run this from the application root:

```bash
uv run --locked --python 3.14 python - <<'PY'
from pathlib import Path
from pyganini import content

content.check(Path("content"))
print("Content checked.")
PY
```

The repository example also provides
`uv run --locked python -m app.main --check-content`. That flag belongs to the
example application.

Checks cover files, metadata, encoding, and size limits. They do not validate
or sanitize authored HTML. HTML passes through unchanged, including line
endings. The article wrapper supplies a styling hook, without HTML containment
or CSS isolation. Your application owns cache headers, CSP, and trust in authors.
Filesystem checks assume trusted application updates, rather than hostile
concurrent writers.

## Source and Mount Contracts

A custom `AdditionalPageSource` can be sync or async and return an
`AdditionalPage`, a concrete Starlette `Response`, or `None`. Sync work runs in
an AnyIO worker; async work uses the host event loop. Direct responses bypass
layouts. HEAD completes resolution and rendering while suppressing body bytes.
An `AdditionalPage` with status 404 counts as handled.

The trusted `body` contains finished HTML. Metadata and ordinary layout strings
remain autoescaped. Declared routes and error callbacks use `Page` or
`FragmentResponse`; they cannot return `AdditionalPage`.

Content selection uses original static live ancestry and whole path segments:
`/guides` does not own `/guides-extra`. Selection happens before middleware and
retains the original graph-local path. Middleware runs root to leaf around
resolution, rendering, source errors, and declined final 404 handling. Layouts
wrap the completed body outer to inner.

For mounts, trusted ASGI `root_path` identifies the host prefix. The resolver
strips an actual whole decoded prefix when present, or accepts an already-local
path. Supplied `raw_path` must agree after UTF-8 percent decoding. Escapes in
an encoded or Unicode host prefix, including escaped host separators, are
allowed; escapes in content segments remain rejected. Query strings do not
affect lookup. Without raw evidence, the resolver can check only the decoded
identifier; it cannot detect erased escape provenance.

## Further Reading

- [Content-pages example](../../examples/content_pages) for HTML, Markdown,
  layouts, middleware, assets, and a check-only command.
- [Full-feature example](../../examples/full_feature) for content alongside
  declared application routes.
- [Content architecture](../arch/content.md) for dispatch, path evidence, and
  rendering boundaries.
