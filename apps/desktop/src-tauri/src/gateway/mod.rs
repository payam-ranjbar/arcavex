//! The typed surface the WebView may call. Nothing reaches the engine except through here.

pub mod session;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tauri::AppHandle;

use crate::engine::{
    CommandLauncher, EngineLauncher, EngineSpec, EngineState, EngineStatus, McpClient, Supervisor,
};
use crate::events::{publish, DesktopEventKind};
use crate::projects::{ChangeActor, ChangeSet, ProjectWatcher, WatchedProject, DEBOUNCE};
use crate::rendering::{RenderJob, RenderOutput, RenderStatus};
use crate::settings::{DesktopSettings, LiveRenderMode, SettingsStore};

use session::{
    png_dimensions, preview_to_display, render_url, summarize, ActivityEntry, ProjectTarget,
    Session, ACTIVITY_LIMIT,
};

/// Gateway state for the real application.
pub type DesktopState = GatewayState<CommandLauncher>;

/// Holds the supervised engine, the open project, and the preferences that outlive both.
pub struct GatewayState<L: EngineLauncher> {
    /// Absent when this build ships no artifact for the running platform.
    supervisor: Option<Arc<Supervisor<L>>>,
    unavailable: Option<String>,
    client: Mutex<Option<Arc<McpClient>>>,
    settings: SettingsStore,
    settings_diagnostic: Option<String>,
    open: Mutex<Option<Session>>,
    activity: Mutex<Vec<ActivityEntry>>,
    app: Mutex<Option<AppHandle>>,
    next_activity_id: AtomicU64,
}

impl<L: EngineLauncher> GatewayState<L> {
    #[must_use]
    pub fn new(launcher: L, spec: EngineSpec, settings_directory: &Path) -> Self {
        let loaded = SettingsStore::load(settings_directory);
        Self {
            supervisor: Some(Arc::new(Supervisor::new(launcher, spec))),
            unavailable: None,
            client: Mutex::new(None),
            settings: loaded.store,
            settings_diagnostic: loaded.diagnostic,
            open: Mutex::new(None),
            activity: Mutex::new(Vec::new()),
            app: Mutex::new(None),
            next_activity_id: AtomicU64::new(1),
        }
    }

    /// Open the workbench in diagnostic mode when there is no engine to supervise at all.
    #[must_use]
    pub fn unavailable(reason: String, settings_directory: &Path) -> Self {
        let loaded = SettingsStore::load(settings_directory);
        Self {
            supervisor: None,
            unavailable: Some(reason),
            client: Mutex::new(None),
            settings: loaded.store,
            settings_diagnostic: loaded.diagnostic,
            open: Mutex::new(None),
            activity: Mutex::new(Vec::new()),
            app: Mutex::new(None),
            next_activity_id: AtomicU64::new(1),
        }
    }

    /// Bind the window that events are published to. Called once during setup.
    pub fn attach(&self, app: AppHandle) {
        *self.app.lock().expect("app handle") = Some(app);
    }

    fn emit(&self, kind: DesktopEventKind) {
        if let Some(app) = self.app.lock().expect("app handle").as_ref() {
            publish(app, kind);
        }
    }

    #[must_use]
    pub fn settings(&self) -> DesktopSettings {
        self.settings.get()
    }

    /// Anything the user should be told about the settings file itself.
    #[must_use]
    pub fn settings_diagnostic(&self) -> Option<String> {
        self.settings_diagnostic.clone()
    }

    /// Apply a settings change, persist it, and tell the workbench.
    ///
    /// # Errors
    ///
    /// Returns the write failure when the new settings could not be persisted.
    pub fn update_settings<F>(&self, change: F) -> Result<DesktopSettings, String>
    where
        F: FnOnce(&mut DesktopSettings),
    {
        let settings = self.settings.update(change).map_err(|e| e.to_string())?;
        self.emit(DesktopEventKind::Settings {
            settings: serde_json::to_value(&settings).unwrap_or(Value::Null),
        });
        Ok(settings)
    }

    #[must_use]
    pub fn activity(&self) -> Vec<ActivityEntry> {
        self.activity.lock().expect("activity").clone()
    }

