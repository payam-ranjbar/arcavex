# Packaged installation

Arcavex must render from a plain `pip install`, with no dev tree present — the wheel ships the
bundled fonts, and ICU (`icudtl.dat`) comes with the `skia-python` dependency. This is verified end
to end by the `packaged-install` job in `.github/workflows/ci.yml` and by the transcript below,
captured on the Phase 7 development machine (Windows 11, Python 3.12, skia-python 144).

## ICU (`icudtl.dat`)

ADR-0001 notes that Skia's Unicode/ICU support needs `icudtl.dat`. In practice, `skia-python` 144
ships `icudtl.dat` inside its own package directory and locates it there, so an ordinary install
resolves ICU with no extra step — `arcavex doctor` confirms it (`icu ok — ICU available
(skia.Unicode built)`). If a future Skia build cannot find it, `doctor` reports the exact
remediation (copy `icudtl.dat` beside the base interpreter). No ICU data is packaged in the Arcavex
wheel; it would only duplicate the dependency's copy.

## Fonts

The wheel bundles the fonts under `arcavex/_bundled/fonts/` (via `force-include` in
`pyproject.toml`). The text service discovers them there when installed and from
`library-seed/fonts/` when run from the repo, so an installed engine and a dev checkout render from
the same families. `$ARCAVEX_HOME/fonts` is always additionally consulted.

## Transcript (clean venv, outside the dev tree)

```console
$ uv build --wheel
Successfully built dist/arcavex-0.1.0-py3-none-any.whl

$ uv venv /tmp/cleanvenv
$ uv pip install --python /tmp/cleanvenv arcavex-0.1.0-py3-none-any.whl

$ arcavex doctor --json        # run from a neutral directory, no dev tree
engine 0.1.0 ok True
  python     ok  Python 3.12.13
  skia       ok  skia-python 144.0.post2
  icu        ok  ICU available (skia.Unicode built)
  fonts      ok  4 bundled families: Estedad, Inter, Lalezar, Vazirmatn
  exporters  ok  png, jpeg, webp, pdf all available
  cache      ok  derived cache=~/.arcavex/cache/derived; budget=256000000 bytes
  temp_dir   ok  Writable temp dir
  paths      ok  home=.../arcavex [default (OS temp)]
  config     ok  config.toml absent; default dpi=per-format

$ arcavex render examples/hello-poster/template.yaml \
    --data examples/hello-poster/data.yaml --format square -o hello.png
Rendered hello.png

$ arcavex render examples/ipen-bilingual/template.yaml \
    --data examples/ipen-bilingual/data.yaml --format a4 --locale fa -o ipen.pdf
Rendered ipen.pdf   # RTL Farsi shaping works from the installed fonts
```

The installed engine's `hello.png` is **byte-identical** to the dev-tree render (same SHA-256),
confirming the package produces the same deterministic bytes as the source checkout.
