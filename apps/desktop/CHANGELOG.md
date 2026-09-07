# Changelog

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
