# Packaged installation

Arcavex must render from a plain `pip install`, with no dev tree present — the wheel ships the
bundled fonts, and ICU (`icudtl.dat`) comes with the `skia-python` dependency. This is verified end
to end by the `packaged-install` job in `.github/workflows/ci.yml` and by the transcript below,
captured verbatim on the Phase 7 development machine (Windows 11, Python 3.12, skia-python 144) by
building the wheel, installing it into a clean throwaway venv, and running the documented
quick-start from a neutral directory outside the source checkout.

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

Build the wheel, create a fresh venv, and install into it:

```console
$ uv build --wheel
Building wheel...
Successfully built dist\arcavex-0.1.0-py3-none-any.whl

$ uv venv cleanvenv
Using CPython 3.12.13
Creating virtual environment at: cleanvenv

$ uv pip install --python cleanvenv/Scripts/python.exe dist/arcavex-0.1.0-py3-none-any.whl
 + arcavex==0.1.0 (from file:///.../dist/arcavex-0.1.0-py3-none-any.whl)
 + skia-python==144.0.post2
 + typer==0.27.0
 ... (22 resolved dependencies)
```

From a neutral directory (no dev tree), `arcavex doctor` reports every probe green — ICU and fonts
resolve from the installed wheel alone:

```console
$ arcavex doctor
Arcavex engine 0.1.0
┌───────────┬────────┬────────────────────────────────────────────────────────┐
│ check     │ status │ detail                                                 │
├───────────┼────────┼────────────────────────────────────────────────────────┤
│ python    │ ok     │ Python 3.12.13                                         │
│ skia      │ ok     │ skia-python 144.0.post2                                │
│ icu       │ ok     │ ICU available (skia.Unicode built)                     │
│ fonts     │ ok     │ 4 bundled families: Estedad, Inter, Lalezar, Vazirmatn │
│ exporters │ ok     │ png, jpeg, webp, pdf all available                     │
│ cache     │ ok     │ derived cache=C:\Users\...\.arcavex\cache\derived;     │
│           │        │ budget=256000000 bytes (disposable)                    │
│ temp_dir  │ ok     │ Writable temp dir: C:\Users\...\AppData\Local\Temp     │
│ paths     │ ok     │ home=C:\Users\...\.arcavex [default (~/.arcavex)];      │
│           │        │ preview cache=C:\Users\...\.arcavex\cache\preview      │
│ config    │ ok     │ config.toml absent                                     │
│           │        │ (C:\Users\...\.arcavex\config.toml); default           │
│           │        │ dpi=per-format [default]                               │
└───────────┴────────┴────────────────────────────────────────────────────────┘
```

`doctor --json` emits the same report as versioned JSON (`--json` never prints the human table).
The `paths` and `cache` rows resolve the same home root (`~/.arcavex`) — both go through
`fsutil.home_dir()`, so they cannot disagree:

```console
$ arcavex doctor --json
{
  "response_version": 1,
  "ok": true,
  "engine_version": "0.1.0",
  "checks": [
    {"name": "python", "status": "ok", "detail": "Python 3.12.13", "hint": null},
    {"name": "skia", "status": "ok", "detail": "skia-python 144.0.post2", "hint": null},
    {"name": "icu", "status": "ok", "detail": "ICU available (skia.Unicode built)", "hint": null},
    {"name": "fonts", "status": "ok",
     "detail": "4 bundled families: Estedad, Inter, Lalezar, Vazirmatn", "hint": null},
    {"name": "exporters", "status": "ok", "detail": "png, jpeg, webp, pdf all available",
     "hint": null},
    {"name": "cache", "status": "ok",
     "detail": "derived cache=C:\\Users\\...\\.arcavex\\cache\\derived; budget=256000000 bytes (disposable)",
     "hint": null},
    {"name": "temp_dir", "status": "ok",
     "detail": "Writable temp dir: C:\\Users\\...\\AppData\\Local\\Temp", "hint": null},
    {"name": "paths", "status": "ok",
     "detail": "home=C:\\Users\\...\\.arcavex [default (~/.arcavex)]; preview cache=C:\\Users\\...\\.arcavex\\cache\\preview",
     "hint": null},
    {"name": "config", "status": "ok",
     "detail": "config.toml absent (C:\\Users\\...\\.arcavex\\config.toml); default dpi=per-format [default]",
     "hint": null}
  ]
}
```

Render both quick-start scenes from the installed package (absolute paths to the examples in the
checkout, output written into the neutral directory):

```console
$ arcavex render poster.yaml \
    --data event.yaml --format square -o hello.png
Rendered hello.png

$ arcavex render examples/future-archive-poster/template.yaml \
    --data examples/future-archive-poster/data/en.yaml --format a4 --locale fa -o ipen.pdf
inferred: data_overlay=data.fa.yaml
Rendered ipen.pdf
```

The installed engine's `hello.png` is **byte-identical** to the dev-tree render — both produce
SHA-256 `91f91c93792de0189aaaa1dabe99db691916cc3a4cf8c7016b457ff56dd11979`. This is not a
coincidence of one run: byte-for-byte reproducibility on the same engine version and platform is a
release-gate guarantee proven by the cross-process determinism tests
(`tests/unit/test_export_formats.py`, `tests/unit/test_derived_cache.py`), which re-render in
separate processes and assert identical `content_sha256`. The installed wheel is the same engine,
so it produces the same bytes.