    fn record_activity(&self, actor: ChangeActor, summary: String, snapshot: Option<&Value>) {
        let read = |field: &str| {
            snapshot
                .and_then(|value| value.get(field))
                .and_then(Value::as_str)
                .map(str::to_owned)
        };
        let entry = ActivityEntry {
            id: format!("a{}", self.next_activity_id.fetch_add(1, Ordering::Relaxed)),
            at: epoch_millis(),
            actor,
            summary,
            project_revision: read("project_revision"),
            render_revision: read("render_revision"),
            diagnostics: Vec::new(),
        };
        let mut log = self.activity.lock().expect("activity");
        log.push(entry.clone());
        if log.len() > ACTIVITY_LIMIT {
            let excess = log.len() - ACTIVITY_LIMIT;
            log.drain(..excess);
        }
        drop(log);
        self.emit(DesktopEventKind::Activity {
            entry: serde_json::to_value(&entry).unwrap_or(Value::Null),
        });
    }

    #[must_use]
    pub fn engine_state(&self) -> EngineState {
        match &self.supervisor {
            Some(supervisor) => supervisor.state(),
            None => EngineState {
                status: EngineStatus::Failed,
                handshake: None,
                artifact_path: None,
                restart_count: 0,
                message: self.unavailable.clone(),
            },
        }
    }

    /// The retained tail of engine stderr, for the diagnostics panel.
    #[must_use]
    pub fn engine_stderr(&self) -> Vec<String> {
        self.supervisor
            .as_ref()
            .map(|supervisor| supervisor.stderr_tail())
            .unwrap_or_default()
    }

    fn supervisor(&self) -> Result<&Arc<Supervisor<L>>, String> {
        self.supervisor.as_ref().ok_or_else(|| {
            self.unavailable
                .clone()
                .unwrap_or_else(|| "no engine is available".to_owned())
        })
    }

    /// Return the connected client, starting the engine on first use.
    ///
    /// # Errors
    ///
    /// Returns the startup failure text when no trusted engine could be reached.
    pub async fn client(&self) -> Result<Arc<McpClient>, String> {
        if let Some(client) = self.client.lock().expect("engine client").clone() {
            return Ok(client);
        }
        let client = self
            .supervisor()?
            .start()
            .await
            .map_err(|error| error.to_string())?;
        *self.client.lock().expect("engine client") = Some(Arc::clone(&client));
        Ok(client)
    }

    /// Drop the current engine and start a fresh one.
    ///
    /// # Errors
    ///
    /// Returns the startup failure text when the replacement engine cannot be trusted.
    pub async fn restart(&self) -> Result<EngineState, String> {
        let supervisor = Arc::clone(self.supervisor()?);
        *self.client.lock().expect("engine client") = None;
        supervisor.shutdown();
        let client = supervisor
            .start()
            .await
            .map_err(|error| error.to_string())?;
        *self.client.lock().expect("engine client") = Some(client);
        Ok(supervisor.state())
    }

    /// Call one MCP tool and hand back its structured report unchanged.
    ///
    /// The gateway parses and presents; it never reimplements engine behaviour.
    ///
    /// # Errors
    ///
    /// Returns the engine's failure text when the call cannot be completed.
    pub async fn call_tool(&self, name: &str, arguments: Value) -> Result<Value, String> {
        let client = self.client().await?;
        let response = client
            .call("tools/call", json!({"name": name, "arguments": arguments}))
            .await
            .map_err(|error| error.to_string())?;
        Ok(response
            .get("structuredContent")
            .cloned()
            .unwrap_or(response))
    }

