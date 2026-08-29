# Releasing Pyganini

Pyganini publishes one wheel and one source distribution from a version tag.
The release workflow builds and tests those artifacts before a separate job
requests a short-lived PyPI credential through GitHub OpenID Connect.

## One-Time Trusted Publisher Setup

Complete these steps after the release workflow reaches the default branch:

1. Create a GitHub environment named `pypi` in `mobiletoly/pyganini`.
2. Sign in to PyPI and open `Account settings` followed by `Publishing`.
3. Add a pending GitHub publisher with:
   - PyPI project name: `pyganini`
   - Owner: `mobiletoly`
   - Repository: `pyganini`
   - Workflow name: `release.yml`
   - Environment: `pypi`
4. Add environment protection rules that match the repository's release
   policy.

The first successful upload creates the `pyganini` project and converts the
pending publisher into a normal project publisher. The pending publisher does
not reserve the project name before that upload. Manage later publisher
changes from the `pyganini` project's `Publishing` page.

The workflow needs no PyPI password or long-lived API token. Only its publish
job receives `id-token: write`; build and verification jobs receive
`contents: read`.

See the [PyPI pending-publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
the [Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
and the [uv GitHub Actions guide](https://docs.astral.sh/uv/guides/integration/github/#publishing-to-pypi)
for the provider setup and credential flow.

## Prepare a Candidate

1. Set the version in `pyproject.toml` and refresh every lockfile that resolves
   the editable Pyganini distribution.
2. Update package, CLI, installation, and artifact assertions for the same
   version.
3. Run the contributor checks from the root README on Python 3.14 and 3.13.
4. Run the functional qualification suite and verify `SHA256SUMS`.
5. Build with `uv build --no-sources` and test the wheel and source
   distribution outside the checkout.
6. Review the complete candidate before authorizing a commit or release.

## Publish

Create an annotated tag whose value matches `project.version` with a leading
`v`, such as `v0.1.0`. Pushing that tag starts the release workflow. The
workflow rejects a version mismatch, builds one artifact set, tests both
artifacts on Python 3.13 and 3.14, generates PEP 740 attestations, and publishes
through the `pypi` environment.

After the PyPI publish job succeeds:

1. Install `pyganini==0.1.0` from PyPI in a clean environment and verify the
   import and `pyganini --version` output.
2. Create a GitHub Release from the existing `v0.1.0` tag.
3. Use `Pyganini v0.1.0` as the release title and summarize the public release
   in its notes.

The release workflow does not create the GitHub Release. The maintainer creates
it after PyPI verification, which activates the root README's Latest Release
badge. Do not rebuild or replace the published PyPI artifacts during this
step.

Version files on PyPI are immutable. If publication fails after one artifact
uploads, retry the same workflow for the same tag and artifact bytes. Change
the version before building any replacement artifacts.
