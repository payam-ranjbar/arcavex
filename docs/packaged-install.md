# Packaged installation

Arcavex must render from a plain `pip install`, with no dev tree present — the wheel ships the
bundled fonts, the seeded style packs, and the design skill, and ICU (`icudtl.dat`) comes with the
`skia-python` dependency. This is verified end to end by the `packaged-install` job in
`.github/workflows/ci.yml` (Linux and macOS, against a template the job writes itself, since the
wheel does not ship the examples) and by the transcript below, captured on 2026-09-04 on the
development machine (Windows 11, CPython 3.12.13, skia-python 144.0.post2, engine 0.1.0) by building
the wheel, installing it into a clean throwaway venv, and rendering the shipped examples from a
neutral directory outside the source checkout. `ARCAVEX_HOME` pointed at an empty directory for the
whole run, so nothing on the machine's existing Arcavex home could contribute.

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

Build the wheel, create a fresh venv, and install into it. The exact dependency versions are
whatever resolves within the bounds `pyproject.toml` declares on the day, so they move; these are
the ones that resolved when the transcript was captured:

```console
$ uv build --wheel
Building wheel...
Successfully built dist\arcavex-0.1.0-py3-none-any.whl

$ uv venv cleanvenv
Using CPython 3.12.13
Creating virtual environment at: cleanvenv

$ uv pip install --python cleanvenv/Scripts/python.exe dist/arcavex-0.1.0-py3-none-any.whl
 + arcavex==0.1.0 (from file:///.../dist/arcavex-0.1.0-py3-none-any.whl)
 + mcp==1.29.1
 + numpy==2.5.2
 + pydantic==2.13.5
 + rich==15.0.0
 + ruamel-yaml==0.19.1
 + segno==1.6.6
 + skia-python==144.0.post2
 + typer==0.26.8
 + watchfiles==1.2.0
 ... (their own dependencies follow)
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
│ cache     │ ok     │ derived cache=C:\...\home\cache\derived;               │
│           │        │ budget=256000000 bytes (disposable)                    │
│ temp_dir  │ ok     │ Writable temp dir: C:\Users\...\AppData\Local\Temp     │
│ paths     │ ok     │ home=C:\...\home [env ARCAVEX_HOME]; preview           │
│           │        │ cache=C:\...\home\cache\preview                        │
│ config    │ ok     │ config.toml absent (C:\...\home\config.toml);          │
│           │        │ default dpi=per-format [default]                       │
└───────────┴────────┴────────────────────────────────────────────────────────┘
```

`doctor --json` emits the same report as versioned JSON (`--json` never prints the human table).
The `paths` and `cache` rows resolve the same home root — both go through `fsutil.home_dir()`, so
they cannot disagree:

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
     "detail": "derived cache=C:\\...\\home\\cache\\derived; budget=256000000 bytes (disposable)",
     "hint": null},
    {"name": "temp_dir", "status": "ok",
     "detail": "Writable temp dir: C:\\Users\\...\\AppData\\Local\\Temp", "hint": null},
    {"name": "paths", "status": "ok",
     "detail": "home=C:\\...\\home [env ARCAVEX_HOME]; preview cache=C:\\...\\home\\cache\\preview",
     "hint": null},
    {"name": "config", "status": "ok",
     "detail": "config.toml absent (C:\\...\\home\\config.toml); default dpi=per-format [default]",
     "hint": null}
  ]
}
```

Render both quick-start scenes from the installed package. The template and data paths are
absolute paths into the checkout's `examples/` directory (the wheel does not ship them), shortened
here to `C:/src/arcavex`; the output is written into the neutral directory. The Future Archive
poster needs its own effect extension, so it is added and enabled first — into the empty home,
proving the extension pipeline works from the installed engine too:

```console
$ arcavex render C:/src/arcavex/examples/hello-poster/template.yaml \
    --data C:/src/arcavex/examples/hello-poster/data.yaml --format square -o hello.png
Rendered hello.png

$ arcavex ext add C:/src/arcavex/examples/future-archive-poster/extensions/archive-print
Added archive-print (enable it next)

$ arcavex ext enable archive-print
Enabled archive-print (active on the next run)

$ arcavex render C:/src/arcavex/examples/future-archive-poster/template.yaml \
    --data C:/src/arcavex/examples/future-archive-poster/data/fa.yaml \
    --format portrait --locale fa -o future-archive.pdf
Rendered future-archive.pdf
```

The installed engine's `hello.png` is **byte-identical** to the dev-tree render — both produce
SHA-256 `960958f9055404dd04f26f5e428b55aef2784de35c17d9ae834ee081277b5476` (engine 0.1.0,
skia-python 144.0.post2, Windows; the value changes whenever the hello poster or the engine does, as
it did when the example was re-created after the licence clean-up). This is not a coincidence of one
run: byte-for-byte reproducibility on the same engine version and platform is a release-gate
guarantee proven by the cross-process determinism tests (`tests/unit/test_export_formats.py`,
`tests/unit/test_derived_cache.py`), which re-render in separate processes and assert identical
`content_sha256`. The installed wheel is the same engine, so it produces the same bytes.
