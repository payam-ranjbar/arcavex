# Phase 04 — DX & design review (projects, library, provenance)

Reviewer: Sonnet 5, DX/design lane. Scope: commit `599e249`. Read only `README.md` before
authoring the workflow (per brief); consulted spec §5, §6.1.2, §6.3 for the precision audits
requested in the brief. All work under `outputs-tmp/dx4/`, with an isolated `ARCAVEX_HOME` at
`outputs-tmp/dx4/home` to avoid colliding with other agents' concurrent runs against the shared
default library.

## Verdict: **remediate**

The determinism spine is genuinely solid and the JSON-envelope consistency gap flagged in the
Phase 3 review is visibly fixed (every new command I touched carries `response_version`). But
this phase's own brief and spec §6.3 treat DX as a release criterion, not an aspiration, and
four things fall short of what §5.3/§5.5 explicitly promise: manifests don't capture the one
project-local input that actually changes pixels (the override patch), `diff` can tell you *that*
data changed but never *what* changed, `project upgrade`'s preview skips the render/diff steps
the spec lists by name, and two of the four documented per-template commands (`validate`,
`preview`) simply don't work in project mode at all. None of these are exotic edge cases — I hit
all of them doing the ordinary new-user workflow the brief asked for.

## Findings

### DX-1 (P1) — `validate` and `preview` have no project mode; only `render` does

**Did:** followed the README's project workflow inside a freshly created project
(`outputs-tmp/dx4/proj/meetup`, `arcavex project new ... --template ipen-poster@1.0.0`). Ran
`arcavex status` (works), then tried `arcavex validate` and `arcavex preview` with no arguments,
the way `arcavex render` is documented to work ("render with no template arg = project mode").

