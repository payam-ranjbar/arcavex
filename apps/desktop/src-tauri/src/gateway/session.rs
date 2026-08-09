//! The open project: its snapshot, its watcher, its render queue, and its activity log.
//!
//! Opening a project never imports or copies it. The desktop holds a pointer, a read-only
//! snapshot, and a watch on the canonical directory the user chose.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::projects::{ChangeActor, ChangeSet, ProjectWatcher};
use crate::rendering::{RenderKey, RenderScheduler};

/// One format-and-locale combination the workbench is currently looking at.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectTarget {
    pub format: Option<String>,
    pub locale: Option<String>,
}

/// Who did something, and what it did to the project.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActivityEntry {
    pub id: String,
    /// Milliseconds since the Unix epoch; the workbench decides how to display it.
    pub at: u64,
    pub actor: ChangeActor,
    pub summary: String,
    pub project_revision: Option<String>,
    pub render_revision: Option<String>,
    pub diagnostics: Vec<Value>,
}

/// How many activity rows are kept in memory for the bottom panel.
pub const ACTIVITY_LIMIT: usize = 500;

/// Everything that belongs to the project currently open.
pub struct Session {
    pub root: PathBuf,
    pub snapshot: Value,
    pub target: ProjectTarget,
    pub scheduler: RenderScheduler,
    pub watcher: ProjectWatcher,
}

impl Session {
    /// The revision that decides whether a rendered picture is still valid.
    #[must_use]
    pub fn render_revision(&self) -> String {
        self.snapshot
            .get("render_revision")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned()
    }

    #[must_use]
    pub fn project_revision(&self) -> Option<String> {
        self.snapshot
            .get("project_revision")
            .and_then(Value::as_str)
            .map(str::to_owned)
    }

    /// The key identifying the picture the workbench is currently asking for.
    #[must_use]
    pub fn render_key(&self) -> RenderKey {
        RenderKey {
            render_revision: self.render_revision(),
            format: self.target.format.clone(),
            locale: self.target.locale.clone(),
            options: std::collections::BTreeMap::new(),
        }
    }

    /// The first declared target, used when a project is opened without a choice.
    #[must_use]
    pub fn default_target(snapshot: &Value) -> ProjectTarget {
        let default = snapshot.get("default_target");
        let read = |field: &str| {
            default
                .and_then(|target| target.get(field))
                .and_then(Value::as_str)
                .map(str::to_owned)
        };
        ProjectTarget {
            format: read("format"),
            locale: read("locale"),
        }
    }
}

/// Describe a change set the way the activity panel should read it.
#[must_use]
pub fn summarize(change: &ChangeSet) -> String {
    let who = match change.actor {
        ChangeActor::Desktop => "Arcavex Desktop",
        ChangeActor::External => "An external editor or AI client",
    };
    match change.paths.as_slice() {
        [only] => format!("{who} changed {only}"),
        paths => format!("{who} changed {} files", paths.len()),
    }
}

/// Resolve a rendered output path to a URL the WebView may load.
///
/// Only paths inside the open project are addressable, so a report naming a file elsewhere
/// cannot be turned into a URL the window will fetch. Windows serves custom schemes over a
/// localhost host name, so the two platforms spell the same resource differently.
#[must_use]
pub fn render_url(root: &Path, output_path: &str) -> Option<String> {
    let absolute = PathBuf::from(output_path);
    let relative = crate::projects::relative_posix(root, &absolute)?;
    #[cfg(windows)]
    {
        Some(format!("http://arcavex.localhost/{relative}"))
    }
    #[cfg(not(windows))]
    {
        Some(format!("arcavex://localhost/{relative}"))
    }
}

/// Read a PNG's pixel dimensions from its header, without decoding the image.
#[must_use]
pub fn png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    const SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
    if bytes.len() < 24 || bytes[..8] != SIGNATURE {
        return None;
    }
    let width = u32::from_be_bytes(bytes[16..20].try_into().ok()?);
    let height = u32::from_be_bytes(bytes[20..24].try_into().ok()?);
    Some((width, height))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn reads_the_default_target_a_project_declares() {
        let snapshot = json!({"default_target": {"format": "poster-a3", "locale": "fa-IR"}});

        let target = Session::default_target(&snapshot);

        assert_eq!(target.format.as_deref(), Some("poster-a3"));
        assert_eq!(target.locale.as_deref(), Some("fa-IR"));
    }

    #[test]
    fn a_project_without_a_default_target_selects_nothing() {
        assert_eq!(
            Session::default_target(&json!({"ok": true})),
            ProjectTarget::default()
        );
    }

    #[test]
    fn names_the_actor_and_the_file_in_an_activity_summary() {
        let one = summarize(&ChangeSet {
            paths: vec!["data.yaml".to_owned()],
            actor: ChangeActor::External,
        });
        let many = summarize(&ChangeSet {
            paths: vec!["a.yaml".to_owned(), "b.yaml".to_owned()],
            actor: ChangeActor::Desktop,
        });

        assert_eq!(one, "An external editor or AI client changed data.yaml");
        assert_eq!(many, "Arcavex Desktop changed 2 files");
    }

    #[test]
    fn refuses_to_address_a_render_written_outside_the_open_project() {
        let root = Path::new("/workspace/poster");

        let inside = render_url(root, "/workspace/poster/outputs/a3.png").expect("addressable");
        assert!(inside.ends_with("/outputs/a3.png"), "{inside}");
        assert_eq!(render_url(root, "/etc/shadow"), None);
    }

    #[test]
    fn reads_dimensions_from_a_png_header_and_rejects_anything_else() {
        let mut png = vec![0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];
        png.extend_from_slice(&[0, 0, 0, 13]);
        png.extend_from_slice(b"IHDR");
        png.extend_from_slice(&1684_u32.to_be_bytes());
        png.extend_from_slice(&2382_u32.to_be_bytes());

        assert_eq!(png_dimensions(&png), Some((1684, 2382)));
        assert_eq!(png_dimensions(b"%PDF-1.7"), None);
    }
}