    /// Open a project in place: snapshot it, watch it, remember it, and render it.
    ///
    /// Nothing is imported or copied. The engine reads the directory the user chose.
    ///
    /// # Errors
    ///
    /// Returns the reason when the directory cannot be resolved or the engine cannot read it.
    pub async fn open_project(self: &Arc<Self>, path: &str) -> Result<Value, String> {
        let project = WatchedProject::open(Path::new(path)).map_err(|e| e.to_string())?;
        let root = project.root().to_path_buf();
        let canonical = root.display().to_string();

        let snapshot = self
            .call_tool("project_snapshot", json!({ "project": canonical }))
            .await?;

        let (sink, mut changes) = tokio::sync::mpsc::unbounded_channel();
        let watcher =
            ProjectWatcher::start(project, DEBOUNCE, sink).map_err(|error| error.to_string())?;

        let target = Session::default_target(&snapshot);
        *self.open.lock().expect("open project") = Some(Session {
            root,
            snapshot: snapshot.clone(),
            target,
            scheduler: crate::rendering::RenderScheduler::new(),
            watcher,
        });

        self.update_settings(|settings| settings.remember_project(&canonical))?;
        self.emit(DesktopEventKind::Project {
            snapshot: snapshot.clone(),
        });
        self.record_activity(
            ChangeActor::Desktop,
            format!("Opened {canonical}"),
            Some(&snapshot),
        );

        let consumer = Arc::clone(self);
        tokio::spawn(async move {
            while let Some(change) = changes.recv().await {
                consumer.apply_change(change).await;
            }
        });

        self.request_render();
        Ok(snapshot)
    }

    /// Stop watching and forget the open project. The project itself is untouched.
    pub fn close_project(&self) {
        *self.open.lock().expect("open project") = None;
    }

    /// The snapshot of the open project as the engine last reported it.
    ///
    /// # Errors
    ///
    /// Returns an error when no project is open.
    pub fn project_snapshot_value(&self) -> Result<Value, String> {
        self.open
            .lock()
            .expect("open project")
            .as_ref()
            .map(|session| session.snapshot.clone())
            .ok_or_else(|| "no project is open".to_owned())
    }

    #[must_use]
    pub fn active_target(&self) -> ProjectTarget {
        self.open
            .lock()
            .expect("open project")
            .as_ref()
            .map(|session| session.target.clone())
            .unwrap_or_default()
    }

    /// Switch the target being viewed. The picture on screen becomes stale until it re-renders.
    ///
    /// # Errors
    ///
    /// Returns an error when no project is open.
    pub fn set_active_target(
        self: &Arc<Self>,
        target: ProjectTarget,
    ) -> Result<ProjectTarget, String> {
        {
            let mut open = self.open.lock().expect("open project");
            let session = open
                .as_mut()
                .ok_or_else(|| "no project is open".to_owned())?;
            session.target = target.clone();
            session.scheduler.target_changed();
        }
        self.publish_render_status();
        self.request_render();
        Ok(target)
    }

    #[must_use]
    pub fn render_status(&self) -> RenderStatus {
        self.open
            .lock()
            .expect("open project")
            .as_ref()
            .map(|session| session.scheduler.status())
            .unwrap_or_else(|| crate::rendering::RenderScheduler::new().status())
    }

    /// Ask for a picture of the current target, starting a job only if none is running.
    pub fn request_render(self: &Arc<Self>) {
        let job = {
            let mut open = self.open.lock().expect("open project");
            let Some(session) = open.as_mut() else { return };
            let key = session.render_key();
            session.scheduler.request(key)
        };
        self.publish_render_status();
        if let Some(job) = job {
            self.run_render(job);
        }
    }

    fn run_render(self: &Arc<Self>, job: RenderJob) {
        let state = Arc::clone(self);
        tokio::spawn(async move {
            let outcome = state.render_once(&job).await;
            let (_, next) = {
                let mut open = state.open.lock().expect("open project");
                let Some(session) = open.as_mut() else { return };
                session.scheduler.complete(&job, outcome)
            };
            state.publish_render_status();
            if let Some(next) = next {
                state.run_render(next);
            }
        });
    }