**Happened:**
```
$ arcavex validate
Usage: arcavex validate [OPTIONS] TEMPLATE
Error: Missing argument 'TEMPLATE'.
[exit 2]

$ arcavex preview
Usage: arcavex preview [OPTIONS] TEMPLATE
Error: Missing argument 'TEMPLATE'.
[exit 2]
```
`arcavex render --help` explicitly documents `[template]` as optional ("Omit to render the
current project (project mode)"); `validate --help` and `preview --help` both keep `TEMPLATE` as
a required positional. Only `render` implements the project-mode/direct-mode split the README's
own prose describes as a general pattern.

**Must change:** this breaks the AI template workflow spec §6.3 lists as a numbered contract step
— "Validate before rendering when possible" — for every project-mode user. Today there's no way
to validate a project's current data + patches without manually reconstructing the template ref,
data path, and (post-detach or post-upgrade) figuring out which library path or local copy to
point at yourself, which defeats the point of `project.yaml` centralizing that. Either give
`validate`/`preview` the same optional-TEMPLATE + `--project` treatment as `render`, or document
prominently that project-mode has no dry-run/preview step and you must `render` to find out.

### DX-2 (P1) — project override patches are invisible to provenance and to `diff`

**Did:** added `overrides/ipen-poster.patch.yaml` to the project (`set:
nodes.venue.style.font_size, value: 30pt`) — guessing the filename from the spec's project-layout
diagram, since README never documents this (see DX-6). Rendered, confirmed via pixel diff
(dssim 0.0057 against an unpatched render) that the patch has a real visual effect. Then
inspected the resulting run's `manifest.json`, and ran `arcavex diff` between the patched and an
otherwise-identical unpatched run.

**Happened:** `grep -i "patch\|override" manifest.json` on the patched run returns nothing — no
hash, no operation list, no acknowledgement a project patch was applied at all. Diffing the
patched run against an unpatched one with everything else held constant:
```
diff 2026-07-15T02-39-24Z_aa3088 .. 2026-07-15T02-39-18Z_aa3088
outputs:
  meetup.a4.en.png: dssim 0.0057
no metadata changes
```
`diff` correctly reports the pixels differ but claims **no metadata changes** — actively wrong,
since the entire cause of the pixel difference is the project patch, which is exactly the kind of
thing spec §5.3 promises `diff` will surface ("separately reports template, data, asset, font,
engine, and option changes"). A user reading this output has no way to explain a pixel diff that
the tool itself produced.

**Must change:** hash the resolved/applied project-patch content (the same way template/style/
data are canonically hashed) and record it in the manifest as a first-class provenance field;
have `diff` compare that hash and report `overrides: changed` (or similar) the same way it
reports `data[en]: <hash> -> <hash>`. Without this, "manifests capture every input by hash"
(brief item 4, spec §5.3) is false for the one input type unique to project mode.

### DX-3 (P1) — `rerun`'s byte-identity is silently contingent on the live override file, and it can't tell you why it broke

**Did:** built directly on DX-2's setup. Recorded a run with the override patch present, then
**deleted** `overrides/ipen-poster.patch.yaml` and ran `arcavex rerun` on that same run directory.

**Happened:**
```json
{
  "reproduced": false,
  "engine_match": true,
  "platform_match": true,
  "mismatches": ["meetup.a4.en.png"]
}
```
Credit where due: it did **not** silently claim reproduction — this is the right instinct and
the safest possible failure mode (see "What impressed"). But `reproduction.json` and the CLI
message ("did not claim exact reproduction (1 output(s) differ)") give no lead on *why*: engine
matches, platform matches, yet it failed — because rerun re-resolves the *current on-disk*
project override rather than a frozen snapshot, and nothing in the manifest records what that
override was at record time (DX-2). A user hitting this in the wild has to already suspect
`overrides/` to explain it.

**Must change:** either (a) freeze the resolved node tree (post-patch) into the manifest so
rerun never re-reads a mutable override file, matching spec §5.3's "uses the original resolved
snapshot" language literally, or (b) if re-reading overrides live is intentional, detect the
override-file hash mismatch specifically and name it in `mismatches`/the human message instead of
just naming the differing PNG.

### DX-4 (P1) — `project upgrade` preview never renders or diffs anything; spec §5.5 lists 5 steps, 2 are missing

**Did:** published `ipen-poster@2.0.0` with a renamed node (`venue` → `location`, which the
project's own override patch targets) and ran `arcavex project upgrade --to 2.0.0`, both without
and with `--yes`.

**Happened:**
```
$ arcavex project upgrade --to 2.0.0
upgrade 1.0.0 -> 2.0.0 (preview only)
stale patch paths (no longer resolve):
  project.patch[0]
```
```json
{"from_version": "1.0.0", "to_version": "2.0.0", "stale_paths": ["project.patch[0]"],
 "outputs": [], "applied": false}
```
`outputs: []` in both the preview and (checked separately) the `--yes` run — no comparable
preview renders are produced, and there is no structural or perceptual diff between the old and
new template version anywhere in the human or JSON output. Spec §5.5 names five explicit steps:
compile old+target, report stale paths, **render comparable previews**, **show structural +
perceptual diffs**, update pin on acceptance. Only steps 1, 2, and 5 exist. The brief's own
question — "is the preview/diff helpful?" — currently has the answer "there is no diff, only a
list of broken patch paths."

**Must change:** render both versions over current project data (as already happens internally
to detect stale paths) and surface those renders plus a dssim comparison, the same shape `diff`
already produces for two runs. This is arguably the single most useful part of an upgrade
decision (does the new version actually look different?) and it's the part that's missing.

### DX-5 (P2) — stale-patch reporting gives an array index, not the actual broken path

**Did:** same upgrade-preview run as DX-4.

**Happened:** the only detail given for the break is `project.patch[0]` — an index into the
override YAML file, not the node path that stopped resolving (`nodes.venue.style.font_size`).
Contrast this with the render-time failure for the *same* stale patch, which is excellent:
```
ERROR ARC-TPL-092 Invalid patch operation: no node with id 'venue' to patch
(...\overrides\ipen-poster.patch.yaml, line 1, at project.patch[0])
  hint: Patch ops are set/remove/insert_before/insert_after addressing 'nodes.<id>'.
```
That message names the file, the line, and the offending node id. The upgrade preview clearly
has access to the same information (it knows the path stopped resolving) but reports only the
index. A project with more than one or two override operations would force counting entries by
hand to find the broken one.

**Must change:** reuse the same located-diagnostic detail (file, line, node id) in the upgrade
preview's stale-path report that render-time patch failures already produce.

### DX-6 (P2) — README never documents project override patches at all

**Did:** searched README for "override" before writing the patch file in DX-2; grepped again
afterward to confirm.

**Happened:** the project-layout, the `overrides/` directory, the `<template-name>.patch.yaml`
filename convention, and the fact that project patches use the same
`set`/`remove`/`insert_before`/`insert_after` vocabulary as format/locale patches are **only** in
the spec (§5.2, §5.4) — none of it is in README. To the README's credit, `project new` *does*
scaffold an empty `overrides/` directory up front (confirmed: `assets/`, `data/`, `outputs/`,
`overrides/` all present immediately after scaffold), so a curious user has a discoverable
breadcrumb — but nothing tells them what filename to use or what syntax the file expects. This is
the same class of gap the Phase 3 review flagged for the (now-fixed) `--style` flag: a real,
working feature that a README-only user cannot discover exists.

**Must change:** add a short "project overrides" subsection to README — the directory, the
filename pattern, and a pointer to the existing patch-operation syntax already documented for
format/locale patches (it's the identical model, so this is a small addition).

### DX-7 (P2) — `list-runs` cannot see direct-mode (`--record`, no project) runs at all

**Did:** ran `arcavex render TEMPLATE --data ... --record` outside any project (README documents
this as a first-class direct-mode flag: "Direct render that also writes a run manifest"). It
wrote a well-formed `outputs/<run>/manifest.json` (`"kind": "direct"`). `rerun` and `diff` both
worked fine on it by path. Then tried `arcavex list-runs` from the same directory.

**Happened:**
```
ERROR ARC-PRJ-001 No project found (no project.yaml in this or any parent directory)
```
`list-runs` unconditionally requires a discoverable `project.yaml`, even when run from inside the
very directory holding the recorded run it should be listing. A direct-mode user who used
`--record` has no command to answer "what have I recorded so far?" other than manually `ls
outputs/` — the discovery half of the provenance story (brief item 1: "how do you know what runs
exist?") doesn't reach the direct-mode half of the feature it's paired with.

**Must change:** either let `list-runs` scan a plain `outputs/` directory when no project is
found (falling back from project-scoped to cwd-scoped listing), or document explicitly that
direct-mode recorded runs are rerun/diff-able but not list-able, so it isn't discovered by
surprise.

### DX-8 (P2) — §6.3's config-precedence chain has no `config.toml` to precede

**Did:** grepped the full source tree for `config.toml` and any `ARCAVEX_*` environment variable
besides `ARCAVEX_HOME`.

**Happened:** zero references to `config.toml` anywhere outside the spec document itself; the
only environment variable actually read anywhere in `src/arcavex` is `ARCAVEX_HOME` (a library
location, not a renderable-value default). §6.3 lists as a release criterion: "Runtime
configuration precedence is CLI flag → ARCAVEX_* environment variable → project.yaml →
~/.arcavex/config.toml → built-in default." I could verify the CLI-flag-over-project.yaml link
(`--format`/`--locale` on `render` correctly narrow a project's declared formats/locales — this
much works), but the ARCAVEX_*-env and config.toml links have nothing to exercise.

**Must change:** if `config.toml` is deliberately deferred to a later phase, say so in the brief
and the spec's phase mapping so this doesn't read as a silently dropped release criterion;
otherwise implement a minimal reader for at least one setting (e.g. default DPI or jobs count) so
the precedence chain is testable.

### DX-9 (P3) — `manifest.json`'s `timings_ms` is always empty

**Did:** inspected `timings_ms` on every manifest produced during this review (project renders,
direct renders, reruns).

**Happened:** always `{}`. Spec §5.3 lists "timings" among the manifest's captured fields
alongside diagnostics and output hashes, both of which *are* populated correctly.

**Must change:** low priority, but either populate compile/render timings or drop the field
until it's implemented — an always-empty provenance field invites someone to trust a number that
isn't there.

### DX-10 (P3) — `batch`'s human output has no aggregate summary line

**Did:** ran `arcavex batch "proj/batch/*" --jobs 4` against four projects, one deliberately
broken.

**Happened:** per-project `ok`/`failed` lines are legible and the failing project's diagnostic is
grouped right under its line with full file/line/hint detail — genuinely good for 4 projects. But
there's no closing tally ("3 ok, 1 failed") — at real batch sizes (the glob pattern in the brief's
acceptance command implies dozens of projects) a human has to count status lines themselves to
know if the run needs attention.

**Must change:** add a one-line summary at the end of human output; `--json`'s `entries[]` array
already lets automation compute this, so this is purely a human-output nicety.

## §6.3 release-criterion audit

| Criterion | Status |
|---|---|
| CLI flag → env → project.yaml → config.toml → default precedence | **Partial.** CLI-over-project.yaml verified working; config.toml unimplemented (DX-8). |
| JSON versioning on all new commands | **Pass.** `status`, `list-runs`, `diff`, `rerun`, `batch`, `template publish`, `project new/clone/set-status/upgrade` all carry `response_version: 1`. Direct fix of the Phase 3 DX-3 gap. |
| Inference reporting | Not heavily exercised in project mode this pass (no ambiguous format/locale cases arose); bare-template-name resolution correctly pins the *resolved* version into `project.yaml` rather than recording "latest" (spec §5.1 requirement), confirmed by inspecting `project.yaml` after `project new --template hello` against a name with a declared default. |
| Default output naming, shown before rendering | **Pass, but under-documented.** Project-mode outputs are named `<project-name>.<format>.<locale>.png` (confirmed: `meetup.a4.en.png`), which is sensible (distinguishes projects sharing a template) but neither README's naming rule nor §6.3's phrasing (`<template>.<format>...`) describes project-mode's name source — only direct mode is specified. |
| "No author must manually calculate a CAS hash" | **Pass** — asset hashing in manifests happened transparently; never had to touch a hash by hand. |
| Ambiguity produces a diagnostic, never silent choice | **Pass** for the cases tested — unknown template ref, duplicate publish, missing run, non-empty target, unknown status, detach-unavailable all produced located `ARC-*` diagnostics with hints and exit 1, never a silent fallback. |

## README-accuracy audit

Ran every project-workflow command exactly as the command table and prose describe (§12-style
requirement that README examples be executable):

- `template publish DIR --name N --version V [--no-default]` — matches exactly, including
  `--no-default` leaving the prior default alias untouched (verified with `ipen-poster@2.0.0`).
- `project new DIR --template REF [...]` — matches; scaffolds `data/<name>.yaml` pre-seeded from
  the template's `preview_data` (a nice touch not called out in README but pleasant to discover).
- `status [--project P]`, `render [--project P] [...]`, `list-runs [--project P]`, `rerun
  outputs/<run>`, `diff outputs/<a> outputs/<b>`, `batch <glob> [--jobs N]` — all match
  documented behavior and flags exactly.
- `project clone`, `project set-status`, `project upgrade --to V [--yes]`, `template detach` —
  all match their one-line descriptions; `template detach`'s warning code (`ARC-PRJ-007`) and its
  effect on `project.yaml` (`template: templates/ipen-poster`) are exactly as documented.
- The one substantive **mismatch**: `render [--project P]` is the only command of the
  render/validate/preview trio that actually implements "no template = project mode," even though
  README's mode-split framing ("render with no template arg = project mode") reads as if it
  describes a general CLI pattern rather than a `render`-only behavior (DX-1).
- Everything in the brief's own acceptance-command block ran verbatim without alteration except
  substituting the seeded `ipen-poster@1.0.0` for the placeholder `<seeded-lib-template-or-path>`.

## Friction log (chronological, as a new user)

1. Default `ARCAVEX_HOME` (`doctor`'s reported path) sits under the shared OS temp directory —
   fine for a single user, but with several review agents running concurrently against the same
   default library this session, I isolated my own `ARCAVEX_HOME` to avoid clobbering another
   agent's published template names. Worth knowing this is a real footgun in any environment
   running more than one Arcavex process against the default library concurrently (multi-seat CI,
   parallel agents) — no lock error surfaced, presumably because I never actually collided, so I
   can't confirm the locking the brief mentions (§8.3) actually prevents a silent stomp; I just
   sidestepped the scenario.
2. `arcavex validate` / `arcavex preview` failing with a bare "Missing argument" inside a freshly
   created project was the single most disorienting moment of the whole session — nothing in the
   error suggests project mode isn't supported here, it just looks like I forgot an argument.
3. Guessing the override-patch filename (`overrides/<template-name>.patch.yaml`) required reading
   the spec directly; a README-only user would have no route to this at all beyond noticing the
   empty `overrides/` folder and guessing.
4. `diff` reporting "no metadata changes" for a run whose only difference was a project patch was
   the moment I most distrusted the tool — it directly contradicts the dssim number two lines
   above it in the same output.
5. Everything else — publish, project new, render, list-runs, rerun, detach, upgrade's mutation
   safety, batch's per-project failure reporting — worked exactly as expected on the first try,
   which made the above four stand out more, not less.

## What impressed

- **`rerun`'s refusal to lie under drift.** Even though the root cause was opaque (DX-3), the
  moment the override file changed underneath a recorded run, it reported `reproduced: false`
  rather than silently returning stale-looking bytes or a false positive. That's the correct
  default when in doubt, and it's the hardest thing in this phase to get right.
- **JSON envelope discipline.** Every new command carries `response_version`, closing the exact
  gap the Phase 3 review flagged for `style list`/`style inspect`. Whoever picked this up
  clearly read that finding.
- **Mutation safety on `project upgrade`.** Confirmed byte-for-byte: `project.yaml` is untouched
  after a preview-only upgrade run, and only changes after an explicit `--yes`. No ambiguity, no
  silent partial state.
- **Render-time patch-failure diagnostics** (`ARC-TPL-092`): file, line, node id, and a correct
  hint, for a patch that broke because of an *upstream* template change the project author didn't
  even make. This is the detail level the upgrade-preview report (DX-5) should be reusing.
- **`diff`'s handling of non-overlapping output sets** ("only in A" / "only in B") when two runs
  render different format/locale sets — clean, no error, exit 0, exactly the kind of graceful
  degradation you want from a diff tool.
- **The full diagnostics catalog for every new `ARC-PRJ-*`/`ARC-LIB-*`/`ARC-RUN-*` code** I
  triggered (7 project codes, 4 library codes, 1 run code) had a complete, consistently-formatted
  doc entry, and `explain` worked on all of them without exception.
