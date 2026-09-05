# Installation

Arcavex is a Python package with one heavyweight dependency, `skia-python` (which also carries the
ICU data Arcavex needs). It runs headless — no display, no browser, no network on the render path.
Python 3.11+ is required; the reference platform is CPython 3.12 with skia-python 144.

Once installed, verify the environment with [`arcavex doctor`](#doctor) before rendering, then
[teach your assistant](#teach-your-assistant) to use it.

## Global command (the install for using Arcavex)

[uv](https://docs.astral.sh/uv/) installs Arcavex into an environment of its own and puts one
`arcavex` command on your PATH. There is no virtual environment to activate; `--python 3.12` asks for
the reference interpreter, and uv downloads a managed copy by itself if the machine has none:

```bash
uv tool install --python 3.12 git+https://github.com/payam-ranjbar/arcavex
arcavex doctor
```

**No Python or uv on the machine yet?** Install uv first, then open a new terminal so it is on PATH:

- Windows: `winget install --id=astral-sh.uv -e`
- macOS or Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

If the install ends with a warning that uv's tool directory `is not on your PATH`, run
`uv tool update-shell` and open a new terminal; `arcavex` is then found. To update later, run the
same `uv tool install` command again with `--reinstall`. To remove it, `uv tool uninstall arcavex`.

From a clone of the repository, `uv tool install <path-to-clone>` installs that checkout the same
way (it does not track later edits to the clone — use the [development install](#from-source-development)
for that).

The package is not on PyPI yet and there are no GitHub releases yet. Once it is published,
`uv tool install arcavex` (or `pipx install arcavex`) becomes the whole install, and releases will
attach the wheel; until then the repository URL above is the install.

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
`import-linter`, `pillow`). The MCP server needs no extra: `mcp` is a runtime dependency, so
`arcavex mcp serve` works from every install. For a runtime-only install, drop the extra:
`pip install -e .`.

The console entry point is `arcavex` (defined as `arcavex.clients.cli:main`); `python -m arcavex`
is the same program for an interpreter whose scripts directory is not on PATH. A venv install does
**not** put `arcavex` on your PATH by itself: from a source checkout it lives at
`.venv/Scripts/arcavex.exe` (Windows) or `.venv/bin/arcavex` (POSIX), or run it as
`uv run arcavex …` from the checkout, or activate the venv first. The [global command](#global-command-the-install-for-using-arcavex)
route avoids this.

## Packaged wheel (no dev tree)

Arcavex renders from a plain wheel install with no source tree present — the wheel bundles the four
fonts (`arcavex/_bundled/fonts/`, via `force-include` in `pyproject.toml`), the seeded style packs,
and the design skill, and ICU ships with `skia-python`. Build and install:

```bash
uv build --wheel
uv pip install --python <target-venv>/Scripts/python.exe dist/arcavex-0.1.0-py3-none-any.whl
```

The end-to-end proof — building the wheel, installing into a clean throwaway venv, and rendering the
quick-start from outside the checkout with byte-identical output to the dev tree — is captured
verbatim in [packaged-install.md](packaged-install.md), and enforced by the `packaged-install` CI
job. Read that page for the full transcript; it is not duplicated here.

## Teach your assistant

Two commands connect an AI assistant to the engine; both are optional for a person using the CLI
alone.

```bash
arcavex skill install    # the design skill, into each assistant's own skill directory
arcavex mcp install      # the MCP server, registered with Claude Code / Claude Desktop / Codex
```

A host reads its skills when it starts, so **restart the assistant, or open a new session, after
`skill install`**; the same applies after `mcp install`, which the host reads at connection time.
`skill install --list` shows every destination without writing; `--target`, `--path DIR`, and
`--project` choose where it goes ([cli.md#skill](cli.md#skill)). `mcp install --print` shows the
configuration snippet for a host it does not know, and [cli.md#mcp](cli.md#mcp) covers serving,
registering, and the tool catalog. An assistant with a shell needs only the skill; one that speaks
MCP but has no shell (Claude Desktop) needs the server, which also serves the skill to it as a
resource.

## ICU (`icudtl.dat`)

Skia's Unicode/ICU support needs `icudtl.dat`. In practice `skia-python` 144 ships the file inside
its own package directory and locates it there, so an ordinary install resolves ICU with no extra
step — `arcavex doctor` confirms it (`icu ok`).

Skia's loader looks *next to the base interpreter* first, though, and says so out loud when the file
is not there:

```
SkIcuLoader: datafile missing: …\cpython-3.12-windows-x86_64-none\icudtl.dat.
```

That line is printed to stderr on every command — above `doctor`'s own all-ok table, and at the
start of every `mcp serve` session — and it is **harmless**: Skia then loads the copy inside
`skia-python`, and shaping, bidi and line breaking all work. Arcavex will not write ten megabytes
into a shared interpreter to quiet another library, so `doctor` names the line instead and prints
the one-line remedy for anyone who wants it gone: copy `icudtl.dat` from `site-packages` next to
the interpreter `doctor` names.

If a future Skia build cannot find the file at all, `doctor` reports that as a failed check with the
same remediation. No ICU data is packaged in the Arcavex wheel; it would only duplicate the
dependency's copy. Background: [ADR-0001](adr/0001-skia-python-144-platform-baseline.md).

## Fonts

Four families are bundled: **Estedad**, **Inter**, **Lalezar**, **Vazirmatn**. Together with any
you install, they are the only fonts the shaper uses — there is no system-font fallback, because
determinism requires it, so a typeface merely installed on the operating system will not resolve.
Bundled families are discovered from `arcavex/_bundled/fonts/` when installed and from
`library-seed/fonts/` when run from the repo, so an installed engine and a dev checkout render from
the same families. The Arcavex home's `fonts/` directory is always additionally consulted.

`arcavex font list` reports every available family and names the install directory:

```console
$ arcavex font list
Estedad bundled (3 file(s))
  …
install fonts into: C:\Users\you\.arcavex\fonts
add one with: arcavex font add <path/to/font.ttf>
```

To use any other typeface, install it. `add` reports the family name to write in `style.font`,
read from the file itself — a file stem and its internal family name routinely differ:

```console
$ arcavex font add ~/Downloads/Lateef-Regular.ttf --license ~/Downloads/OFL.txt
Installed Lateef into C:\Users\you\.arcavex\fonts
  use it in a template as: style: {font: Lateef}
```

`--license` copies the licence alongside the font, the convention the bundled OFL licences follow.
`arcavex font remove FAMILY` removes an installed family; a bundled one is refused. A text node
requesting a family that is not available reports `ARC-RND-010`, whose hint lists the nearest
available families and points at `arcavex font add`. Full reference: [cli.md](cli.md#font).

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
