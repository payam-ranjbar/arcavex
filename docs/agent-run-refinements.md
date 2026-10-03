# Agent-run refinement decisions

Reviewed the supplied 3 October 2026 analysis against source commit
`dd341cd2e3a0ee0212fe2cdd5c081d0d2fbd81f1`. Its session counts and proposed performance targets
are reported observations and estimates; this repository does not contain the cited pi transcripts
or Hunter Hub feedback script. This change makes no claim to have reproduced those measurements.

## Changes in this PR

| Proposal | Decision and implementation |
|---|---|
| Build identity / version drift | Embed commit metadata in wheels, source distributions, and frozen executables. `--version` and `doctor` expose the commit, with a dirty marker for modified tracked source. The desktop handshake reads the same embedded metadata. Preserve the existing package version and release process. |
| Font naming on Windows | Resolve the OpenType typographic family (name ID 16), falling back to family ID 1 and then Skia if the table is unavailable. Prefer English/neutral Unicode records deterministically. Register that exact alias in the paragraph font provider; `font add/list` reuse it. A synthetic name-table regression simulates the Windows backend discrepancy. Native Windows execution remains a CI responsibility. |
| `template check` vs render | Both already use the same compiler and font resolver, including selected-locale mappings. Preserve that path and test a scaffold through check and render with the same format/locale. |
| Structural error collection | Collect independent top-level errors (unknown fields, missing root/formats, invalid locales, undeclared requested locale) before resolution. Report every unknown key within a checked mapping. Later dependent compilation/layout failures can still stop their branch. A locale declaration is optional unless selected. |
| Units | Unify masks and shapes with the SDK length validator already used by effects: `px`, `pt`, `mm`, bare points; reject `%`. Pass the canvas DPI to component schema validation. Rendered-byte tests compare pixels and equivalent points. |
| Numeric style expressions | Keep the current literal-only language and emit a located `ARC-TPL-069` explaining style roles, format/locale patches, and text fit policies. Broadening the expression language needs its own compatibility design. |
| Project-mode `layout inspect` | Omit the template argument to resolve project data, style, format, locale, and override patches through the existing render-input resolver. Refuse an ambiguous multi-target selection with instructions to select one cell. |
| Overlap bounds | Existing JSON and human output already report transformed content bounds and effect-grown paint bounds separately. Preserve this distinction; axis-aligned enclosures are conservative, not exact painted-pixel collision tests. |
| Plain output | Disable Rich CLI help/error panels when stdout is not a terminal. Preserve whole lines in captured human output and print doctor checks as plain lines. |
| Home setup | Discover the nearest existing `.arcavex-home` from the working directory, stopping at a project root. An explicit `ARCAVEX_HOME` wins; otherwise use `~/.arcavex`. For `--project` outside the working directory, set the explicit home once as documented. |
| Scaffold / metadata patching | New templates include `en`. Add `template.<section>[.<field>...]` set/remove paths alongside existing node paths. Mixed batches write only after all operations succeed. Refuse split-section shadowing; edit the sidecar file itself. |
| Skill | Replace the long main reading path with a CLI operating manual: build check, one-time setup, scaffold, small image/text example, unit/expression rules, stack/path recipes, JSON filters, debug previews, series loop, and verification fallback. Keep optional design/extension references and a short MCP appendix. Generate the command reference from Typer's live help model and check drift in CI; frozen builds regenerate it. Both packaging paths include and stamp the same skill. |

The skill installer preserves other installed skills. Automatically deleting `arcavex-poster-studio`
could discard local edits, so the manual explains how to identify and retire a conflicting copy.
The previous reference also incorrectly claimed `style.align` was ignored: the compiler uses it
as a default and an explicit `paragraph.align` overrides it. The reference now states that rule.

## Separate work

- **Publishing and installing a Windows release, PATH integration, `ENGINE.lock`:** this Linux
  checkout contains no `ENGINE.lock` or installed Windows binary. The desktop has its own
  `engine-lock.json` artifact workflow. Do not fabricate an artifact hash or pretend separately
  packaged executables have identical bytes. Build identity and skill inclusion are prerequisites;
  actual release publication and target-machine installation follow the existing release lane.
- **`render --rows` / `--data-dir` / `--name-from`:** worthwhile, but requires contracts for CSV
  value types, relative asset paths, duplicate/safe filenames, partial failure, and recorded run
  provenance. The skill documents the current YAML-series loop and project `batch` accurately.
- **Crop, scale, thumbnail, contact sheets:** useful follow-ups. Define whether they create preview
  derivatives or delivery artifacts and how hashes/reruns record those transformations. The current
  reduced-DPI preview and debug overlays cover immediate inspection needs.
- **`asset inspect`, `describe`, `verify`, combined render report:** useful service/API additions,
  rather than CLI-only wrappers. Asset probing and geometry data already exist. Reuse them while
  defining bounded reports, text metrics, contrast sampling, matrix expansion, and reproducibility
  evidence. A scalar contrast value over an image is not sufficient to establish readability.
- **IPEN skills and style guide:** the cited `ipen-design-start`, `ipen-render`, style guide, and
  Hunter Hub templates are absent from this repository. They require their owning checkout.
- **Fresh pi-session comparison:** needs the original assets, brief, model, and feedback script.
  The regression suite validates behavior, not the proposed message/context/cost targets.

## Validation

The regression cases cover real render/check workflows, pixel-to-point rendered-byte equality,
project overrides, metadata-patch failure atomicity, split-sidecar refusal, long diagnostic paths,
font-name table selection, scoped-home precedence, generated-reference drift, and skill identity.
The full engine suite and architecture/type/lint checks are the merge gates. The existing Windows
CI lane freezes the changed source and verifies the sidecar/desktop bundle; it must pass before
shipping a native Windows artifact.
