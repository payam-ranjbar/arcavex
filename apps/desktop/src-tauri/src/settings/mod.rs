//! Atomic, corruption-tolerant persistence for app-local preferences.

pub mod model;

use std::io;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

pub use model::{
    AutomationMode, DesktopSettings, ExtensionMode, LiveRenderMode, WorkspacePreferences,
    MAX_RECENT_PROJECTS, SETTINGS_VERSION,
};

/// Filename under the platform application-data directory.
pub const SETTINGS_FILENAME: &str = "settings.json";

/// The outcome of loading settings, including anything the user should be told about.
#[derive(Debug)]
pub struct LoadedSettings {
    pub store: SettingsStore,
    /// Present when an unreadable file was replaced by defaults.
    pub diagnostic: Option<String>,
}

/// Reads and writes one settings file, keeping the parsed value in memory.
#[derive(Debug)]
pub struct SettingsStore {
    path: PathBuf,
    current: Mutex<DesktopSettings>,
}

impl SettingsStore {
    /// Load settings, falling back to approved defaults when the file is missing or corrupt.
    ///
    /// A corrupt file is preserved beside the new one rather than deleted, so a hand-edited
    /// mistake can be recovered instead of silently discarded.
    #[must_use]
    pub fn load(directory: &Path) -> LoadedSettings {
        let path = directory.join(SETTINGS_FILENAME);
        let Ok(text) = std::fs::read_to_string(&path) else {
            return LoadedSettings {
                store: Self::with(path, DesktopSettings::default()),
                diagnostic: None,
            };
        };

        match serde_json::from_str::<DesktopSettings>(&text) {
            Ok(settings) => LoadedSettings {
                store: Self::with(path, settings),
                diagnostic: None,
            },
            Err(error) => {
                let quarantine = path.with_extension("invalid.json");
                let preserved = std::fs::write(&quarantine, &text).is_ok();
                let diagnostic = if preserved {
                    format!(
                        "Settings could not be read ({error}). Defaults are in use and the \
                         previous file was kept at {}.",
                        quarantine.display()
                    )
                } else {
                    format!("Settings could not be read ({error}). Defaults are in use.")
                };
                LoadedSettings {
                    store: Self::with(path, DesktopSettings::default()),
                    diagnostic: Some(diagnostic),
                }
            }
        }
    }

    fn with(path: PathBuf, settings: DesktopSettings) -> Self {
        Self {
            path,
            current: Mutex::new(settings),
        }
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn get(&self) -> DesktopSettings {
        self.current.lock().expect("settings").clone()
    }

    /// Apply a change and persist it atomically.
    ///
    /// # Errors
    ///
    /// Returns an error when the new file could not be written or moved into place. The in-memory
    /// value is only updated once the write succeeded, so memory and disk cannot disagree.
    pub fn update<F>(&self, change: F) -> io::Result<DesktopSettings>
    where
        F: FnOnce(&mut DesktopSettings),
    {
        let mut guard = self.current.lock().expect("settings");
        let mut candidate = guard.clone();
        change(&mut candidate);
        self.write_atomic(&candidate)?;
        *guard = candidate.clone();
        Ok(candidate)
    }

    /// Write through a temporary file and rename, so a crash never leaves a half-written file.
    fn write_atomic(&self, settings: &DesktopSettings) -> io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temporary = self.path.with_extension("json.tmp");
        let mut text = serde_json::to_string_pretty(settings)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        text.push('\n');
        std::fs::write(&temporary, text)?;
        // Windows rename fails onto an existing file, so the target is removed first.
        if self.path.exists() {
            std::fs::remove_file(&self.path)?;
        }
        std::fs::rename(&temporary, &self.path)
    }
}
