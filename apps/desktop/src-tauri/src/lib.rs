//! Arcavex Desktop core.
//!
//! The Rust side owns everything the WebView must not: the private MCP sidecar, the project
//! watcher, the render queue, and settings. The WebView reaches all of it through typed
//! commands and one versioned event envelope, never through a network origin.

#![forbid(unsafe_code)]

pub mod engine;
pub mod events;
pub mod gateway;

use std::path::PathBuf;
use std::time::Duration;

use engine::{CommandLauncher, EngineLock, EngineSpec};
use gateway::DesktopState;

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
pub fn build_state() -> DesktopState {
    let lock = match EngineLock::parse(ENGINE_LOCK_SOURCE) {
        Ok(lock) => lock,
        Err(error) => {
            return DesktopState::unavailable(format!(
                "The bundled engine lock manifest is unreadable: {error}"
            ))
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
        Some(spec) => DesktopState::new(CommandLauncher, spec),
        None => DesktopState::unavailable(format!(
            "This build pins engine {} but ships no artifact for {TARGET_TRIPLE}. Set \
             {ENGINE_OVERRIDE_VARIABLE} to a locally built engine to continue.",
            lock.engine_version
        )),
    }
}

/// Where the pinned sidecar sits: beside the installed executable, or in the source tree.
fn binaries_directory() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|executable| executable.parent().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries"))
}

/// Build and run the workbench window.
///
/// # Panics
///
/// Panics when Tauri cannot create the window, which is unrecoverable at startup.
pub fn run() {
    tauri::Builder::default()
        .manage(build_state())
        .invoke_handler(tauri::generate_handler![
            gateway::engine_state,
            gateway::engine_stderr,
            gateway::restart_engine,
            gateway::validate_project,
            gateway::project_snapshot,
        ])
        .run(tauri::generate_context!())
        .expect("Arcavex Desktop failed to start");
}
