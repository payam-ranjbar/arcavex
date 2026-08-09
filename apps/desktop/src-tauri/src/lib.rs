//! Arcavex Desktop core.
//!
//! The Rust side owns everything the WebView must not: the private MCP sidecar, the project
//! watcher, the render queue, and settings. The WebView reaches all of it through typed
//! commands and one versioned event envelope, never through a network origin.

#![forbid(unsafe_code)]

/// The event envelope version the WebView is compiled against. A frontend that understands a
/// different version drops the event rather than guessing at its shape.
pub const DESKTOP_EVENT_VERSION: u32 = 1;

/// Tauri channel every desktop event travels on.
pub const DESKTOP_EVENT_CHANNEL: &str = "arcavex:desktop-event";

/// Build and run the workbench window.
///
/// # Panics
///
/// Panics when Tauri cannot create the window, which is unrecoverable at startup.
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("Arcavex Desktop failed to start");
}
