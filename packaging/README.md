# Packaging Arcavex as a standalone Windows binary

Builds `arcavex.exe` — the whole engine, its fonts, ICU, and a Python runtime in one folder, with
no Python installation on the target machine. Its purpose is distribution to people who will never
open a terminal: the binary is the payload of an MCP bundle (`.mcpb`) that Claude Desktop installs
by double-click.

| File | Role |
|---|---|
| [`arcavex.spec`](arcavex.spec) | The PyInstaller build definition — what goes in the bundle and why. |
| [`entry_arcavex.py`](entry_arcavex.py) | Entry script; delegates straight to `arcavex.clients.cli:main`. |
| [`build.py`](build.py) | Runs PyInstaller and applies the one post-build step the spec cannot. |
| [`verify_frozen.py`](verify_frozen.py) | Proves the binary is byte-identical to the installed engine. |

## Pinned desktop toolchains

The repository pins the locally verified desktop toolchains: Node `22.21.0` in `.nvmrc` and Rust
`1.97.1` in `rust-toolchain.toml`. Update a pin deliberately: install the candidate release, update
the corresponding pin, rebuild the sidecar, run `packaging/verify_frozen.py`, and commit the pin
only with passing verification evidence. Do not use moving aliases such as `stable` or a Node major
alone for release builds.

## Build and verify

```bash
.venv/Scripts/python.exe packaging/build.py           # -> dist/frozen/arcavex/arcavex.exe
.venv/Scripts/python.exe packaging/verify_frozen.py   # must print PASS
```

`--onefile` produces a single self-extracting `.exe` instead of a folder. It is easier to hand to
someone, but it unpacks ~116 MB to a temp directory on **every** launch, which an MCP client pays
as startup latency on each session. The default onedir build starts immediately, and since a
`.mcpb` is a zip either way, onedir is the right input for one.

## Why verification is not optional

Arcavex guarantees byte-identical output for identical inputs. Packaging is the step most likely
to break that guarantee *silently* — every failure mode below produces a working binary that
renders subtly different pixels, and none of them raise an error:

- **Missing package metadata.** `services.doctor.engine_version()` reads `importlib.metadata`, and
  the PDF exporter embeds `Arcavex <version>` as the PDF `Producer`. A frozen build without
  metadata reports `0.0.0+unknown`, so every exported PDF differs from the installed engine's.
  Hence `copy_metadata("arcavex")` in the spec.
- **Missing fonts.** Text falls back to another family and reflows. The bundle places fonts at
  `arcavex/_bundled/fonts`, exactly where the wheel puts them, so `services.text` discovers them
  with no frozen-mode branch in engine code.
- **Missing style packs.** These resolve to *nothing* rather than to an error. See below.
- **A different ICU.** Farsi shaping and digit handling change. See below.

`verify_frozen.py` renders the synthetic bilingual-fixture matrix (3 formats × 2 locales, plus both
A4 PDFs) with the dev install and the binary and compares SHA-256 digests, then compares the MCP tool
catalog. Anything less than a digest comparison would not have caught the two bugs found while
building this.

## Two traps worth knowing about

**The binary must be tested outside the source tree.** `services.style` used to locate style packs
only by walking up for a `pyproject.toml` marker. An `.exe` under `dist/` *inside the repo* finds
the developer's real checkout and appears to work perfectly; copy it anywhere else and every style
pack silently disappears. This was a live bug in the wheel too, fixed by shipping
`arcavex/_bundled/styles` and teaching `find_style_dirs` to look there first — mirroring the fonts
rule. `verify_frozen.py` now copies the bundle to a temp directory and re-probes it there, which is
the only reason the fix can be trusted.

**ICU data placement.** Skia looks for `icudtl.dat` beside the running executable, but PyInstaller
6 collects data into `_internal/`. Without the post-build copy in `build.py`, Skia prints
`SkIcuLoader: datafile missing` on every run and falls back to its built-in ICU. Output stays
byte-identical either way — this was measured, not assumed — but an engine that warns on every
invocation reads as broken to the audience this binary exists for.

## Third-party extensions work in the frozen binary

A frozen build embeds a real interpreter, and `services.extensions.loader` imports each extension
under a synthetic package whose `__path__` points at a directory on disk. That mechanism is intact
once frozen: scaffold → validate → add → enable → render all work from `arcavex.exe`, the new
effect appears in `effects list`, and disabling it makes the same template fail with the effect
absent from the registry. Renders that use a user-authored effect are byte-identical between the
binary and the dev install.

The constraint is the **dependency surface**. Extension code can import `arcavex.sdk`, the standard
library, and whatever is already bundled (numpy) — it cannot pull a new PyPI package, because there
is no environment to install into. The extension validator already restricts imports to the
`arcavex.sdk` surface, so a conforming extension stays inside what the bundle provides.

## Source protection: what this does and does not give you

PyInstaller stores compiled bytecode (`.pyc`), not `.py` source, so the engine's source is not
sitting in the bundle as readable text. **This is obfuscation, not protection.** Bytecode is
recoverable with off-the-shelf decompilers, and the bundle's contents can be extracted with
`pyi-archive_viewer`. Treat the binary as raising the effort required, not as a licensing or IP
boundary. Anything that must not be redistributed belongs on a server, not in a shipped artifact.

## Known limitations

- **Windows x64 only.** skia-python ships per-platform wheels, so macOS and Linux need their own
  build on their own machine or CI runner. The spec itself is platform-neutral.
- **Unsigned.** Windows SmartScreen will warn on first run ("More info" → "Run anyway"). Signing
  needs a code-signing certificate; budget it before distributing beyond people who trust you.
- **`ext test` runs golden fixtures in a subprocess** and expects a Python interpreter; it is a
  developer command and is not expected to work from the binary.
- **Extensions with third-party dependencies** cannot be installed into the frozen runtime.

## Next step

Wrap `dist/frozen/arcavex/` in an MCP bundle so Claude Desktop installs it by double-click:
`npx @anthropic-ai/mcpb init` to scaffold the manifest, declaring a `binary` server that runs
`arcavex.exe mcp serve`, then `mcpb pack`.