    /// Run one render through the engine and turn its report into a displayable picture.
    async fn render_once(&self, job: &RenderJob) -> Result<RenderOutput, Vec<Value>> {
        let (root, canonical) = {
            let open = self.open.lock().expect("open project");
            let Some(session) = open.as_ref() else {
                return Err(vec![json!({"message": "no project is open"})]);
            };
            (session.root.clone(), session.root.display().to_string())
        };

        let mut arguments = json!({ "project": canonical });
        if let Some(format) = &job.key.format {
            arguments["formats"] = json!([format]);
        }
        if let Some(locale) = &job.key.locale {
            arguments["locales"] = json!([locale]);
        }

        let report = self
            .call_tool("project_preview", arguments)
            .await
            .map_err(|error| vec![json!({ "message": error })])?;

        let preview = preview_to_display(&report)?.clone();
        let output_path = preview
            .get("output_path")
            .and_then(Value::as_str)
            .expect("preview_to_display only returns a target with an output path");
        let image_url = render_url(&root, self.engine_cache_root().as_deref(), output_path)
            .ok_or_else(|| {
                vec![json!({
                    "message": format!(
                        "render wrote outside the project and the engine cache: {output_path}"
                    )
                })]
            })?;

        let (width_px, height_px) = std::fs::read(output_path)
            .ok()
            .and_then(|bytes| png_dimensions(&bytes))
            .unwrap_or((0, 0));

        Ok(RenderOutput {
            key: job.key.clone(),
            image_url,
            width_px,
            height_px,
            content_sha256: preview
                .get("content_sha256")
                .and_then(Value::as_str)
                .map(str::to_owned),
            compile_ms: preview
                .get("compile_ms")
                .and_then(Value::as_f64)
                .map(round_ms),
            render_ms: preview
                .get("render_ms")
                .and_then(Value::as_f64)
                .map(round_ms),
        })
    }

    /// React to one debounced burst of source changes.
    async fn apply_change(self: &Arc<Self>, change: ChangeSet) {
        let Some(canonical) = self
            .open
            .lock()
            .expect("open project")
            .as_ref()
            .map(|session| session.root.display().to_string())
        else {
            return;
        };

        let Ok(snapshot) = self
            .call_tool("project_snapshot", json!({ "project": canonical }))
            .await
        else {
            return;
        };

        {
            let mut open = self.open.lock().expect("open project");
            let Some(session) = open.as_mut() else { return };
            session.snapshot = snapshot.clone();
        }
        self.emit(DesktopEventKind::Project {
            snapshot: snapshot.clone(),
        });
        self.record_activity(change.actor, summarize(&change), Some(&snapshot));

        if self.settings.get().live_render == LiveRenderMode::EveryChange {
            self.request_render();
        } else {
            self.publish_render_status();
        }
    }

    /// The canonical path of the open project, as the engine expects to receive it.
    ///
    /// # Errors
    ///
    /// Returns an error when no project is open.
    pub fn open_project_path(&self) -> Result<String, String> {
        self.open
            .lock()
            .expect("open project")
            .as_ref()
            .map(|session| session.root.display().to_string())
            .ok_or_else(|| "no project is open".to_owned())
    }

    /// The engine's cache directory, as the running engine reported it at handshake.
    ///
    /// Live preview renders land under this directory rather than inside the project, so the
    /// scheme handler must be able to serve from it. Reading it from the handshake rather than
    /// recomputing it keeps the desktop correct when the engine's home is not the default.
    #[must_use]
    pub fn engine_cache_root(&self) -> Option<PathBuf> {
        self.engine_state()
            .handshake
            .as_ref()
            .and_then(|report| report.get("paths"))
            .and_then(|paths| paths.get("cache"))
            .and_then(Value::as_str)
            .map(PathBuf::from)
    }

    /// After one of our own semantic edits: claim its writes and refresh the picture.
    ///
    /// The transaction report names every path it changed; announcing them keeps the watcher
    /// from labelling the engine's write an external edit, and an accepted render-affecting
    /// change re-renders the active target exactly like any other change.
    pub fn after_own_edit(self: &Arc<Self>, report: &Value) {
        let changed: Vec<String> = report
            .get("changed")
            .and_then(Value::as_array)
            .map(|entries| {
                entries
                    .iter()
                    .filter_map(|entry| entry.get("path").and_then(Value::as_str))
                    .map(str::to_owned)
                    .collect()
            })
            .unwrap_or_default();
        for path in &changed {
            self.announce_own_write(path);
        }
        if report.get("ok").and_then(Value::as_bool) == Some(true) && !changed.is_empty() {
            self.refresh_open_snapshot();
            self.request_render();
        }
    }

    /// Re-read the open project's snapshot so revisions the UI sees match the engine's.
    fn refresh_open_snapshot(self: &Arc<Self>) {
        let state = Arc::clone(self);
        tokio::spawn(async move {
            let Ok(project) = state.open_project_path() else { return };
            let Ok(snapshot) = state
                .call_tool("project_snapshot", json!({ "project": project }))
                .await
            else {
                return;
            };
            if let Some(session) = state.open.lock().expect("open project").as_mut() {
                session.snapshot = snapshot.clone();
            }
            state.emit(DesktopEventKind::Project { snapshot });
        });
    }

