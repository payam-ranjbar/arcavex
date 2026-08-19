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

/// The two directories a rendered file may legitimately come from.
///
/// Everything else is unaddressable, which is what lets the window load pictures without the
/// application holding any filesystem permission at all.
pub const PROJECT_SPACE: &str = "project";
pub const PREVIEW_SPACE: &str = "preview";

/// Resolve a rendered output path to a URL the WebView may load.
///
/// A project render lands inside the open project, but `project_preview` — the call behind live
/// preview — writes into the engine's own cache, outside any project. Both are addressable and
/// nothing else is, so the URL names which space it came from and the scheme handler resolves it
/// against that root alone. Windows serves custom schemes over a localhost host name, so the two
/// platforms spell the same resource differently.
#[must_use]
pub fn render_url(root: &Path, engine_cache: Option<&Path>, output_path: &str) -> Option<String> {
    let absolute = PathBuf::from(output_path);
    let (space, relative) = crate::projects::relative_posix(root, &absolute)
        .map(|relative| (PROJECT_SPACE, relative))
        .or_else(|| {
            engine_cache
                .and_then(|cache| crate::projects::relative_posix(cache, &absolute))
                .map(|relative| (PREVIEW_SPACE, relative))
        })?;
    #[cfg(windows)]
    {
        Some(format!("http://arcavex.localhost/{space}/{relative}"))
    }
    #[cfg(not(windows))]
    {
        Some(format!("arcavex://localhost/{space}/{relative}"))
    }
}

/// Choose the preview to display from an engine report, or the diagnostics explaining why there
/// is none.
///
/// A failed target carries its own diagnostics — the missing font, the overflowing text, the line
/// of the template at fault — while the report-level list stays empty. Reading only the outer list
/// turns an engine that said exactly what was wrong into a workbench that says "render failed" and
/// nothing else, which is the opposite of what the diagnostics panel exists for.
///
/// # Errors
///
/// Returns every diagnostic the report offers when no target produced an image, and never an empty
/// list: a failure the user cannot read about is worse than a blunt one.
pub fn preview_to_display(report: &Value) -> Result<&Value, Vec<Value>> {
    let previews = report
        .get("previews")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default();

    if let Some(rendered) = previews
        .iter()
        .find(|preview| preview.get("output_path").and_then(Value::as_str).is_some())
    {
        return Ok(rendered);
    }

    let mut diagnostics: Vec<Value> = previews
        .iter()
        .filter_map(|preview| preview.get("diagnostics").and_then(Value::as_array))
        .flat_map(|entries| entries.iter().cloned())
        .collect();
    if let Some(outer) = report.get("diagnostics").and_then(Value::as_array) {
        diagnostics.extend(outer.iter().cloned());
    }
    if diagnostics.is_empty() {
        diagnostics.push(serde_json::json!({
            "message": "The engine produced no preview for this target and gave no reason.",
        }));
    }
    Err(diagnostics)
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
    fn addresses_a_render_written_inside_the_open_project() {
        let root = Path::new("/workspace/poster");

        let inside =
            render_url(root, None, "/workspace/poster/outputs/a3.png").expect("addressable");
        assert!(inside.ends_with("/project/outputs/a3.png"), "{inside}");
    }

    #[test]
    fn addresses_a_preview_written_into_the_engine_cache() {
        // Live preview goes through project_preview, which writes into the engine's own cache
        // rather than the project. Refusing it left the canvas permanently empty.
        let root = Path::new("/workspace/poster");
        let cache = Path::new("/home/user/.arcavex/cache");

        let preview = render_url(
            root,
            Some(cache),
            "/home/user/.arcavex/cache/preview/a1.png",
        )
        .expect("addressable");
        assert!(preview.ends_with("/preview/preview/a1.png"), "{preview}");
    }

    #[test]
    fn refuses_a_render_written_outside_both_roots() {
        let root = Path::new("/workspace/poster");
        let cache = Path::new("/home/user/.arcavex/cache");

        assert_eq!(render_url(root, Some(cache), "/etc/shadow"), None);
        assert_eq!(
            render_url(root, None, "/home/user/.arcavex/cache/preview/a1.png"),
            None
        );
    }

    #[test]
    fn displays_the_target_that_produced_an_image() {
        let report = json!({
            "ok": true,
            "previews": [{"ok": true, "output_path": "/cache/preview/a1.png"}],
            "diagnostics": [],
        });

        let preview = preview_to_display(&report).expect("an image to show");

        assert_eq!(preview["output_path"], "/cache/preview/a1.png");
    }

    #[test]
    fn reports_the_diagnostics_the_failing_target_carried() {
        // The engine names the node, the font, and the line. Reading only the report-level list
        // left the workbench saying "render failed" with nothing a person could act on.
        let report = json!({
            "ok": false,
            "previews": [{
                "ok": false,
                "output_path": null,
                "diagnostics": [{
                    "code": "ARC-RND-010",
                    "severity": "error",
                    "message": "Node 'organization-line-1' requests font family 'Archivo Black', which is not in the bundled font database",
                }],
            }],
            "diagnostics": [],
        });

        let diagnostics = preview_to_display(&report).expect_err("no image");

        assert_eq!(diagnostics.len(), 1);
        assert_eq!(diagnostics[0]["code"], "ARC-RND-010");
    }

    #[test]
    fn falls_back_to_the_report_level_diagnostics_when_no_target_was_attempted() {
        let report = json!({
            "ok": false,
            "previews": [],
            "diagnostics": [{"code": "ARC-PRJ-002", "message": "the project declares no formats"}],
        });

        let diagnostics = preview_to_display(&report).expect_err("no image");

        assert_eq!(diagnostics[0]["code"], "ARC-PRJ-002");
    }

    #[test]
    fn never_fails_a_render_without_saying_anything() {
        let report = json!({"ok": true, "previews": [], "diagnostics": []});

        let diagnostics = preview_to_display(&report).expect_err("no image");

        assert!(!diagnostics.is_empty());
        assert!(diagnostics[0]["message"].as_str().is_some());
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
