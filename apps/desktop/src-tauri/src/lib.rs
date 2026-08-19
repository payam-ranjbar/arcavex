//! Arcavex Desktop core.
//!
//! The Rust side owns everything the WebView must not: the private MCP sidecar, the project
//! watcher, the render queue, and settings. The WebView reaches all of it through typed
//! commands and one versioned event envelope, never through a network origin.

#![forbid(unsafe_code)]

pub mod engine;
pub mod events;
pub mod gateway;
pub mod projects;
pub mod rendering;
pub mod selfcheck;
pub mod settings;

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use tauri::Manager;

use engine::{CommandLauncher, EngineLock, EngineSpec};
use gateway::{DesktopState, SharedState};

/// The event envelope version the WebView is compiled against. A frontend that understands a
/// different version drops the event rather than guessing at its shape.
pub const DESKTOP_EVENT_VERSION: u32 = 1;

/// Tauri channel every desktop event travels on.
pub const DESKTOP_EVENT_CHANNEL: &str = "arcavex:desktop-event";

/// The platform this build was compiled for, used to select the pinned artifact.
pub const TARGET_TRIPLE: &str = env!("TAURI_ENV_TARGET_TRIPLE");

/// Environment override pointing at a locally built engine, honoured in development builds.
pub const ENGINE_OVERRIDE_VARIABLE: &str = "ARCAVEX_DESKTOP_ENGINE";

/// The lock is a build-time pin, so it is compiled in rather than read at startup.
const ENGINE_LOCK_SOURCE: &str = include_str!("../binaries/engine-lock.json");

/// Long enough for a cold render, short enough that a hung engine still reports.
const CALL_TIMEOUT: Duration = Duration::from_secs(120);

/// Build the gateway state, or a diagnostic state explaining why no engine can be trusted.
#[must_use]
pub fn build_state(settings_directory: &Path) -> DesktopState {
    let lock = match EngineLock::parse(ENGINE_LOCK_SOURCE) {
        Ok(lock) => lock,
        Err(error) => {
            return DesktopState::unavailable(
                format!("The bundled engine lock manifest is unreadable: {error}"),
                settings_directory,
            )
        }
    };

    let override_path = std::env::var_os(ENGINE_OVERRIDE_VARIABLE).map(PathBuf::from);
    match EngineSpec::resolve(
        &lock,
        &binaries_directory(),
        TARGET_TRIPLE,
        override_path,
        CALL_TIMEOUT,
    ) {
        Some(spec) => DesktopState::new(CommandLauncher, spec, settings_directory),
        None => DesktopState::unavailable(
            format!(
                "This build pins engine {} but ships no artifact for {TARGET_TRIPLE}. Set \
                 {ENGINE_OVERRIDE_VARIABLE} to a locally built engine to continue.",
                lock.engine_version
            ),
            settings_directory,
        ),
    }
}

/// Where the pinned sidecar sits: beside the installed executable, or in the source tree.
fn binaries_directory() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|executable| executable.parent().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries"))
}

/// Serve one rendered file, and only from inside the project the user has open.
///
/// The WebView displays the raster the engine produced. Reading it through a scheme handler
/// scoped to the open project is why the application needs no filesystem permission at all.
fn serve_render(
    state: &SharedState,
    request: &tauri::http::Request<Vec<u8>>,
) -> tauri::http::Response<Vec<u8>> {
    let not_found = || {
        tauri::http::Response::builder()
            .status(404)
            .body(Vec::new())
            .expect("404 response")
    };

    // The first segment names which of the two addressable roots this file came from; the rest is
    // relative to that root. Anything else has no root to resolve against and is refused.
    let full = request.uri().path().trim_start_matches('/');
    let Some((space, relative)) = full.split_once('/') else {
        return not_found();
    };
    if relative.is_empty() || relative.contains("..") {
        return not_found();
    }

    let root = match space {
        gateway::session::PROJECT_SPACE => state.open_project_path().ok().map(PathBuf::from),
        gateway::session::PREVIEW_SPACE => state.engine_cache_root(),
        _ => None,
    };
    let Some(root) = root else {
        return not_found();
    };

    let path = root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
    // Re-resolve rather than trust the URL: a symlink must not escape the root it was served from.
    let Ok(resolved) = dunce::canonicalize(&path) else {
        return not_found();
    };
    if !resolved.starts_with(&root) {
        return not_found();
    }
    let Ok(bytes) = std::fs::read(&resolved) else {
        return not_found();
    };

    let content_type = match resolved
        .extension()
        .and_then(|extension| extension.to_str())
    {
        Some("png") => "image/png",
        Some("jpg" | "jpeg") => "image/jpeg",
        Some("webp") => "image/webp",
        Some("svg") => "image/svg+xml",
        Some("pdf") => "application/pdf",
        _ => "application/octet-stream",
    };
    tauri::http::Response::builder()
        .header("Content-Type", content_type)
        // A render is replaced in place, so a cached copy would show the previous picture.
        .header("Cache-Control", "no-store")
        .body(bytes)
        .expect("render response")
}

/// Build and run the workbench window.
///
/// # Panics
///
/// Panics when Tauri cannot create the window, which is unrecoverable at startup.
pub fn run() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_dialog::init());

    // Registered so a signed release can be verified against the public key compiled into this
    // build. Phase 1 produces and verifies signed updater artifacts; the in-application check
    // and prompt are a later phase, so nothing here contacts the network on its own.
    #[cfg(windows)]
    let builder = builder.plugin(tauri_plugin_updater::Builder::new().build());

    builder
        .register_uri_scheme_protocol("arcavex", |context, request| {
            let state = context.app_handle().state::<SharedState>();
            serve_render(&state, &request)
        })
        .setup(|app| {
            let directory = app
                .path()
                .app_config_dir()
                .unwrap_or_else(|_| PathBuf::from("."));
            let state: SharedState = Arc::new(build_state(&directory));
            state.attach(app.handle().clone());
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            gateway::engine_state,
            gateway::engine_stderr,
            gateway::restart_engine,
            gateway::choose_project_directory,
            gateway::open_project,
            gateway::close_project,
            gateway::project_snapshot,
            gateway::validate_project,
            gateway::active_target,
            gateway::set_active_target,
            gateway::render_status,
            gateway::request_render,
            gateway::layer_tree,
            gateway::hit_test,
            gateway::ui_metadata,
            gateway::set_ui_metadata,
            gateway::project_policy,
            gateway::set_project_policy,
            gateway::list_proposals,
            gateway::approve_proposal,
            gateway::reject_proposal,
            gateway::activity,
            gateway::settings,
            gateway::update_settings,
        ])
        .run(tauri::generate_context!())
        .expect("Arcavex Desktop failed to start");
}
