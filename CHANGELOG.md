# Changelog

All notable changes to Arcavex are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning for both
the engine and the IR schema.

## [1.0.0](https://github.com/payam-ranjbar/arcavex/compare/engine-v0.1.0...engine-v1.0.0) (2026-09-07)


### ⚠ BREAKING CHANGES

* remove five example posters; MIT licence; test fixtures replace them
* **deps:** bound every dependency, add Windows to the CI matrix
* **compiler:** templates carrying unknown fields now fail validation. This is the fix for fields that quietly did nothing — a template that validates now has no inert lines in it. No template shipped in this repository needed a change.

### Features

* **assets:** ARC-AST-020 warns when contain/cover scales mostly padding ([b26b441](https://github.com/payam-ranjbar/arcavex/commit/b26b441d7cf14052294915fea90871990f4ee6ad))
* **cli:** add `arcavex font` group for installing typefaces ([c68928a](https://github.com/payam-ranjbar/arcavex/commit/c68928a2b85c993bc8c7293733e08be61fb8e325))
* **contracts:** generate desktop types from MCP schemas ([fcd83c2](https://github.com/payam-ranjbar/arcavex/commit/fcd83c29184acc7b069a4e9a1ab3bd3339504279))
* **desktop:** add semantic command and history bus ([e3a0487](https://github.com/payam-ranjbar/arcavex/commit/e3a0487d9410bb83447792279ef9fdd054a5fbd5))
* **desktop:** add semantic property inspectors ([9e4cd92](https://github.com/payam-ranjbar/arcavex/commit/9e4cd923276c6f40169dc20f169212a65c6f2c47))
* **desktop:** complete Phase 2 graphic editing ([fbb3253](https://github.com/payam-ranjbar/arcavex/commit/fbb32539b3e3b18c37f7f216dfb832de3b9c0391))
* **desktop:** complete the live project viewer ([7812430](https://github.com/payam-ranjbar/arcavex/commit/78124309c4500cb9f6767c0790dd107a7efae62c))
* **desktop:** establish Tauri React application boundaries ([2fd83e8](https://github.com/payam-ranjbar/arcavex/commit/2fd83e84a2502d4638caf3fbfe1d170faf338ed2))
* **desktop:** gate and document editing in the packaged product ([d9f6466](https://github.com/payam-ranjbar/arcavex/commit/d9f6466c7344ef0188d46b231cb2bad462f173a8))
* **desktop:** let the inspector change type, colour, and appearance ([ff616bf](https://github.com/payam-ranjbar/arcavex/commit/ff616bf1955274624f9dd05d6e007129c7fa8219))
* **desktop:** surface undo, redo, and refused edits ([8d71312](https://github.com/payam-ranjbar/arcavex/commit/8d71312a166ae953e55305d6130d277892dc5a87))
* **editor:** add atomic locked transaction infrastructure ([1976060](https://github.com/payam-ranjbar/arcavex/commit/19760600e7b4249d7a153b3e4663612c011f853b))
* **editor:** add source-mapped authored tree operations ([6577f74](https://github.com/payam-ranjbar/arcavex/commit/6577f745c41cbe70b3fd96d5a9151286ae9cb66a))
* **editor:** define semantic transaction contracts ([74ad076](https://github.com/payam-ranjbar/arcavex/commit/74ad076ed4db732759613a045248e2341b0fb47a))
* **engine:** add editor metadata and automation proposals ([300a143](https://github.com/payam-ranjbar/arcavex/commit/300a14391eb4ab610edf15e5c0db4eaa1a8a2fb6))
* **engine:** add project snapshots and revision manifests ([9d83fc9](https://github.com/payam-ranjbar/arcavex/commit/9d83fc9ca4717bc42d2f400478fd546ab80018dc))
* **engine:** execute revision-safe semantic edits ([97a18da](https://github.com/payam-ranjbar/arcavex/commit/97a18da4469227cb2fb00279dcecd0164fe249a9))
* **engine:** expose authoritative layer trees and hit testing ([9a9b8c6](https://github.com/payam-ranjbar/arcavex/commit/9a9b8c6375077d6c60112a3772fbb698b0cd69dc))
* **engine:** expose desktop handshake and schemas ([74f6414](https://github.com/payam-ranjbar/arcavex/commit/74f6414beb4fcd39a446187f758a658197d31ad8))
* **engine:** patch one format in one locale, and address list items ([9504ba2](https://github.com/payam-ranjbar/arcavex/commit/9504ba24613bd79c7bbc21fa0db3c84e13310883))
* **engine:** report what a text layer actually rendered as ([f2641ab](https://github.com/payam-ranjbar/arcavex/commit/f2641ab472803a09c8b20b363f27bd4f422ea6b5))
* **engine:** say when a locale supplies no text of its own ([8aef3df](https://github.com/payam-ranjbar/arcavex/commit/8aef3df581e95021acd8f8ff331552194a9ec014))
* **layout:** classify sibling overlaps as content vs halo (P2-1) ([8aaa162](https://github.com/payam-ranjbar/arcavex/commit/8aaa162785b18c108700c8bf2414b341f5a008aa))
* **layout:** let a stack size to its children ([d0cbc0d](https://github.com/payam-ranjbar/arcavex/commit/d0cbc0de3964a1c6692550fccf15a52510bb5523))
* **mcp:** let an assistant learn this engine from this engine ([7b7c490](https://github.com/payam-ranjbar/arcavex/commit/7b7c4909cbb8e001d505ac564516b1925d163262))
* phase 0 — kernel core, direct render slice, diagnostics, hello poster ([74f5d15](https://github.com/payam-ranjbar/arcavex/commit/74f5d154e20a022a5e4f35c71060082cea441d24))
* phase 1 — authoring loop (pending review) ([1004936](https://github.com/payam-ranjbar/arcavex/commit/10049365dd31a6c097f64e732db06a8b3f98d14a))
* phase 2 — layout, text stack, locales, masks, inspection (pending review) ([157b799](https://github.com/payam-ranjbar/arcavex/commit/157b799d699f9cf6d5610d6f8715995be9a38d99))
* phase 3 — effects, styles, golden infra, pop-art grid (pending review) ([0d051d7](https://github.com/payam-ranjbar/arcavex/commit/0d051d74612012b40e4ce159f30ca68ba5348700))
* phase 4 — projects, library, provenance, runs, rerun, diff, batch (pending review) ([599e249](https://github.com/payam-ranjbar/arcavex/commit/599e249056816d9432cfdbb32b9871562168e7c8))
* phase 5 — MCP authoring surface, stdio server, agent session tests (pending review) ([eb50d77](https://github.com/payam-ranjbar/arcavex/commit/eb50d77358fc63511d1a83b658858b3409786132))
* phase 6 — trusted local extension SDK, loader, GoldenHarness, reference ext (pending review) ([9e02c15](https://github.com/payam-ranjbar/arcavex/commit/9e02c1576e67ba20041132c989b57267989c3f66))
* phase 7 — JPEG/WebP/PDF export, derived cache, budgets, packaged install (pending review) ([f5270ca](https://github.com/payam-ranjbar/arcavex/commit/f5270ca44783a09c2588e9712555c14908ebbdad))
* reference poster — bilingual IPEN template, 5 formats x 2 locales (pending design review) ([81f2081](https://github.com/payam-ranjbar/arcavex/commit/81f208101b206519f46b5340667c0d6f16f389e5))
* **skill:** ship a design skill and an installer for AI assistants ([c4a705f](https://github.com/payam-ranjbar/arcavex/commit/c4a705f8011caa921266a7393cdb054349dea3d2))
* standalone Windows binary (PyInstaller) + packaged style-pack fix ([d3d8667](https://github.com/payam-ranjbar/arcavex/commit/d3d866797ad5ddcceb20ca3a899f5e89aca82f05))


### Bug fixes

* **build:** the contracts gate never ran, and shelled-out tools lose non-ASCII output ([0b9fa04](https://github.com/payam-ranjbar/arcavex/commit/0b9fa040e1e0b0c5b1613caa73e5c563efd9dfc1))
* **cache:** the disk tier handed back an image over freed memory ([66c1744](https://github.com/payam-ranjbar/arcavex/commit/66c1744763e9370655475dd3a6e88e0dd2d4f342))
* **compiler:** reject unknown fields in every authoring scope ([7d93d56](https://github.com/payam-ranjbar/arcavex/commit/7d93d565ef1cc4afa9b9a9135c2cc9ac858e12ec))
* **contracts:** stop drift checking from healing what it should catch ([abdbd30](https://github.com/payam-ranjbar/arcavex/commit/abdbd30910e002a97b7ce671bb16550bac7ad2fb))
* **deps:** bound every dependency, add Windows to the CI matrix ([f0f1c39](https://github.com/payam-ranjbar/arcavex/commit/f0f1c39a9ffc5e774a9091d359f87c1fce449ca6))
* **desktop:** call the editor tools by the names the engine registers ([6328ca0](https://github.com/payam-ranjbar/arcavex/commit/6328ca01e6c38a501ed8b22b5bf6a89c2491b32f))
* **desktop:** make the packaged edit check exercise an editable project ([330ee85](https://github.com/payam-ranjbar/arcavex/commit/330ee859bfed7e934f4675c370711e9bbdf549f1))
* **desktop:** stop the window vanishing when a target is switched ([7d4239a](https://github.com/payam-ranjbar/arcavex/commit/7d4239aa681ac377918ccfd4765357e30924c2d4))
* **desktop:** write alignment where the renderer reads it, and actually save a file ([b2a00a8](https://github.com/payam-ranjbar/arcavex/commit/b2a00a8eb96db71df6f6bee52139ad86759e62a0))
* **diagnostics:** ARC-LAY-051 said raise min_size; raising makes it worse ([fdc02d0](https://github.com/payam-ranjbar/arcavex/commit/fdc02d0ded5a85426e9935ff3268d871c4364b22))
* **editor:** accept any absolute spelling of the project path ([7430a81](https://github.com/payam-ranjbar/arcavex/commit/7430a8145ecf5cc0b47432618055b40f9cc4b7d2))
* **editor:** edit the template the project actually renders ([d649a95](https://github.com/payam-ranjbar/arcavex/commit/d649a95758a4d85bc61db4a4a4edd29736e6c7c4))
* **editor:** let a client read a conflict from the diagnostics it already reads ([97cbe37](https://github.com/payam-ranjbar/arcavex/commit/97cbe37e4ba76edc18c298cac4e3e9c61ff669dc))
* **editor:** name what is wrong with a malformed transaction ([278bc8d](https://github.com/payam-ranjbar/arcavex/commit/278bc8dfbee81f26f7adce5f83bccf975c9e8448))
* **editor:** refuse an outside template with a way out, and give detach one ([312f115](https://github.com/payam-ranjbar/arcavex/commit/312f1158c35cece0cb782a39b0fa0441b9c3f7cf))
* **engine:** align patch provenance and layout summaries ([8ab1616](https://github.com/payam-ranjbar/arcavex/commit/8ab1616ee72744494155bc81c18f6d1a3197c361))
* **engine:** apply locale digits to displayed strings, not only numbers ([a2b94a1](https://github.com/payam-ranjbar/arcavex/commit/a2b94a1f8765f7b97780f11300fe43e0510c0683))
* **engine:** correct project snapshot render sources ([cf34d8f](https://github.com/payam-ranjbar/arcavex/commit/cf34d8fdba2bfd59269b225f17b2a9487d11b6e6))
* **engine:** document project snapshot diagnostic ([18e2926](https://github.com/payam-ranjbar/arcavex/commit/18e2926ef25ea515aff216d356b155df231daf0c))
* **engine:** harden layer provenance and geometry ([d68aecb](https://github.com/payam-ranjbar/arcavex/commit/d68aecb05e7aa3ae26a9aa76e78e937c67d908f8))
* **engine:** harden project mutation contracts ([654ee53](https://github.com/payam-ranjbar/arcavex/commit/654ee5302ee38f3b28264d3886e844c86d90f4a0))
* **engine:** harden snapshot text and symlink handling ([2867014](https://github.com/payam-ranjbar/arcavex/commit/2867014c3661f4969b1958ae657c9a64683b371b))
* **engine:** make translation and scale render consistently ([ff61740](https://github.com/payam-ranjbar/arcavex/commit/ff61740c4697acd82ed0bb5a33de31f9a19a661f))
* **engine:** preserve automation field comments ([bdd7884](https://github.com/payam-ranjbar/arcavex/commit/bdd78843dedd21bfd55043f2da5e1c7bddff355b))
* **engine:** preserve forward automation metadata ([febefe1](https://github.com/payam-ranjbar/arcavex/commit/febefe193268ad815350ca725419318b2df5f081))
* **engine:** split automation comment ownership ([50a9d76](https://github.com/payam-ranjbar/arcavex/commit/50a9d76feab46cc541bdf2bb20f84a9ff70cb862))
* **engine:** start a project from the template's own data when it ships some ([ad43536](https://github.com/payam-ranjbar/arcavex/commit/ad435369bf56565854ebdfcf453fd6471cfe34ba))
* **engine:** stop two hints contradicting each other, and take a run id ([afc3a6a](https://github.com/payam-ranjbar/arcavex/commit/afc3a6a9b0a024a602a30bf5ebb1a1a10b3ca5c6))
* **ext:** read golden-test output as UTF-8 and separate harness I/O failures ([781b265](https://github.com/payam-ranjbar/arcavex/commit/781b26533bb77116762044ec510848d5764a1f0c))
* **layout:** ARC-LAY-057 now covers max_lines under 'wrap', not just the shrink floor ([5bd5ff5](https://github.com/payam-ranjbar/arcavex/commit/5bd5ff5f1dc561933f8f9ac282e33e6c17c315ab))
* **layout:** report max_lines violations as ARC-LAY-057, not a box overflow ([2aab44c](https://github.com/payam-ranjbar/arcavex/commit/2aab44c34d0bf9f918817f74d019d30c62fdc036))
* **mcp:** let a run be rerun by the id that run_list reports ([595da68](https://github.com/payam-ranjbar/arcavex/commit/595da68144c9e8b81a0bf2e84408e2fe5e465b3e))
* phase 1 remediation accepted — CR-1..13, DX-1..6 root-cause fixes ([b5ecdf8](https://github.com/payam-ranjbar/arcavex/commit/b5ecdf8a6c1c20d678c0cb4d8ea1a2ba93ce7f5b))
* phase 2 remediation — provenance inspection, RTL stacks, strict fields, design fixes ([d8fadc3](https://github.com/payam-ranjbar/arcavex/commit/d8fadc39aa1ef9cd26fa7d7d62383aef5a810a87))
* phase 3 remediation accepted — --style flag, pop-art retune, effect discovery ([223a33b](https://github.com/payam-ranjbar/arcavex/commit/223a33b83978ec0dbf48a0794fe2d208061db6f7))
* phase 4 remediation accepted — patch provenance, project-mode validate/preview, config ([5350d77](https://github.com/payam-ranjbar/arcavex/commit/5350d7729277135d4593db5ef1a739670df959fa))
* phase 5 remediation accepted — MCP data-path P0, project render, parity ([6ba7fd7](https://github.com/payam-ranjbar/arcavex/commit/6ba7fd72ef56fac99e9d02034f3e5a7effc95b88))
* phase 6 remediation accepted — all-8-kind scaffolds, collision detection ([9b11427](https://github.com/payam-ranjbar/arcavex/commit/9b114275e0743b51e755a786d16da187ed74bd3c))
* phase 7 remediation accepted — ARC-EXP-001 wiring, honest transcript, disk-cache LRU ([f9a90cd](https://github.com/payam-ranjbar/arcavex/commit/f9a90cda5c351cfa0509c760343df983a3872c18))
* **project:** pin a template absolutely when no relative path exists ([95713ec](https://github.com/payam-ranjbar/arcavex/commit/95713ec56b06f13f984d4d3b28ef892407c11a18))
* reference poster accepted — design matrix 10/10 PASS, two-line venue (P3) ([74223f1](https://github.com/payam-ranjbar/arcavex/commit/74223f13d5547f6d92a876149e9308bf915c3d27))
* RR2-1/2/3 — data layering order per ADR-0002, a4 subtitle, overlay inference ([7c22c62](https://github.com/payam-ranjbar/arcavex/commit/7c22c6260532dd541e37369b981c31263bbb31af))
* **skill:** correct the Codex/ChatGPT install path to the Agent Skills location ([825ba6c](https://github.com/payam-ranjbar/arcavex/commit/825ba6c8e6799328128e2a22f0fdff37bcb211c6))
* write project previews under the home the engine reports ([7a1b3e6](https://github.com/payam-ranjbar/arcavex/commit/7a1b3e6dde1e1d5e53a7d3e9f05e7365d2dd7ad6))


### Performance

* **desktop:** proof at screen resolution, export at print resolution ([16e5bbb](https://github.com/payam-ranjbar/arcavex/commit/16e5bbbc8b0defef484625b959c4092530325518))


### Refactoring

* name the unexplained constants in geometry, fit, and effect bounds ([3e4e981](https://github.com/payam-ranjbar/arcavex/commit/3e4e98197fbb8070150ae3cbced641466892239a))
* one render path, and objective-only code comments ([264dab2](https://github.com/payam-ranjbar/arcavex/commit/264dab24c85be197c0591f1b75b6717a3dffb279))


### Documentation

* add four-style Arcavex MCP showcase ([2e0f8b7](https://github.com/payam-ranjbar/arcavex/commit/2e0f8b761b7c1e730b82b412a5aef13b9061362e))
* add MCP-authored Future Archive showcase ([6307408](https://github.com/payam-ranjbar/arcavex/commit/630740820a8a6e724c904a4eaaa5e9fb0a81a1bc))
* consolidate the Unreleased changelog and record fix-list status ([aed60de](https://github.com/payam-ranjbar/arcavex/commit/aed60de6b8d224e7a4a7f28573fd376ffb16c740))
* design Arcavex desktop architecture ([b83c7e1](https://github.com/payam-ranjbar/arcavex/commit/b83c7e1c07d1233e755e1eb9dcf222df812e226a))
* FINAL_REPORT — v0.1.0 release gate met, full verification green ([9cf58e3](https://github.com/payam-ranjbar/arcavex/commit/9cf58e357694654789033eb041e960883da41615))
* list the editing and packaged-desktop test layers ([196742c](https://github.com/payam-ranjbar/arcavex/commit/196742ce4b47e1100b66348f32e6d8c458f52ad5))
* **mcp:** say that patching source branches the undo chain ([52f4bed](https://github.com/payam-ranjbar/arcavex/commit/52f4bed2e51402a67313c12ebe6183681dd78081))
* phase 2 accepted — final re-review verdict, phase 3 brief with carry-overs ([0cb9d09](https://github.com/payam-ranjbar/arcavex/commit/0cb9d09a4c07302c5cd2494823a3aecab456654e))
* plan Arcavex desktop through Phase 2 ([2eed867](https://github.com/payam-ranjbar/arcavex/commit/2eed867b124296ddb1c55fe63f650ad109c15590))
* README showcase + docs index; ledger task-12 row (missed staging in 858572f) ([5cec56e](https://github.com/payam-ranjbar/arcavex/commit/5cec56e8b4506bef7f4169de5eac09fd0ccf9ee9))
* **skill:** teach the design skill how to change a design ([20bf24f](https://github.com/payam-ranjbar/arcavex/commit/20bf24fd20ffd9baad15adfadc436bb1c7e30e76))
* state the design-judgement boundary instead of leaving it implied ([59c3123](https://github.com/payam-ranjbar/arcavex/commit/59c3123ba0601bf44ea5b23be24a9dd4796bc136))
* task 12 consolidation — full doc set, indexed and command-verified ([858572f](https://github.com/payam-ranjbar/arcavex/commit/858572f38263ff578ac83deafb68c5d3cd341ebc))


### Chores

* remove five example posters; MIT licence; test fixtures replace them ([a5e09d8](https://github.com/payam-ranjbar/arcavex/commit/a5e09d8fce4640cccd5e73fa071b386cb52b6c51))

## [Unreleased]

### Changed — **breaking**: unknown fields are now rejected in every authoring scope

Arcavex promised that "unknown fields are rejected rather than silently ignored, so a misspelled
property cannot quietly do nothing." That held only for a handful of node sub-blocks. At the
template root, in `formats`, in a `canvas`, in a variable declaration, on a **node top level**, and
in an `effects[]` entry, an invented field validated clean and did nothing.

That is the worst possible failure for a template language meant to be authored by an AI agent: the
engine answered `OK template is valid`, so the author kept building on a field that was inert. In
the case that prompted this, an agent invented `condition:` on nodes, shipped three nodes relying on
it, and wrote the invented behaviour into handoff documentation as a real engine constraint.
Deleting every `condition:` line produced a byte-identical render.

**This is a breaking change for any template carrying a junk field — and it is the fix for fields
that quietly did nothing.** A template that validates now has no inert lines in it. If a template
starts failing, the reported field was never doing anything; delete it, or move it to the scope the
hint names. No template shipped in this repository needed a change.

- **Five new diagnostics**: `ARC-TPL-064` (unknown node field), `ARC-TPL-065` (template root),
  `ARC-TPL-066` (format / canvas), `ARC-TPL-067` (variable declaration), `ARC-TPL-068` (effect
  entry). `ARC-TPL-051` now also covers the `transform`, `mask`, `padding`, and `repeat`/`if`
  construct mappings, which were permissive too.
- **`ARC-TPL-064` names the real home of a wrong-scope field** instead of only rejecting it. There
  is no per-node `condition:` (the hint points at the structural `if:` / `node:` construct);
  `opacity`/`color`/`font_size` belong in `style`; `width`/`height` in `constraints.size`; `x`/`y`
  in `constraints.anchor`; `rotation` in `transform`. A field that is real but belongs to another
  node kind is told which kind owns it.
- **Fields that are authored-but-deliberately-unsupported keep their own, more useful diagnostic**:
  `line_height` still reports `ARC-TPL-053` and a stack's `wrap` still reports `ARC-LAY-056`.
- A guard test walks the whole authoring surface and asserts every scope rejects an unknown key, so
  a scope added later cannot silently reintroduce this.

### Fixed — generated docs

- `make docs-diagnostics` no longer rewrites every generated file with CRLF on Windows (the
  declared reference platform), which made a one-entry edit look like a 118-file change. The
  previously CRLF-committed files are normalized to LF.

### Added — overlap classification

- **`SiblingOverlap.kind` on `layout inspect`** — every reported overlap is now classified as
  `content` (the nodes' layout bounds genuinely intersect) or `halo` (only their effect-grown
  paint bounds do, i.e. a shadow, glow or torn-paper edge reaching over a neighbour). Overlap
  reporting previously compared `paint_bounds` alone, so a shadowed node was indistinguishable
  from a real collision and the useful signal got filtered away with the noise. The field is
  carried by `--json` and by the `arcavex_layout_inspect` MCP tool, so an agent that cannot see
  the render filters structurally instead of guessing.

### Changed — overlap reporting

- **`layout inspect` human output** groups overlaps: `content` ones are listed under the
  `overlaps` heading, `halo` ones demoted to a dimmed *effect spill* subsection, with a
  `N content, M effect spill` count on the heading itself.
- **`layout inspect` prints both boxes per node** — `bounds` (the resolved layout box) and
  `paint` (that box grown by rotation and effect expansion). Only `bounds` was shown before,
  which is why a halo overlap's rect looked like it came from nowhere.
- **`rect_pt` on a `content` overlap is now the content intersection**, not the paint
  intersection — so its width/height is the actual collision depth to correct. `halo` overlaps
  still report the paint intersection, which is the only one that exists for them.
- **The full-bleed backdrop suppression threshold** (a node covering ≥90% of its parent region is
  structure, not a collision) is measured on the layout box rather than the paint box, so a
  generous shadow can no longer promote an ordinary node into a backdrop and have its containment
  of a sibling silently dropped.

### Compatibility — overlap classification

`SiblingOverlap.kind` is **additive and forward-compatible**: it defaults to `content`, so a
payload serialised before the field existed still parses and a consumer that ignores the field is
unaffected. `response_version` therefore stays at `1` and no migration is required. Consumers that
want the new signal opt in by reading `kind`; the recommended filter for "real problems only" is
`kind == "content"`. Which node pairs are reported is unchanged — verified byte-for-byte against
the previous output across all 16 reference-poster and IPEN format × locale targets; the change is
purely the added label plus the more precise `rect_pt` for content overlaps.

### Added — font command group

- **`arcavex font` command group** — the supported way to use a typeface beyond the four bundled
  families, which previously required knowing (from prose in the docs) to drop a `.ttf` into
  `$ARCAVEX_HOME/fonts` by hand:
  - `font list [--json]` lists every resolvable family with its files, marks each **bundled** or
    **installed**, and names the directory `add` writes to — the answer `doctor` never gave, since
    it reported only the family *count*.
  - `font add PATH [--license PATH]` installs a `.ttf` into the Arcavex home and reports the family
    name **as the engine resolves it**, read from the file with the shaper's own resolver. A file
    stem and its internal family name routinely differ (`Lateef-Regular.ttf` provides `Lateef`) and
    `style.font` must name the family, so reporting the stem would hand back a name that does not
    render. `--license` copies a licence alongside the font, following the bundled OFL convention.
  - `font remove FAMILY` removes an installed family and its licence; a family bundled with the
    engine is refused (`ARC-RND-032`), because it backs the default font stacks.
- **`arcavex_font_list` MCP tool** — the legal `style.font` vocabulary is now discoverable by an
  agent alongside `arcavex_style_list`/`arcavex_effects_list`. Installing a font stays CLI-only, in
  the same class as `ext add`: an operator action on the machine, not an agent one.
- **New diagnostics** `ARC-RND-030`..`ARC-RND-034` for the font store (file not found, unusable
  typeface, bundled-family removal refused, no such installed family, unreadable/unwritable store).

### Changed — font diagnostics

- **`ARC-RND-010` (font family not available)** now lists the **nearest** available families ahead
  of the full list and names `arcavex font add` in its hint, so a typo and a genuinely missing
  typeface get different, actionable answers. Its catalog entry no longer implies the font set is
  closed.

### Fixed — font discovery

- **Fonts in the default Arcavex home were silently ignored.** Font discovery read `$ARCAVEX_HOME`
  directly and skipped the `~/.arcavex` default that `doctor` reports, so with `ARCAVEX_HOME` unset
  a font placed in `~/.arcavex/fonts` was never registered. Discovery now resolves through
  `fsutil.home_dir()` — the same single source of truth every other reader uses.

### Changed — **breaking**: every dependency is now version-bounded

The dev extra declared a bare `mcp`. A fresh `uv pip install -e ".[dev]"` resolved it to 2.0.0,
which removed `mcp.server.fastmcp` — so a clean clone could not collect its own test suite, and a
new contributor's first command failed. Six venvs built from the same file within one hour
resolved three different ways (1.28.1, 1.29.0, 2.0.0).

Every runtime and dev requirement now carries a floor and a cap, annotated with the version CI and
the reference machine actually verified. This can break an environment that was silently relying on
an out-of-range version. `tests/unit/test_packaging.py` fails on any dependency added without
bounds. Windows — the declared reference platform — is now in the CI matrix, which no encoding
defect below could have been caught by before.

### Added — asset shape advice

- **`ARC-AST-020`** warns when an image node uses `fit: contain`/`cover` and the asset's opaque
  artwork covers less than 40% of the canvas it declares. Both fit modes scale the *canvas*, so
  the artwork shrinks with it: a 512x512 logo whose mark is a 452x114 band renders as an
  unreadable smudge while every existing check passes. It is raised at compile time, so `validate`
  reports it before a pixel is drawn. The opaque bounding box is measured at ingest and recorded
  in the asset sidecar (`opaque_bbox`, additive and defaulting to `null`, so existing sidecars
  parse unchanged). `fit: fill` is not checked — it distorts rather than shrinks, which is visibly
  wrong without help.

### Fixed — diagnostics that pointed the wrong way

- **`ARC-LAY-051` told the author to raise `min_size`.** `min_size` is the *floor* of the shrink
  search, so raising it removes the only candidates that could still fit: measured on one node,
  30pt → 612pt, 20pt → 264pt, 12pt → 90pt, all failing, fitting only once the floor dropped to
  8pt. Following the hint made the failure monotonically worse. Both the catalog entry and the
  solver's raise-site hint now say lower, and tests pin the direction behaviourally.
- **`ARC-LAY-057` now covers `max_lines` under `policy: wrap`**, not only at the `shrink_to_fit`
  floor. A wrapping node with a line cap still reported `ARC-LAY-050`'s measured-vs-box height
  pair, which under `wrap` is provably inert: the same node reported an identical 76.0pt measured
  height at box heights of 60, 80, 200 and 400pt. The message now names the authored size, and the
  hint drops "lower `min_size`" — under `wrap` there is no floor to lower.

### Fixed — the release gate itself

- **`make contracts` never ran.** It invoked `python -m importlinter.cli lint`, which dispatches
  nothing: verified by appending a deliberately forbidden `clients` → `kernel` contract, against
  which the console script exits 1 and names the violating import chain while the module form still
  exits 0 with no output. The architecture gate inside `make verify` had been reporting green
  without checking anything. It now invokes the console script, and `tests/unit/test_toolchain.py`
  fails if the no-op form returns or the tool goes quiet.
- **Shelled-out tools lost non-ASCII output.** The Makefile exports `PYTHONIOENCODING`/`PYTHONUTF8`
  for every target (import-linter's own output measured 552 bytes without it against 1188 with —
  truncated, not merely missing a banner), and `scripts/benchmark.py`'s cold-start probe decodes
  its child as UTF-8 with an explicit error handler and reports a non-zero child exit instead of
  failing inside `float()`.
- **Generated diagnostics docs are guarded against CRLF at the byte level.** The existing mirror
  test reads through universal newlines and cannot see line endings by construction; the new check
  found seven files already committed with CRLF.

### Documentation

- **known-limitations.md states the design-judgement boundary.** Validation checks that a design is
  well-formed, never whether it is good — across a four-revision design session the engine reported
  clean validation for every draft, including those rejected outright. That is correct behaviour and
  was previously left implied. The doc names it with the evidence, says what could honestly be added
  later (contrast, cap-height at viewing scale, safe-area assertions, optical margins) and what could
  not, and `backlog.md` carries both as explicit non-commitments.

## [0.1.0] — 2026-07-15

First tagged release: a local-first, headless, deterministic, template-driven rendering engine.
Same inputs produce byte-identical outputs across every supported format.

### Added — Phase 7 (export and release hardening)

- **JPEG and WebP exporters** with quality/lossless control in `ExportOptions`. Lossy quality
  defaults to 90 (the conventional "visually lossless, small" setting) when `--quality` is omitted.
  Lossless WebP is bit-exact (VP8L), not approximated. JPEG flattens transparency over opaque white
  deterministically.
- **Raster-embedded RGB PDF exporter** (`-o out.pdf`) at the target DPI with the correct physical
  page size and `TrimBox`/`BleedBox` (A4 + bleed is first-class). The embedded raster is stored at
  full render resolution. Vector-preserving PDF and CMYK/PDF-X remain future work.
- **Exporter selection by output extension** — `.png`, `.jpg`/`.jpeg`, `.webp`, `.pdf`. New CLI
  flags `--quality` and `--lossless`.
- **Format determinism** extended to every exporter: identical inputs produce byte-identical
  JPEG/WebP/PDF. Exported files embed only stable metadata (engine version, render signature, color
  policy) — never timestamps or run ids.
- **Derived-asset LRU cache** (`$ARCAVEX_HOME/cache/derived/`): a large image drawn into a small
  slot is decoded and downscaled once, keyed by `(content-hash, target-size)` under a configurable
  byte budget. Both the in-memory and the on-disk tier are held under the byte budget, evicting the
  least-recently-used variant when over it. Disposable and never authoritative — a cold cache
  produces byte-identical output.
- **Per-render resource budgets** (`ARC-RND-020..023`): output-dimension, decoded-pixel,
  surface-memory (pre-flight), and wall-clock limits, configurable via `[budgets]` in `config.toml`,
  refusing an oversized render with a located diagnostic and exit code 4.
- **Path/symlink traversal guard** for template-relative assets (`ARC-AST-004`).
- **Located export-write failures** (`ARC-EXP-001`): an unwritable or invalid output path (a parent
  that is a file, a read-only directory, a full disk) reports as an actionable, located diagnostic
  with exit 1, instead of leaking as an internal engine error.
- **`arcavex doctor`** now self-tests the exporters (PNG/JPEG/WebP/PDF) and reports the derived
  cache directory and budget.
- **Packaged installation**: the wheel ships the bundled fonts (`arcavex/_bundled/fonts`); a clean
  install renders the quick-start without the dev tree.
- **CI workflow** (`.github/workflows/ci.yml`) for the linux-x86_64 + macos-arm64 + linux-aarch64
  matrix, plus a packaged-install job.
- **Documentation**: `docs/performance.md` (measured actuals), `docs/testing.md` (per-platform
  golden strategy), and a benchmark harness (`scripts/benchmark.py`).

### Added — earlier phases (0–6)

- **Phase 0–1**: pure kernel + SPI contracts, registry, Skia backend, anchor layout solver, PNG
  export, the template compiler, expression evaluator, and the diagnostic system.
- **Phase 2**: layout (stacks, anchors), the SkParagraph text stack (shaping, BiDi, RTL, fit
  policies), locales, masks, rotation, and layout inspection.
- **Phase 3**: the effect engine (geometry/color/raster/composite categories with fusion), shape
  generators, and style packs.
- **Phase 4**: the content-addressed asset store with decode guards.
- **Phase 5**: projects, the versioned library, run manifests, rerun/diff provenance, and the MCP
  authoring surface.
- **Phase 6**: the trusted-local extension SDK, loader, and golden harness.

### Determinism guarantees

- Rendering confined to bundled fonts; no system-font fallback.
- All randomness flows from a seeded per-effect RNG.
- Atomic writes (temp file + rename) for every output; interrupted renders publish nothing.
- Immutable completed run directories; timestamps and run ids live only in manifests.

[0.1.0]: https://example.com/arcavex/releases/0.1.0
