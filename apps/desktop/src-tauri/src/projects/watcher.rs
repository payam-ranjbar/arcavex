//! Turns a burst of filesystem noise into one stable, attributed change set.
//!
//! An editor writing a file produces several events; a render writes into `outputs/`, which is
//! not project source at all. The coalescer is a pure state machine over (path, instant) pairs so
//! the debounce and attribution rules are tested without a filesystem or a clock.

use std::collections::{BTreeSet, HashSet};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

/// Long enough to swallow an editor's write-truncate-write, short enough to feel immediate.
pub const DEBOUNCE: Duration = Duration::from_millis(120);

/// Paths the desktop must never treat as project source.
///
/// `outputs/` is what rendering produces, and everything under `.arcavex/` is engine-managed
/// state — the proposal queue, caches, the history records, the remembered revision manifests,
/// and the staging directory a transaction writes through. Reacting to any of them would make
/// the desktop render its own output forever.
///
/// Only `pending` and `cache` used to be ignored, so one ordinary edit — which writes a history
/// record, a manifest, and a staging tree — surfaced in the activity log as "an external editor
/// or AI client changed 86 files". The application reporting its own edit as someone else's is
/// worse than saying nothing: the whole point of that log is to show what you did not do.
const IGNORED_PREFIXES: [&str; 2] = ["outputs", ".arcavex"];
const IGNORED_SUFFIXES: [&str; 3] = [".tmp", ".swp", "~"];

/// Version control is the user's business, not the desktop's.
const IGNORED_DIRECTORIES: [&str; 1] = [".git"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ChangeActor {
    /// Every path in the set was a write this desktop had already announced.
    Desktop,
    /// At least one path was written by an AI client, the CLI, or a human editor.
    External,
}

/// One debounced burst of source changes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChangeSet {
    /// Project-relative POSIX paths, sorted, with duplicates collapsed.
    pub paths: Vec<String>,
    pub actor: ChangeActor,
}

/// Normalize an absolute path to a project-relative POSIX path, or `None` when it is outside.
#[must_use]
pub fn relative_posix(root: &Path, path: &Path) -> Option<String> {
    let relative = path.strip_prefix(root).ok()?;
    let mut parts = Vec::new();
    for component in relative.components() {
        match component {
            Component::Normal(part) => parts.push(part.to_string_lossy().into_owned()),
            Component::CurDir => {}
            // A path escaping the project root is never project source.
            Component::ParentDir => return None,
            _ => {}
        }
    }
    (!parts.is_empty()).then(|| parts.join("/"))
}

/// Whether a project-relative path is engine output, queue state, or editor scratch.
#[must_use]
pub fn is_ignored(relative: &str) -> bool {
    IGNORED_PREFIXES
        .iter()
        .chain(IGNORED_DIRECTORIES.iter())
        .any(|prefix| relative == *prefix || relative.starts_with(&format!("{prefix}/")))
        || IGNORED_SUFFIXES
            .iter()
            .any(|suffix| relative.ends_with(suffix))
}

/// Collects raw events and releases one change set once the burst goes quiet.
#[derive(Debug)]
pub struct ChangeCoalescer {
    debounce: Duration,
    pending: BTreeSet<String>,
    last_seen: Option<Instant>,
    /// Writes this desktop announced, so the events they cause are not reported as external.
    announced: HashSet<String>,
    saw_unannounced: bool,
}

impl ChangeCoalescer {
    #[must_use]
    pub fn new(debounce: Duration) -> Self {
        Self {
            debounce,
            pending: BTreeSet::new(),
            last_seen: None,
            announced: HashSet::new(),
            saw_unannounced: false,
        }
    }

    /// Announce a write the desktop is about to make, so its own event is deduplicated.
    pub fn announce(&mut self, relative: &str) {
        self.announced.insert(relative.to_owned());
    }

    /// Record one raw event. Ignored paths never start or extend a burst.
    pub fn observe(&mut self, relative: &str, at: Instant) {
        if is_ignored(relative) {
            return;
        }
        if !self.announced.remove(relative) {
            self.saw_unannounced = true;
        }
        self.pending.insert(relative.to_owned());
        self.last_seen = Some(at);
    }

    /// Whether a burst is still settling.
    #[must_use]
    pub fn is_settling(&self) -> bool {
        self.last_seen.is_some()
    }

    /// Release the burst once it has been quiet for the debounce window.
    pub fn poll(&mut self, now: Instant) -> Option<ChangeSet> {
        let last_seen = self.last_seen?;
        if now.duration_since(last_seen) < self.debounce {
            return None;
        }
        self.last_seen = None;
        let actor = if self.saw_unannounced {
            ChangeActor::External
        } else {
            ChangeActor::Desktop
        };
        self.saw_unannounced = false;
        let paths: Vec<String> = std::mem::take(&mut self.pending).into_iter().collect();
        (!paths.is_empty()).then_some(ChangeSet { paths, actor })
    }
}

/// The canonical project the desktop currently has open, and nothing else.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WatchedProject {
    pub root: PathBuf,
}

impl WatchedProject {
    /// Canonicalize once so every later comparison is against the same spelling.
    ///
    /// # Errors
    ///
    /// Returns an error when the directory does not exist or cannot be resolved.
    pub fn open(path: &Path) -> std::io::Result<Self> {
        Ok(Self {
            root: dunce::canonicalize(path)?,
        })
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Translate a raw event path into the relative form the coalescer works in.
    #[must_use]
    pub fn relative(&self, path: &Path) -> Option<String> {
        relative_posix(&self.root, path)
    }
}
