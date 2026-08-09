//! One versioned envelope carries every desktop event, so the WebView can refuse an unknown one.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter};

use crate::engine::EngineState;
use crate::{DESKTOP_EVENT_CHANNEL, DESKTOP_EVENT_VERSION};

/// The payload published on [`DESKTOP_EVENT_CHANNEL`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DesktopEventKind {
    Engine { engine: EngineState },
    Project { snapshot: Value },
    Render { render: Value },
    Activity { entry: Value },
    Settings { settings: Value },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesktopEvent {
    pub version: u32,
    #[serde(flatten)]
    pub kind: DesktopEventKind,
}

impl DesktopEvent {
    #[must_use]
    pub fn new(kind: DesktopEventKind) -> Self {
        Self {
            version: DESKTOP_EVENT_VERSION,
            kind,
        }
    }
}

/// Publish one event to the workbench window.
///
/// A failed emit means the window is gone, which is not a reason to fail the operation that
/// produced the event.
pub fn publish(app: &AppHandle, kind: DesktopEventKind) {
    let _ = app.emit(DESKTOP_EVENT_CHANNEL, DesktopEvent::new(kind));
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::EngineStatus;

    #[test]
    fn serializes_as_a_flat_versioned_envelope_the_frontend_can_discriminate() {
        let event = DesktopEvent::new(DesktopEventKind::Engine {
            engine: EngineState {
                status: EngineStatus::Ready,
                handshake: None,
                artifact_path: Some("/opt/arcavex".to_owned()),
                restart_count: 0,
                message: None,
            },
        });

        let value = serde_json::to_value(&event).expect("serialize");

        assert_eq!(value["version"], DESKTOP_EVENT_VERSION);
        assert_eq!(value["type"], "engine");
        assert_eq!(value["engine"]["status"], "ready");
        assert_eq!(value["engine"]["artifact_path"], "/opt/arcavex");
    }

    #[test]
    fn round_trips_every_event_kind() {
        for kind in [
            DesktopEventKind::Project {
                snapshot: serde_json::json!({"ok": true}),
            },
            DesktopEventKind::Render {
                render: serde_json::json!({"state": "current"}),
            },
            DesktopEventKind::Activity {
                entry: serde_json::json!({"id": "a1"}),
            },
            DesktopEventKind::Settings {
                settings: serde_json::json!({"themeId": "arcavex-dark"}),
            },
        ] {
            let event = DesktopEvent::new(kind);
            let text = serde_json::to_string(&event).expect("serialize");
            let parsed: DesktopEvent = serde_json::from_str(&text).expect("deserialize");
            assert_eq!(parsed, event);
        }
    }
}
