//! The typed surface the WebView may call. Nothing reaches the engine except through here.

use std::sync::{Arc, Mutex};

use serde_json::{json, Value};

use crate::engine::{
    CommandLauncher, EngineLauncher, EngineSpec, EngineState, EngineStatus, McpClient, Supervisor,
};

/// Gateway state for the real application.
pub type DesktopState = GatewayState<CommandLauncher>;

/// Holds the supervised engine and the connected client, and starts one on first use.
pub struct GatewayState<L: EngineLauncher> {
    /// Absent when this build ships no artifact for the running platform.
    supervisor: Option<Arc<Supervisor<L>>>,
    unavailable: Option<String>,
    client: Mutex<Option<Arc<McpClient>>>,
}

impl<L: EngineLauncher> GatewayState<L> {
    #[must_use]
    pub fn new(launcher: L, spec: EngineSpec) -> Self {
        Self {
            supervisor: Some(Arc::new(Supervisor::new(launcher, spec))),
            unavailable: None,
            client: Mutex::new(None),
        }
    }

    /// Open the workbench in diagnostic mode when there is no engine to supervise at all.
    #[must_use]
    pub fn unavailable(reason: String) -> Self {
        Self {
            supervisor: None,
            unavailable: Some(reason),
            client: Mutex::new(None),
        }
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

    /// End the engine process. Called when the window closes.
    pub fn shutdown(&self) {
        *self.client.lock().expect("engine client") = None;
        if let Some(supervisor) = &self.supervisor {
            supervisor.shutdown();
        }
    }
}

#[tauri::command]
pub fn engine_state(state: tauri::State<'_, DesktopState>) -> EngineState {
    state.engine_state()
}

#[tauri::command]
pub fn engine_stderr(state: tauri::State<'_, DesktopState>) -> Vec<String> {
    state.engine_stderr()
}

#[tauri::command]
pub async fn restart_engine(state: tauri::State<'_, DesktopState>) -> Result<EngineState, String> {
    state.restart().await
}

#[tauri::command]
pub async fn validate_project(
    state: tauri::State<'_, DesktopState>,
    path: String,
) -> Result<Value, String> {
    state
        .call_tool("validate_project", json!({ "path": path }))
        .await
}

#[tauri::command]
pub async fn project_snapshot(
    state: tauri::State<'_, DesktopState>,
    path: String,
) -> Result<Value, String> {
    state
        .call_tool("project_snapshot", json!({ "path": path }))
        .await
}
