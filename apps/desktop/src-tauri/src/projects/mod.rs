//! Project synchronization: watch exactly the open project and report attributed changes.

pub mod watcher;

use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use tokio::sync::mpsc::UnboundedSender;

pub use watcher::{
    is_ignored, relative_posix, ChangeActor, ChangeCoalescer, ChangeSet, WatchedProject, DEBOUNCE,
};

/// How often the settling burst is checked; well under the debounce window.
const POLL_INTERVAL: Duration = Duration::from_millis(25);

/// Watches one canonical project directory and publishes debounced, attributed change sets.
///
/// Dropping this stops the watch, which is how closing a project stops its events.
pub struct ProjectWatcher {
    project: WatchedProject,
    coalescer: Arc<Mutex<ChangeCoalescer>>,
    _watcher: RecommendedWatcher,
}

impl ProjectWatcher {
    /// Begin watching `project`, publishing each debounced burst to `sink`.
    ///
    /// # Errors
    ///
    /// Returns an error when the platform watcher cannot be created or the path cannot be watched.
    pub fn start(
        project: WatchedProject,
        debounce: Duration,
        sink: UnboundedSender<ChangeSet>,
    ) -> notify::Result<Self> {
        let coalescer = Arc::new(Mutex::new(ChangeCoalescer::new(debounce)));

        let observing = Arc::clone(&coalescer);
        let root = project.root.clone();
        let mut watcher =
            notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
                let Ok(event) = event else { return };
                let now = Instant::now();
                let mut coalescer = observing.lock().expect("coalescer");
                for path in &event.paths {
                    if let Some(relative) = relative_posix(&root, path) {
                        coalescer.observe(&relative, now);
                    }
                }
            })?;
        watcher.watch(&project.root, RecursiveMode::Recursive)?;

        let releasing = Arc::clone(&coalescer);
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(POLL_INTERVAL).await;
                let released = releasing.lock().expect("coalescer").poll(Instant::now());
                if let Some(change) = released {
                    if sink.send(change).is_err() {
                        return;
                    }
                }
            }
        });

        Ok(Self {
            project,
            coalescer,
            _watcher: watcher,
        })
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.project.root
    }

    /// Announce a write the desktop is about to make so its own event is not called external.
    pub fn announce(&self, relative: &str) {
        self.coalescer.lock().expect("coalescer").announce(relative);
    }
}
