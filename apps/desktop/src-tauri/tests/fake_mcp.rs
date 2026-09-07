//! A scripted MCP engine over in-memory pipes, so supervision is tested without a real process.
//!
//! Real-process behaviour (spawning the frozen artifact, piped stdio, process-tree shutdown) is
//! covered by the packaged sidecar smoke tests, which run the actual binary.

#![allow(dead_code)]

use std::io;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use arcavex_desktop_lib::engine::{
    EngineHandle, EngineLauncher, EngineSpec, EngineStreams, LaunchedEngine,
};
use serde_json::{json, Value};
use tokio::io::{duplex, AsyncBufReadExt, AsyncWriteExt, BufReader};

/// How one scripted engine behaves for the lifetime of a single launch.
#[derive(Debug, Clone)]
pub struct FakeEngineScript {
    pub mcp_contract_version: String,
    pub produced_ir_version: String,
    /// Fail this many launches with a spawn error before any process appears.
    pub failed_launches: usize,
    /// Close the streams after this many requests, modelling a crash mid-session.
    pub close_after_requests: Option<usize>,
    /// Never answer, modelling an engine that hangs before the handshake completes.
    pub silent: bool,
    pub stderr_lines: Vec<String>,
}

impl Default for FakeEngineScript {
    fn default() -> Self {
        Self {
            mcp_contract_version: "2025-06-18".to_owned(),
            produced_ir_version: "1.0".to_owned(),
            failed_launches: 0,
            close_after_requests: None,
            silent: false,
            stderr_lines: Vec::new(),
        }
    }
}

/// An [`EngineLauncher`] that hands out scripted engines and counts what happened.
pub struct FakeLauncher {
    script: Mutex<FakeEngineScript>,
    launches: Arc<AtomicUsize>,
    terminations: Arc<AtomicUsize>,
}

impl FakeLauncher {
    #[must_use]
    pub fn new(script: FakeEngineScript) -> Self {
        Self {
            script: Mutex::new(script),
            launches: Arc::new(AtomicUsize::new(0)),
            terminations: Arc::new(AtomicUsize::new(0)),
        }
    }

    /// Counters that outlive handing the launcher to a supervisor.
    #[must_use]
    pub fn counters(&self) -> FakeCounters {
        FakeCounters {
            launches: Arc::clone(&self.launches),
            terminations: Arc::clone(&self.terminations),
        }
    }
}

/// Observes a launcher that a supervisor now owns.
#[derive(Debug, Clone)]
pub struct FakeCounters {
    launches: Arc<AtomicUsize>,
    terminations: Arc<AtomicUsize>,
}

impl FakeCounters {
    #[must_use]
    pub fn launches(&self) -> usize {
        self.launches.load(Ordering::SeqCst)
    }

    /// How many launched processes were ended, whether by replacement or by shutdown.
    #[must_use]
    pub fn terminations(&self) -> usize {
        self.terminations.load(Ordering::SeqCst)
    }
}

impl EngineLauncher for FakeLauncher {
    fn launch(&self, _spec: &EngineSpec) -> io::Result<LaunchedEngine> {
        let attempt = self.launches.fetch_add(1, Ordering::SeqCst);
        let script = self.script.lock().expect("script").clone();
        if attempt < script.failed_launches {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "scripted launch failure",
            ));
        }

        let (desktop_writes, engine_reads) = duplex(64 * 1024);
        let (engine_writes, desktop_reads) = duplex(64 * 1024);
        let (mut engine_stderr, desktop_stderr) = duplex(64 * 1024);

        let stderr_lines = script.stderr_lines.clone();
        tokio::spawn(async move {
            for line in stderr_lines {
                let _ = engine_stderr
                    .write_all(format!("{line}\n").as_bytes())
                    .await;
            }
        });
        tokio::spawn(serve(engine_reads, engine_writes, script));

        Ok(LaunchedEngine {
            streams: EngineStreams {
                stdin: Box::new(desktop_writes),
                stdout: Box::new(desktop_reads),
                stderr: Box::new(desktop_stderr),
            },
            handle: Box::new(FakeHandle {
                terminations: Arc::clone(&self.terminations),
            }),
        })
    }
}

struct FakeHandle {
    terminations: Arc<AtomicUsize>,
}

impl EngineHandle for FakeHandle {
    fn terminate(&mut self) {
        self.terminations.fetch_add(1, Ordering::SeqCst);
    }
}

async fn serve<R, W>(reader: R, mut writer: W, script: FakeEngineScript)
where
    R: tokio::io::AsyncRead + Unpin + Send + 'static,
    W: tokio::io::AsyncWrite + Unpin + Send + 'static,
{
    let mut requests = BufReader::new(reader);
    let mut handled = 0_usize;
    let mut line = String::new();

    loop {
        line.clear();
        match requests.read_line(&mut line).await {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
        let Ok(message) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        let Some(id) = message.get("id").cloned() else {
            continue; // A notification needs no response.
        };
        if script.silent {
            continue;
        }

        let response = json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": result_for(&message, &script),
        });
        if writer
            .write_all(&arcavex_desktop_lib::engine::encode(&response))
            .await
            .is_err()
        {
            return;
        }

        handled += 1;
        if Some(handled) == script.close_after_requests {
            return;
        }
    }
}

fn result_for(message: &Value, script: &FakeEngineScript) -> Value {
    let method = message.get("method").and_then(Value::as_str).unwrap_or("");
    if method == "initialize" {
        return json!({
            "protocolVersion": script.mcp_contract_version,
            "capabilities": {},
            "serverInfo": {"name": "arcavex", "version": "0.0.0-fake"},
        });
    }

    let tool = message
        .get("params")
        .and_then(|params| params.get("name"))
        .and_then(Value::as_str)
        .unwrap_or("");
    if tool == "engine_handshake" {
        return json!({
            "structuredContent": {
                "response_version": 1,
                "ok": true,
                "mcp_contract_version": script.mcp_contract_version,
                "produced_ir_version": script.produced_ir_version,
                "identity": {"engine_version": "0.0.0-fake"},
            }
        });
    }
    json!({"structuredContent": {"response_version": 1, "ok": true, "tool": tool}})
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    use arcavex_desktop_lib::engine::McpClient;

    #[tokio::test]
    async fn the_fake_engine_answers_initialize_and_the_handshake_tool() {
        let launcher = FakeLauncher::new(FakeEngineScript::default());
        let spec = spec();
        let launched = launcher.launch(&spec).expect("launch");
        let client = McpClient::connect(
            launched.streams.stdout,
            launched.streams.stdin,
            Duration::from_secs(2),
        );

        let initialize = client
            .call("initialize", json!({}))
            .await
            .expect("initialize");
        assert_eq!(initialize["protocolVersion"], "2025-06-18");

        let handshake = client
            .call("tools/call", json!({"name": "engine_handshake"}))
            .await
            .expect("handshake");
        assert_eq!(handshake["structuredContent"]["produced_ir_version"], "1.0");
    }

    fn spec() -> EngineSpec {
        EngineSpec {
            program: std::path::PathBuf::from("fake"),
            args: Vec::new(),
            expected_sha256: None,
            expected_mcp_contract: "2025-06-18".to_owned(),
            accepted_ir_versions: vec!["1.0".to_owned()],
            call_timeout: Duration::from_secs(2),
        }
    }
}
