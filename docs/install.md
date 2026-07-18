# Installation

Arcavex is a Python package with one heavyweight dependency, `skia-python` (which also carries the
ICU data Arcavex needs). It runs headless — no display, no browser, no network on the render path.
Python 3.11+ is required; the reference platform is CPython 3.12 with skia-python 144.

Once installed, verify the environment with [`arcavex doctor`](#doctor) before rendering.

## From source (development)

Clone the repo and create a virtual environment. The project targets [uv](https://docs.astral.sh/uv/)
but plain `pip` works too.

With uv:

```bash
uv venv
uv pip install -e ".[dev]"
```

With pip:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   •   POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` extra adds the test and lint toolchain (`pytest`, `hypothesis`, `ruff`, `mypy`,
`import-linter`, `pillow`, `mcp`). For a runtime-only install, drop it: `pip install -e .`.

The console entry point is `arcavex` (defined as `arcavex.clients.cli:main`). From a source
checkout it lives at `.venv/Scripts/arcavex.exe` (Windows) or `.venv/bin/arcavex` (POSIX).

## Packaged wheel (no dev tree)

Arcavex renders from a plain wheel install with no source tree present — the wheel bundles the four
fonts (`arcavex/_bundled/fonts/`, via `force-include` in `pyproject.toml`) and ICU ships with
`skia-python`. Build and install:

```bash
uv build --wheel
uv pip install --python <target-venv>/Scripts/python.exe dist/arcavex-0.1.0-py3-none-any.whl
```

The end-to-end proof — building the wheel, installing into a clean throwaway venv, and rendering the
quick-start from outside the checkout with byte-identical output to the dev tree — is captured
verbatim in [packaged-install.md](packaged-install.md), and enforced by the `packaged-install` CI
job. Read that page for the full transcript; it is not duplicated here.

## ICU (`icudtl.dat`)

Skia's Unicode/ICU support needs `icudtl.dat`. In practice `skia-python` 144 ships the file inside
its own package directory and locates it there, so an ordinary install resolves ICU with no extra
step — `arcavex doctor` confirms it (`icu ok — ICU available (skia.Unicode built)`). If a future
Skia build cannot find it, `doctor` reports the exact remediation (copy `icudtl.dat` beside the base
interpreter). No ICU data is packaged in the Arcavex wheel; it would only duplicate the dependency's
copy. Background: [ADR-0001](adr/0001-skia-python-144-platform-baseline.md).

## Fonts

Four families are bundled and are the only fonts the shaper uses (no system-font fallback, for
determinism): **Estedad**, **Inter**, **Lalezar**, **Vazirmatn**. They are discovered from
`arcavex/_bundled/fonts/` when installed and from `library-seed/fonts/` when run from the repo, so an
installed engine and a dev checkout render from the same families. `$ARCAVEX_HOME/fonts` is always
additionally consulted. A text node requesting a family that is not available reports `ARC-RND-010`.

## Configuration home

Arcavex keeps its home at `~/.arcavex` (override with `$ARCAVEX_HOME`). It holds the style/extension
stores, the derived-image and preview caches, and an optional `config.toml`. Runtime settings resolve
highest-first through **CLI flag → `ARCAVEX_*` env var → `project.yaml` → `~/.arcavex/config.toml`
→ built-in default**; `config.toml` also carries the `[budgets]` and `[cache]` tables (see the
[README config tables](../README.md#runtime-configuration-precedence-63)). `arcavex doctor` reports
whether a `config.toml` is present and which layer the default DPI resolves from.

## doctor

`arcavex doctor` is the one command to run after installing — it checks every prerequisite and
reports the engine version. On a healthy install every row is `ok`:

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
│ cache     │ ok     │ derived cache=…\.arcavex\cache\derived;                │
│           │        │ budget=256000000 bytes (disposable)                    │
│ temp_dir  │ ok     │ Writable temp dir: …\AppData\Local\Temp                │
│ paths     │ ok     │ home=…\.arcavex [default (~/.arcavex)];                 │
│           │        │ preview cache=…\.arcavex\cache\preview                  │
│ config    │ ok     │ config.toml absent (…\.arcavex\config.toml);           │
│           │        │ default dpi=per-format [default]                       │
└───────────┴────────┴────────────────────────────────────────────────────────┘
```

| Row | What it proves |
|---|---|
| `python` | The interpreter version (3.11+). |
| `skia` | `skia-python` imported and its version. |
| `icu` | ICU/Unicode is available — shaping and BiDi will work. |
| `fonts` | The bundled families were discovered. |
| `exporters` | PNG, JPEG, WebP, and PDF backends are all available. |
| `cache` | The derived-image cache directory and its byte budget. |
| `temp_dir` | A writable temp directory for atomic writes. |
| `paths` | The Arcavex home and preview-cache locations (and whether the home is the default). |
| `config` | Whether a `config.toml` is present and which layer supplies the default DPI. |

`doctor --json` emits the same report as versioned JSON (it never prints the human table alongside).

## Next steps

- [quick-start.md](quick-start.md) — a 10-minute path from a first render to exports and locales.
- [tutorials/](tutorials/) — build a template from scratch and a bilingual template worked example.
- [../README.md](../README.md) — the project overview and command summary.
