//! App-local preferences. Project-local policy lives in the project, not here.

use serde::{Deserialize, Serialize};

/// Bumped only when a field's meaning changes; unknown newer files fall back to defaults.
pub const SETTINGS_VERSION: u32 = 1;

/// How many recent projects the welcome screen offers.
pub const MAX_RECENT_PROJECTS: usize = 10;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum LiveRenderMode {
    /// The approved default: render after every committed change to the active target.
    #[default]
    EveryChange,
    Manual,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AutomationMode {
    /// The approved default. Visible and changeable, never silently imposed.
    #[default]
    Unrestricted,
    Review,
    ReadOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ExtensionMode {
    #[default]
    Unrestricted,
    Disabled,
}

/// Window and panel state that belongs to the application rather than to a project.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct WorkspacePreferences {
    pub left_sidebar_visible: bool,
    pub right_inspector_visible: bool,
    pub activity_visible: bool,
}

impl Default for WorkspacePreferences {
    fn default() -> Self {
        Self {
            left_sidebar_visible: true,
            right_inspector_visible: true,
            activity_visible: false,
        }
    }
}

/// Everything the desktop remembers between launches.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct DesktopSettings {
    pub version: u32,
    /// Most recently opened first; the desktop stores a pointer, never a copy of the project.
    pub recent_projects: Vec<String>,
    pub theme_id: String,
    pub branding_id: String,
    pub live_render: LiveRenderMode,
    /// The default policy offered to a project that has not declared one.
    pub automation: AutomationMode,
    pub extensions: ExtensionMode,
    /// Off by default: rendering and editing are fully local, and update checks are optional.
    pub check_for_updates: bool,
    pub engine_override_path: Option<String>,
    pub workspace: WorkspacePreferences,
}

impl Default for DesktopSettings {
    fn default() -> Self {
        Self {
            version: SETTINGS_VERSION,
            recent_projects: Vec::new(),
            theme_id: "arcavex-dark".to_owned(),
            branding_id: "arcavex".to_owned(),
            live_render: LiveRenderMode::default(),
            automation: AutomationMode::default(),
            extensions: ExtensionMode::default(),
            check_for_updates: false,
            engine_override_path: None,
            workspace: WorkspacePreferences::default(),
        }
    }
}

impl DesktopSettings {
    /// Record a project as most recently opened, without duplicating or growing without bound.
    pub fn remember_project(&mut self, path: &str) {
        self.recent_projects.retain(|entry| entry != path);
        self.recent_projects.insert(0, path.to_owned());
        self.recent_projects.truncate(MAX_RECENT_PROJECTS);
    }

    /// Drop a project the user no longer wants offered, or that no longer exists.
    pub fn forget_project(&mut self, path: &str) {
        self.recent_projects.retain(|entry| entry != path);
    }
}
