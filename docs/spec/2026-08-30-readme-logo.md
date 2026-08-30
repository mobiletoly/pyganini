# Spec: README Logo

Status: implemented
Created: 2026-08-30
Updated: 2026-08-30

## 1. Authority and Dependencies

`AGENTS.md` and `docs/spec/README.md` govern this child. No active umbrella
owns repository branding, so this standalone child limits itself to a static
README identity asset. The project owner must accept this child before
implementation starts.

## 2. Goal

Add a recognizable violin-and-snake Pyganini logo above the existing README title.
The logo must remain legible on GitHub's light and dark backgrounds without
pushing the opening description far below the initial viewport.

## 3. Non-Goals

- Do not change framework behavior, Python code, public APIs, dependencies,
  packaging metadata, generated files, examples, or durable user and
  architecture guides.
- Do not change the existing README prose, badge order, heading, or onboarding
  structure beyond inserting the logo block.
- Do not create favicons, social-preview images, repository avatars, merchandise,
  animation, a mascot, or a general brand guide.
- Do not claim trademark protection or reuse third-party artwork.
- Do not stage, commit, push, publish, or release.

## 4. Background and Evidence

The README starts with `# Pyganini`, three badges, and the reader-first project
description. The repository had no logo or branding asset. A letter-first mark
did not communicate the Paganini reference. The project owner selected a filled
upright violin with a round body, visible neck and pegs, transparent strings and
f-holes, and one original S-shaped python in place of the tailpiece. The selected
mark has no bow and does not use the Python Software Foundation logo.

GitHub renders README content on light and dark surfaces. A single dark foreground
would disappear in dark mode, so the README needs theme-specific SVG files.

## 5. Desired Behavior

The README renders a centered violin-and-snake mark above `# Pyganini`:

```html
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/pyganini-logo-dark.svg">
    <img src="docs/assets/pyganini-logo-light.svg" alt="Pyganini violin and snake logo" width="112">
  </picture>
</p>
```

The existing Markdown title remains text. Screen readers receive useful alt text,
and clients without `<picture>` support use the light asset.

## 6. Locked Decisions and Invariants

- The primary mark is the owner-selected A direction: a filled upright violin
  with one S-shaped snake in place of the tailpiece.
- The mark uses a transparent background and no enclosing badge or container.
- The violin body, neck, scroll, and pegs use one solid foreground color.
- The strings and f-holes cut through the foreground as transparent negative
  space. The snake uses the blue accent and one small yellow eye.
- The snake uses an original single-animal silhouette. It does not reproduce,
  split, crop, distort, or combine the Python Software Foundation's two-snake
  logo.
- Bows, route diagrams, letters, and other mascots do not appear in this slice.
- The light asset uses ink `#1c2028`, blue `#248bff`, and yellow `#ffd343`.
- The dark asset uses warm white `#f3f0e8`, blue `#5aadff`, and yellow `#ffd95a`.
- Both files use the same geometry and view box; their three colors differ.
- SVG files contain paths and basic shapes. They contain no text, font,
  raster image, script, animation, external URL, or metadata generator output.
- The README displays the mark at 112 CSS pixels wide.
- `# Pyganini`, all badges, and the current introduction retain their order and
  wording after the inserted logo block.
- All added repository text and SVG source remains plain ASCII.

## 7. Rules and Failure Modes

- A missing light or dark asset is a validation failure.
- Malformed XML or an SVG with an external resource is a validation failure.
- A mark that becomes unrecognizable at the README display size requires a
  geometry correction inside the accepted concept.
- A mark that lacks contrast on either GitHub theme requires a color correction
  and owner reacceptance when the correction changes a locked color.
- README prose or badge drift outside the insertion point is out of scope.

## 8. Existing Patterns to Reuse

- Preserve the current README title, badge group, and reader-first introduction.
- Use repository-relative asset paths, as the README already does for local links.
- Goldr has no repository logo asset to preserve or adapt. Branding parity is
  `reject`: Pyganini owns an independent visual identity and imports no Goldr
  artwork.

## 9. Implementation Touchpoints and Agent Containment

Implementation scope consists of:

- `README.md`
- `docs/assets/pyganini-logo-light.svg`
- `docs/assets/pyganini-logo-dark.svg`
- this child spec for checklist and lifecycle status updates

All other repository paths are forbidden. Do not add a dependency, public API,
generated artifact, test helper, formatter configuration, or refactor. Stop if
unrelated work appears in an allowed path, the selected geometry needs a concept
change, or validation requires a change outside the allowed paths.

## 10. Proposed Design

Draw one compact vector mark in a `100 120` view box. Fill the violin silhouette,
neck, pegbox, pegs, and scroll with the theme foreground. Cut the strings and
f-holes from the foreground with an SVG mask. Draw one blue S-shaped snake from
the lower bout toward the bridge, with a round head and one yellow eye.

Place the `<picture>` block at the first line of `README.md`, followed by one blank
line and the existing title.

## 11. Implementation Plan

- [x] Create the two SVG files with byte-identical geometry and theme-specific
  colors.
- [x] Add the centered `<picture>` block above `# Pyganini`.
- [x] Parse both SVG files as XML and inspect them at 112, 32, and 16 pixels on
  light and dark backgrounds.
- [x] Run the focused documentation test and diff checks.
- [x] Confirm that changes remain within the allowed paths.
- [x] Set this child to `implemented` after every item passes.

## 12. Acceptance Criteria

- The README shows the selected violin-and-snake logo above its unchanged title.
- GitHub theme selection chooses the matching asset.
- The fallback image has descriptive alt text and a width of 112.
- Both SVGs parse, use the locked colors, contain no external references, and
  share identical geometry.
- The mark matches the owner-selected A direction at 112 pixels and retains a
  usable violin-and-snake shape at 32 and 16 pixels.
- Existing README local links and guide-index tests pass.
- No path outside containment changes.

## 13. Validation Commands

```text
uv run python -c 'from pathlib import Path; from xml.etree import ElementTree as ET; [ET.parse(path) for path in (Path("docs/assets/pyganini-logo-light.svg"), Path("docs/assets/pyganini-logo-dark.svg"))]'
uv run pytest tests/test_documentation.py
git diff --check
git status --short
```

Visual validation must inspect both assets on light and dark backgrounds at 112,
32, and 16 pixels. The implementer must report this in the handoff because the
commands above do not prove recognizability or contrast.

Implementation evidence on 2026-08-30:

- Both SVG files parsed as XML, used the locked colors, and matched after color
  normalization.
- Browser rendering on white and GitHub dark backgrounds matched the selected A
  direction at 112 pixels and retained the violin-and-snake shape at 32 and 16
  pixels.
- `uv run pytest tests/test_documentation.py` passed both tests.
- `git diff --check` passed, and repository changes remained within containment.

## 14. Documentation and Example Updates

`README.md` receives the logo block. `docs/user/`, `docs/arch/`,
`examples/full_feature`, other examples, generated starter applications, CLI
help, package documentation, and docstrings remain unchanged because this slice
does not alter supported behavior or usage.

## 15. Cleanup and Legacy Removal

No legacy logo exists. Do not retain rejected concept sketches in the repository.
If implementation stops before completion, remove incomplete README references
and unreferenced SVG assets before reporting the result.

## 16. Open Questions

None. Owner acceptance of this child authorizes no other work.
