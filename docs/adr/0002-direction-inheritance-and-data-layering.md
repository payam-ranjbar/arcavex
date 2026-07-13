# ADR 0002 — Direction inheritance, null-as-value, and locale data layering

- Status: accepted
- Date: 2026-07-12
- Phase: 2 (layout, text, locales) — remediation

## Context

Phase 2 introduced logical `start`/`end` edges resolved through a group's `direction`, a
locale system with a `data` overlay, a user-side `data.<locale>.yaml` sidecar convention, and
per-format/per-locale patches. The first implementation left three semantics under-specified,
and the phase-2 code and DX reviews (CR-6, CR-10 vs. phase-1 CR-5, DX-4) flagged them as either
ambiguous or in direct conflict with the spec. This ADR records the adjudicated decisions.

## Decision 1 — group `direction` inherits from the nearest enclosing group (CR-6)

A `group` that does not declare a `direction` inherits it from the **nearest ancestor group
that declares one**. The root default comes from the requested locale's `direction` (else
`ltr`). Inheritance is resolved at compile time and threaded into each group's children, so
logical `start`/`end` edges and stack mirroring behave consistently through arbitrarily nested
groups without the author re-declaring `direction` at every level.

Spec basis: §4.2 states logical edges resolve "through the enclosing group's direction", and
Appendix A carries a single root-level `direction: rtl` that the whole tree honors. Without
inheritance, an undirected nested group would silently flip back to `ltr`.

## Decision 2 — explicit `null` binds null in every data layer (CR-10)

An explicit `null` in **any** data layer (the base `--data` file, a locale `data` overlay, or a
sidecar) is a real value, per §4.1.4 ("null remains a valid data value and therefore does not
mean deletion"). It therefore:

- binds `None` (so `{{ x is none }}` is true), and is **not** type/enum-checked;
- never falls back to the variable's declared `default` (no default-resurrection);
- for a **required** variable, remains an error (`ARC-TPL-014`).

Only genuine **omission** (an absent key) selects the default or the optional-none fallback.
This supersedes the phase-1 CR-5 framing of "explicit null ≡ omission", which held only because
the earlier build dropped all null-valued keys before variable resolution; the phase-1 tests
that encoded that framing were updated. Deletion of an overlay key uses the explicit YAML tag
`!delete` (e.g. `key: !delete`); the plain string `"!delete"` is ordinary data (CR-17).

## Decision 3 — locale data layering and sidecar precedence (DX-4)

Effective data is resolved in four layers, each overriding the previous under the §4.1.4
overlay-merge semantics (recursive mapping merge, whole-replace for scalars/lists, `null` is a
value, `!delete` removes):

1. template `preview_data` / variable `default`s (used only when no `--data` is supplied);
2. template `locales.<L>.data` overlay (ships localized default strings);
3. the user `--data` base file;
4. the user sidecar `data.<L>.yaml` beside the base file (auto-applied for `--locale L`).

Rationale for the ordering: template-shipped locale strings should be able to localize
*defaults*, but user-supplied data must always outrank template data; and the locale-specific
sidecar (the most specific user input) must outrank the base user data. Both overlay
applications (the inline locale data and the sidecar) are reported as `inferred` breadcrumbs on
every surface, including `--json`; `--quiet` suppresses only the human-readable line. Patch
layers apply format patch → locale patch, before expression evaluation, and are inspectable via
`template inspect --resolved`.

## Consequences

- Nested RTL/LTR groups mirror correctly without redundant `direction` declarations.
- `null` is expressible and distinguishable from both omission and `!delete` across all layers;
  authors can null out a defaulted value deliberately.
- The precedence trap where a convention sidecar silently shadowed inline locale data is now a
  documented, inspectable ordering rather than a silent choice.
- Deterministic rendering is unaffected: all three decisions are resolved at compile time and do
  not depend on any runtime state.