    /// Tell the watcher a write is ours, so the event it causes is not called an external edit.
    pub fn announce_own_write(&self, relative: &str) {
        if let Some(session) = self.open.lock().expect("open project").as_ref() {
            session.watcher.announce(relative);
        }
    }

    /// Merge a partial settings object, rejecting anything that does not fit the schema.
    ///
    /// # Errors
    ///
    /// Returns an error when the patch is not an object, produces invalid settings, or cannot
    /// be persisted.
    pub fn apply_settings_patch(&self, patch: Value) -> Result<DesktopSettings, String> {
        let Value::Object(fields) = patch else {
            return Err("a settings patch must be an object".to_owned());
        };
        let mut merged =
            serde_json::to_value(self.settings.get()).map_err(|error| error.to_string())?;
        let Value::Object(current) = &mut merged else {
            return Err("settings did not serialize as an object".to_owned());
        };
        for (key, value) in fields {
            current.insert(key, value);
        }
        let candidate: DesktopSettings =
            serde_json::from_value(merged).map_err(|error| error.to_string())?;
        self.update_settings(|settings| *settings = candidate)
    }

    fn publish_render_status(&self) {
        let status = self.render_status();
        self.emit(DesktopEventKind::Render {
            render: serde_json::to_value(&status).unwrap_or(Value::Null),
        });
    }

    /// End the engine process. Called when the window closes.
    pub fn shutdown(&self) {
        *self.client.lock().expect("engine client") = None;
        if let Some(supervisor) = &self.supervisor {
            supervisor.shutdown();
        }
    }
}

/// Milliseconds since the Unix epoch, the unambiguous timestamp the workbench formats.
fn epoch_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|since| u64::try_from(since.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or_default()
}

/// Engine durations are floats; the workbench shows whole milliseconds.
fn round_ms(value: f64) -> u64 {
    value.max(0.0).round() as u64
}

/// State shared with background watcher and render tasks.
pub type SharedState = Arc<DesktopState>;

#[tauri::command]
pub fn engine_state(state: tauri::State<'_, SharedState>) -> EngineState {
    state.engine_state()
}

#[tauri::command]
pub fn engine_stderr(state: tauri::State<'_, SharedState>) -> Vec<String> {
    state.engine_stderr()
}

#[tauri::command]
pub async fn restart_engine(state: tauri::State<'_, SharedState>) -> Result<EngineState, String> {
    let restarted = state.restart().await?;
    {
        let mut open = state.open.lock().expect("open project");
        if let Some(session) = open.as_mut() {
            session.scheduler.engine_restarted();
        }
    }
    state.publish_render_status();
    let resumed = {
        let mut open = state.open.lock().expect("open project");
        open.as_mut().and_then(|session| session.scheduler.resume())
    };
    if let Some(job) = resumed {
        state.inner().run_render(job);
    }
    Ok(restarted)
}

/// Ask the user for a project directory. `None` means they cancelled.
#[tauri::command]
pub async fn choose_project_directory(app: AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;

    let (sender, receiver) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_title("Open an Arcavex project")
        .pick_folder(move |chosen| {
            let _ = sender.send(chosen);
        });
    receiver
        .await
        .ok()
        .flatten()
        .map(|folder| folder.to_string())
}

#[tauri::command]
pub async fn open_project(
    state: tauri::State<'_, SharedState>,
    path: String,
) -> Result<Value, String> {
    state.inner().open_project(&path).await
}

#[tauri::command]
pub fn close_project(state: tauri::State<'_, SharedState>) {
    state.close_project();
}

#[tauri::command]
pub fn project_snapshot(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    state.project_snapshot_value()
}

#[tauri::command]
pub async fn validate_project(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool("project_validate", json!({ "project": project }))
        .await
}

#[tauri::command]
pub fn active_target(state: tauri::State<'_, SharedState>) -> ProjectTarget {
    state.active_target()
}

#[tauri::command]
pub fn set_active_target(
    state: tauri::State<'_, SharedState>,
    target: ProjectTarget,
) -> Result<ProjectTarget, String> {
    state.inner().set_active_target(target)
}

