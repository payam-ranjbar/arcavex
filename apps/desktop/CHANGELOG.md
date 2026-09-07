# Changelog

## 1.0.0 (2026-09-07)


### Features

* **contracts:** generate desktop types from MCP schemas ([fcd83c2](https://github.com/payam-ranjbar/arcavex/commit/fcd83c29184acc7b069a4e9a1ab3bd3339504279))
* **desktop:** add direct canvas manipulation ([3522e31](https://github.com/payam-ranjbar/arcavex/commit/3522e315f9809fbed1a2549a1e2c9250f740207f))
* **desktop:** add editable layer hierarchy ([dd1c18d](https://github.com/payam-ranjbar/arcavex/commit/dd1c18dec3dd8a64fdd590b11f8a2bca6b04a323))
* **desktop:** add Move up and Move down to the layer actions ([a17e437](https://github.com/payam-ranjbar/arcavex/commit/a17e4377ddf0917895c536833fb600271c9e6795))
* **desktop:** add project sync and latest-wins rendering ([e4043f3](https://github.com/payam-ranjbar/arcavex/commit/e4043f34b6be7f06cb110029c7ef218a50d6a26f))
* **desktop:** add semantic command and history bus ([e3a0487](https://github.com/payam-ranjbar/arcavex/commit/e3a0487d9410bb83447792279ef9fdd054a5fbd5))
* **desktop:** add semantic property inspectors ([9e4cd92](https://github.com/payam-ranjbar/arcavex/commit/9e4cd923276c6f40169dc20f169212a65c6f2c47))
* **desktop:** add zoom, actual size, and save image ([7362d26](https://github.com/payam-ranjbar/arcavex/commit/7362d26783e52428ff876da5db705bc3a6bfba70))
* **desktop:** build the branded extensible workbench ([481cf1e](https://github.com/payam-ranjbar/arcavex/commit/481cf1e2d4a4b5b8ec5e3aeb240472ca9bd690e3))
* **desktop:** complete the live project viewer ([7812430](https://github.com/payam-ranjbar/arcavex/commit/78124309c4500cb9f6767c0790dd107a7efae62c))
* **desktop:** establish Tauri React application boundaries ([2fd83e8](https://github.com/payam-ranjbar/arcavex/commit/2fd83e84a2502d4638caf3fbfe1d170faf338ed2))
* **desktop:** gate and document editing in the packaged product ([d9f6466](https://github.com/payam-ranjbar/arcavex/commit/d9f6466c7344ef0188d46b231cb2bad462f173a8))
* **desktop:** let the inspector change type, colour, and appearance ([ff616bf](https://github.com/payam-ranjbar/arcavex/commit/ff616bf1955274624f9dd05d6e007129c7fa8219))
* **desktop:** pan the canvas, type a hex colour, and name the size unit ([1e9b2e4](https://github.com/payam-ranjbar/arcavex/commit/1e9b2e4eff555d16aefa396fb84f630dae1c636a))
* **desktop:** put the window back when it collapses ([8a9541c](https://github.com/payam-ranjbar/arcavex/commit/8a9541cbaa482a6241d0b923d2bb5f7ac7399f8b))
* **desktop:** record a panic instead of vanishing ([ca17340](https://github.com/payam-ranjbar/arcavex/commit/ca17340b4dd17bf8b1819e27ef09e780f0586daf))
* **desktop:** supervise the pinned MCP engine sidecar ([cd6d78b](https://github.com/payam-ranjbar/arcavex/commit/cd6d78bab78d378bce1d67c8940531eee440e143))
* **desktop:** surface undo, redo, and refused edits ([8d71312](https://github.com/payam-ranjbar/arcavex/commit/8d71312a166ae953e55305d6130d277892dc5a87))
* **editor:** define semantic transaction contracts ([74ad076](https://github.com/payam-ranjbar/arcavex/commit/74ad076ed4db732759613a045248e2341b0fb47a))
* **engine:** execute revision-safe semantic edits ([97a18da](https://github.com/payam-ranjbar/arcavex/commit/97a18da4469227cb2fb00279dcecd0164fe249a9))
* **engine:** report what a text layer actually rendered as ([f2641ab](https://github.com/payam-ranjbar/arcavex/commit/f2641ab472803a09c8b20b363f27bd4f422ea6b5))


### Bug fixes

* **contracts:** stop drift checking from healing what it should catch ([abdbd30](https://github.com/payam-ranjbar/arcavex/commit/abdbd30910e002a97b7ce671bb16550bac7ad2fb))
* **desktop:** call the editor tools by the names the engine registers ([6328ca0](https://github.com/payam-ranjbar/arcavex/commit/6328ca01e6c38a501ed8b22b5bf6a89c2491b32f))
* **desktop:** make Close project actually close the project ([f9887fd](https://github.com/payam-ranjbar/arcavex/commit/f9887fdb9f2c26a6d65384767ea04459ac9a9553))
* **desktop:** make the effect toggle write a field the engine accepts, and add the Reload it promised ([152eaaf](https://github.com/payam-ranjbar/arcavex/commit/152eaafbca0584a51cc6e70e2910e7f0a3e58c58))
* **desktop:** make the packaged edit check exercise an editable project ([330ee85](https://github.com/payam-ranjbar/arcavex/commit/330ee859bfed7e934f4675c370711e9bbdf549f1))
* **desktop:** say what typing over a data binding costs ([2503613](https://github.com/payam-ranjbar/arcavex/commit/250361340dd7fcfb6ba1f3749f92aa158ac3b82a))
* **desktop:** say why a render failed instead of showing a black canvas ([bd8254a](https://github.com/payam-ranjbar/arcavex/commit/bd8254ab0871eb7995708cca12c7c5142154498b))
* **desktop:** show the diagnostics a failed render actually carried ([63b2489](https://github.com/payam-ranjbar/arcavex/commit/63b2489c17947a351cb4642957236a2c3a0da913))
* **desktop:** show the render the canvas says it is showing ([f5ba93f](https://github.com/payam-ranjbar/arcavex/commit/f5ba93f192a02bee27edcc331734f8ce2db81eb8))
* **desktop:** stop the activity log blaming someone else for your own edits ([2855072](https://github.com/payam-ranjbar/arcavex/commit/28550727876c47e4d7fdb76b83fcb61d4d9ceb13))
* **desktop:** stop the window vanishing when a target is switched ([7d4239a](https://github.com/payam-ranjbar/arcavex/commit/7d4239aa681ac377918ccfd4765357e30924c2d4))
* **desktop:** write alignment where the renderer reads it, and actually save a file ([b2a00a8](https://github.com/payam-ranjbar/arcavex/commit/b2a00a8eb96db71df6f6bee52139ad86759e62a0))


### Performance

* **desktop:** proof at screen resolution, export at print resolution ([16e5bbb](https://github.com/payam-ranjbar/arcavex/commit/16e5bbbc8b0defef484625b959c4092530325518))

## Changelog

All notable changes to Arcavex Desktop. The desktop is versioned independently of the Arcavex
engine it bundles: `desktop-vA.B.C` tags this application, `engine-vX.Y.Z` tags the engine, and
[`src-tauri/binaries/engine-lock.json`](src-tauri/binaries/engine-lock.json) records exactly which
engine build a desktop release ships.

Release Please maintains the entries below from Conventional Commits touching `apps/desktop`; do
not edit released sections by hand.

## Unreleased

The Foundation and Phase 1 viewer, not yet published as a `desktop-v*` release:

- Tauri 2 + React workbench with a Rust core owning the engine sidecar, project watcher, and
  latest-wins render scheduler.
- Projects open in place and are never copied or rewritten by viewing them.
- Live preview of the active format and locale, with stale marking for other targets.
- Read-only Layers panel over the engine's authored and rendered hierarchies, with canvas
  hit-testing and selection.
- Diagnostics, variants, activity stream, proposals queue, and visible automation, extension, and
  live-render modes.
- Themeable branded shell with Studio Dark, Light, and High Contrast.
- Windows x64 NSIS installer carrying a digest-pinned engine, with signed updater artifacts.
