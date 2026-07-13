# Phase 02 remediation — layout, text, locales, masks, inspection

Remediation of the phase-02 code review (CR-1..CR-19) and DX/design review (DX-1..DX-15) plus
the design fixes to `examples/ipen-bilingual`. Root-cause fixes only; no test or acceptance was
weakened. New ADR: `docs/adr/0002-direction-inheritance-and-data-layering.md`.

## Verdict

All P1/P2 findings fixed; the P3 batch done except two explicitly-justified deferrals below.
The six ipen renders were re-viewed and self-assessed as design-review-passing. Full suite
**305 passed** (was 277), ruff clean, mypy `--strict` kernel clean, lint-imports 3/3 kept,
every acceptance command and seeded failure behaves per spec, and the fa square render is
byte-identical across two runs.

## Adjudication notes (binding, recorded in ADR-0002)

- **CR-6** — an undirected group inherits `direction` from the nearest ancestor group that
  declares one (root default from the locale, else `ltr`), resolved at compile time and threaded
  into children.
- **CR-10 vs phase-1 CR-5** — explicit `null` in *any* data layer binds null (a value, §4.1.4):
  never omission, never default-resurrection; explicit null for a required variable is still an
  error. Only omission selects the default. Phase-1 tests that encoded `null ≡ omission` were
  renamed/rewritten.
- **DX-4 data layering** — effective data = defaults/preview → template `locales.<L>.data` →
  user `--data` → user sidecar `data.<L>.yaml`; user data always outranks template data, the
  sidecar outranks base user data. Both overlays are reported as inferences (even with `--json`;
  `--quiet` hides only the human line). Documented in README + ADR-0002.

## Finding → action → test

| # | Finding | Action | Test |
|---|---|---|---|
| CR-1 | `template inspect --resolved` not implemented | `Compiler.inspect_resolved` reads the PatchLog + final AST values; `Facade.inspect_resolved` + `TemplateResolvedReport`; CLI `--resolved [--format][--locale]` (human + JSON) | `test_cr1_resolved_reports_format_patch_layer` |
| CR-2 | unknown style/typography fields pass silently | `_reject_unknown_keys` whitelists per block (style/paragraph/fit/constraints/size/run) → located `ARC-TPL-051` | `test_cr2_unknown_fields_rejected`, `test_cr2_unknown_size_field_rejected` |
| CR-3 | patch `set` silently creates unknown final key | `_do_set` requires the final segment to exist → `ARC-TPL-092` | `test_cr3_set_unknown_final_segment_errors` |
| CR-4 | aspect derives from *unclamped* axis | `_resolve_size` clamps the non-aspect axis first, then derives + clamps the aspect axis | `test_cr4_aspect_derives_from_clamped_axis` |
| CR-5 | aspect on stack cross axis → size 0 | `_stack_child_sizes` derives cross-aspect from the concrete main size; unresolvable → `ARC-LAY-055` | `test_cr5_stack_cross_aspect_resolves` |
| CR-6 | group direction doesn't inherit | `inherited_direction` threaded through `_build_node`/expanders; resolved before children | `test_cr6_direction_inherits_from_ancestor` |
| CR-7 | RTL derivation strings numerically wrong | `_derive_anchors` flips the printed offset sign for logical edges under rtl | `test_cr7_rtl_derivation_string_flips_offset` |
| CR-8 | digits miss exact-match numeric expressions | `_resolve_text` localizes the stringified exact-match numeric value | `test_cr8_cr9_digits` |
| CR-9 | `digits: arab`/`latn` validate then no-op | Arabic-Indic implemented; `en`/`latn` = Latin identity (documented); `locale_digits()` supports all four | `test_cr8_cr9_digits` |
| CR-10 | overlay `null` resurrects default | `provided`-set tracking; explicit null binds None, required-null errors | `test_cr10_explicit_null_does_not_resurrect_default`, `_required_is_error` |
| CR-11 | patches can't edit repeat/if nodes or root | `_search` descends into `node:`, `_locate` includes root, field ops unwrap the construct | `test_cr11_field_edit_through_if_wrapper`, `_root_addressable_accurate_diagnostic` |
| CR-12 | `fill` bypasses min/max in stacks | main-fill share and cross fill/stretch clamped to the child's spec | `test_cr12_stack_fill_respects_max` |
| CR-13 | truncate collapses to bare "…" in a short box | service flags the degenerate case; solver emits `ARC-LAY-051` | `test_cr13_truncate_sub_line_box_warns` |
| CR-14 | rotation AABB unused for anchors/overlaps | `sib_rects` stores the post-rotation AABB; overlaps use `paint_bounds` | `test_cr14_sibling_anchors_to_rotation_aabb`, `test_overlaps_suppress_full_bleed_background` |
| CR-15 | inspect omits transform + free regions | `LayoutNodeReport` gains `absolute_transform`, `paint_bounds_px`; report gains `free_regions` | `test_cr15_report_has_transform_and_free_regions`, `test_report_carries_transform_and_paint_px` |
| CR-16 | truncation measures base style, paints lead style | `_truncate` measures with the lead run's style (the painted one) | covered by truncate path in `test_cr13...` (see justification) |
| CR-17 | plain string `"!delete"` deletes | `is_delete` matches only the YAML tag | `test_delete_marker_removes_key`, `test_plain_delete_string_is_a_value_not_deletion` |
| CR-19 | invented 1.2 line-height divisor | line count divides by a *measured* single-line height (`_unit_line_height`); dead service-level `line_height` threading removed | existing text-fit tests + `max_lines` tests |
| DX-1 | stacks don't mirror under RTL | `_stack_children` mirrors horizontal coords within the content box under rtl | `test_dx1_hstack_mirrors_under_rtl` |
| DX-2 | `ARC-LAY-040` false-fires in stacks; stale hint | suppressed when the repeat is a stack child; hint + catalog entry rewritten | `test_dx2_no_overlap_warning_for_repeat_in_stack` |
| DX-3 | default name omits locale (overwrite footgun) | `_output_name` → `<stem>.<format>[.<locale>].png`, threaded through render/plan | `test_dx3_output_name_includes_locale` |
| DX-4 | silent two-source overlay precedence | documented layering (README + ADR-0002); both overlays reported as inferences | (doc/adjudication) |
| DX-5 | README doesn't teach / contradicts constraints | "Constraints and anchors" fully rewritten (sibling refs, logical start/end, aspect + `aspect(W:H)` sugar, min/max, fit block, stacks + RTL); false expressions/null claims removed | (README) |
| DX-6 | aspect catalog/hint mismatches; op typo not echoed | `ARC-IR-011/012`, `ARC-LAY-012/032/040` entries corrected; patch op error echoes the offending keys | `test_dx6_op_typo_echoes_key` |
| DX-7 | `max_lines` no-op with `h: fit_content` | fit_content height capped at `max_lines` lines | `test_dx7_max_lines_caps_fit_content_height` |
| DX-8 | overlap report signal-buried | suppress pairs where one node fully contains the other (backdrops/containers) | `test_overlaps_suppress_full_bleed_background` |
| DX-9 | debug labels overprint / clip off-canvas | deterministic label deconfliction + canvas clamping | debug determinism re-checked (byte-identical) |
| DX-10 | overlay file passed as `--data` fails opaquely | missing-var hint detects the `data.<L>.yaml` shape | `test_dx10_overlay_as_data_hints` |
| DX-11 | ipen story reads unfinished | story patch: taller hero + bottom-anchored footer band (rule + wordmark + localized CTA) | ipen snapshots + viewed |
| DX-12 | ipen A4 venue wrap + title rhythm | title → `fit_content` (even rhythm); A4 patch shrinks title/venue + widens venue | ipen snapshots + viewed |
| DX-13 | rotated accent not mirrored under rtl | fa locale patch flips `accent-bar` rotate to `+4` | ipen fa renders viewed |
| DX-14 | no `arcavex --version` | top-level `--version` callback (exit 0) | verified via CLI |