#[tauri::command]
pub fn render_status(state: tauri::State<'_, SharedState>) -> RenderStatus {
    state.render_status()
}

#[tauri::command]
pub fn request_render(state: tauri::State<'_, SharedState>) -> RenderStatus {
    state.inner().request_render();
    state.render_status()
}

#[tauri::command]
pub async fn layer_tree(
    state: tauri::State<'_, SharedState>,
    mode: String,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    let target = state.active_target();
    state
        .call_tool(
            "layer_tree",
            json!({
                "project": project,
                "mode": mode,
                "format": target.format,
                "locale": target.locale,
            }),
        )
        .await
}

#[tauri::command]
pub async fn hit_test(
    state: tauri::State<'_, SharedState>,
    x_pt: f64,
    y_pt: f64,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    let target = state.active_target();
    state
        .call_tool(
            "hit_test",
            json!({
                "project": project,
                "x_pt": x_pt,
                "y_pt": y_pt,
                "format": target.format,
                "locale": target.locale,
            }),
        )
        .await
}

#[tauri::command]
pub async fn ui_metadata(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool("project_ui_metadata", json!({ "project": project }))
        .await
}

#[tauri::command]
pub async fn set_ui_metadata(
    state: tauri::State<'_, SharedState>,
    metadata: Value,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state.announce_own_write("project.ui.yaml");
    state
        .call_tool(
            "project_ui_metadata_set",
            json!({ "project": project, "metadata": metadata }),
        )
        .await
}

#[tauri::command]
pub async fn editor_apply(
    state: tauri::State<'_, SharedState>,
    transaction: Value,
) -> Result<Value, String> {
    let report = state
        .call_tool("editor_apply", json!({ "transaction": transaction }))
        .await?;
    state.after_own_edit(&report);
    Ok(report)
}

#[tauri::command]
pub async fn editor_apply_authorized(
    state: tauri::State<'_, SharedState>,
    command_id: String,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    let report = state
        .call_tool(
            "editor_apply_authorized",
            json!({ "project": project, "command_id": command_id }),
        )
        .await?;
    state.after_own_edit(&report);
    Ok(report)
}

#[tauri::command]
pub async fn editor_undo(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    let report = state
        .call_tool("editor_undo", json!({ "project": project }))
        .await?;
    state.after_own_edit(&report);
    Ok(report)
}

#[tauri::command]
pub async fn editor_redo(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    let report = state
        .call_tool("editor_redo", json!({ "project": project }))
        .await?;
    state.after_own_edit(&report);
    Ok(report)
}

#[tauri::command]
pub async fn editor_history(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool("editor_history", json!({ "project": project }))
        .await
}

#[tauri::command]
pub async fn project_policy(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool("project_policy", json!({ "project": project }))
        .await
}

#[tauri::command]
pub async fn set_project_policy(
    state: tauri::State<'_, SharedState>,
    policy: Value,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state.announce_own_write("project.yaml");
    state
        .call_tool(
            "project_policy_set",
            json!({ "project": project, "policy": policy }),
        )
        .await
}

#[tauri::command]
pub async fn list_proposals(state: tauri::State<'_, SharedState>) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool("project_proposal_list", json!({ "project": project }))
        .await
}

#[tauri::command]
pub async fn approve_proposal(
    state: tauri::State<'_, SharedState>,
    command_id: String,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool(
            "project_proposal_approve",
            json!({ "project": project, "command_id": command_id }),
        )
        .await
}

#[tauri::command]
pub async fn reject_proposal(
    state: tauri::State<'_, SharedState>,
    command_id: String,
    reason: String,
) -> Result<Value, String> {
    let project = state.open_project_path()?;
    state
        .call_tool(
            "project_proposal_reject",
            json!({ "project": project, "command_id": command_id, "reason": reason }),
        )
        .await
}

#[tauri::command]
pub fn activity(state: tauri::State<'_, SharedState>) -> Vec<ActivityEntry> {
    state.activity()
}

#[tauri::command]
pub fn settings(state: tauri::State<'_, SharedState>) -> DesktopSettings {
    state.settings()
}

#[tauri::command]
pub fn update_settings(
    state: tauri::State<'_, SharedState>,
    patch: Value,
) -> Result<DesktopSettings, String> {
    state.apply_settings_patch(patch)
}
