# Backlog — deferred and post-v1 items

Items explicitly deferred by the specification (§12, §7.4, Post-v1) or accepted as P3
during reviews. Nothing here is required v1 scope.

## Deferred by specification

- Hostile Python-extension isolation / WASM extension runtime (§7.4)
- GPU rendering backend (§4.5)
- Vector-preserving PDF, CMYK / PDF-X prepress (§4.6)
- Animation / video rendering (§1.3)
- Hosted service concerns: accounts, tenants, quotas (§8.3)
- SQLite discovery index (§5.4 — files remain canonical)
- Automatic installation of older engine versions for compatibility reruns (§12 open)
- Hyphenation (unless a concrete template requires it — none did in v1)

## Deferred to Phase 7 (asset & cache budgets)

- **Derived-variant asset cache (§4.7).** Phase 4 landed the CAS core: ingest-by-sha256 with
  sidecar metadata and decode guards (max source bytes, max decoded pixels, format allowlist)
  enforced against the image header before decode — enough to pin assets in run manifests. The
  downscaled-variant cache keyed by `(hash, params)` under an LRU byte budget (so a 40 MP photo
  in a 400 px slot never decodes at full size twice) is deferred to Phase 7 with the other cache
  budgets, along with per-render wall-clock / surface-memory / output-dimension budgets (§8.3).

## Accepted P3 review findings

- **Composite `backdrop` snapshot (CR-1).** `CompositeContext.backdrop` is a read-only accessor
  reserved for the content painted below a node in z-order (spec §3.2), but in v1 it always
  returns `None`: the renderer does not snapshot the underlying canvas region into it. No shipped
  behaviour depends on it — the two composite effects (drop-shadow, glow) build from the
  element's own alpha — so this is deferred rather than fixed in Phase 3. Populating it requires
  reading back the correct device-space region of the (possibly nested element) canvas under the
  full CTM and clipping it to the node's paint region; that is a renderer change larger than the
  latent gap warrants now. The docstring and the construction site state the deferral honestly so
  no future composite effect assumes a live backdrop.