## Justified deferrals

- **CR-16 (per-run truncation styling)** — measurement now uses the lead run's style, matching
  what the solver paints, so measured and painted prefixes agree; per-run styling collapsing to
  the lead run on truncation is documented in `_truncate` rather than preserved (the binding has
  no per-run ellipsis API — ADR-0001).
- **Dead `line_height` model fields** — the `Style`/`ResolvedText`/`MeasureRequest.line_height`
  fields are kept as §4.3-v1 schema placeholders (removing them risks the content hash and the
  Phase-0 byte-identity baseline). The substantive CR-19 fix (the invented divisor) is done and
  the deferral is now a tracked ledger row (`§4.3b`).
- **DX-15 (zero-area text box warning)** — deferred: reliably detecting a zero-area box needs
  layout-time size resolution (heights are `fit_content`/`fill`), and `overflow: clip` already
  makes the empty result well-defined; low value for the added layout-time plumbing.

## Verification transcript

```
pytest tests                       -> 305 passed
ruff check .                       -> All checks passed!
mypy --strict src/arcavex/kernel   -> Success: no issues found in 12 source files
lint-imports                       -> Contracts: 3 kept, 0 broken
render square/story/a4 x en/fa     -> exit 0 (six renders viewed)
layout inspect square fa --json    -> response_version 1, ok true
render --debug (twice)             -> byte-identical
render square fa (twice)           -> byte-identical (determinism)
seeded: overflow:error             -> ARC-LAY-050, exit 1
seeded: constraint cycle           -> ARC-LAY-052, exit 1
template inspect --resolved a4 fa  -> format:a4 hero.h=38% (effective), direction rtl, digits fa
```

## Pointers for the re-reviewer

- **Highest-leverage new code**: `solver._stack_children` (RTL mirror), `_stack_child_sizes`
  (cross-aspect + fill clamps), `_resolve_size` (clamp-before-aspect), `_aabb_for` (CR-14);
  `compiler._build_context` (null semantics) and the `inherited_direction` threading;
  `overlays._do_set`/`_locate`/`_node_of` (patch traversal) and `is_delete`; `api._collect_overlaps`
  (+`_contains`), `_free_regions`, `_derive_anchors` (RTL), `Compiler.inspect_resolved`.
- **Behavior changes worth a second look**: the 0.5pt fit_content-width safety margin
  (`_FIT_WIDTH_MARGIN`, updated `test_fit_content_text`); title `fit_content` interacting with
  `shrink_to_fit` + `max_lines`; the a4 title/venue patch values (tuned by eye).
- **Snapshots** regenerated via `ARCAVEX_UPDATE_SNAPSHOTS=1`; all six now reflect the redesign.
```
