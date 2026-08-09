//! Keeps exactly one pinned engine process alive, and refuses to pretend when it cannot.
//!
//! The desktop never renders against an engine it has not identified. A launch is only `Ready`
//! after the artifact hash matches the committed lock and the handshake reports a compatible MCP
//! contract and IR version. Anything else is a diagnostic mode with the reason attached.

use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, BufReader};

use super::client::{EngineError, McpClient};

/// Delay before the first restart; each further attempt doubles it.
pub const FIRST_RESTART_DELAY: Duration = Duration::from_millis(250);
/// Restarting slower than this only makes the workbench feel abandoned.
pub const MAX_RESTART_DELAY: Duration = Duration::from_secs(30);
/// Consecutive failed starts after which the supervisor stops and asks for a decision.
pub const CRASH_LOOP_THRESHOLD: u32 = 3;
/// Lines of sidecar stderr retained for the diagnostics panel.
pub const STDERR_TAIL_LINES: usize = 200;

/// The MCP protocol revision this desktop build speaks.
pub const MCP_PROTOCOL_VERSION: &str = "2025-06-18";

/// Bounded exponential backoff. Attempt 1 is the first restart, not the first launch.
#[must_use]
pub fn restart_delay(attempt: u32) -> Duration {
    let doubling = attempt.saturating_sub(1).min(16);
    FIRST_RESTART_DELAY
        .saturating_mul(1_u32 << doubling)
        .min(MAX_RESTART_DELAY)
}

// ------------------------------------------------------------------------------- engine lock

/// One platform's pinned artifact, as committed in `binaries/engine-lock.json`.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct LockedArtifact {
    pub file: String,
    pub sha256: String,
}

/// The engine release this desktop build is pinned to.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct EngineLock {
    pub engine_version: String,
    pub release_tag: String,
    pub mcp_contract_version: String,
    pub produced_ir_version: String,
    pub accepted_ir_versions: Vec<String>,
    /// Keyed by Rust target triple so one lock covers every shipped platform.
    pub artifacts: BTreeMap<String, LockedArtifact>,
}

impl EngineLock {
    /// Parse the committed lock manifest.
    ///
    /// # Errors
    ///
    /// Returns an error when the manifest is not valid JSON in the expected shape.
    pub fn parse(source: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(source)
    }

    /// The artifact for one target triple, or `None` when this platform is not shipped.
    #[must_use]
    pub fn artifact_for(&self, target_triple: &str) -> Option<&LockedArtifact> {
        self.artifacts.get(target_triple)
    }
}

/// Hash a file the same way the release pipeline does.
///
/// # Errors
///
/// Returns an error when the file cannot be read.
pub fn sha256_file(path: &Path) -> io::Result<String> {
    let bytes = std::fs::read(path)?;
    let digest = Sha256::digest(&bytes);
    Ok(digest.iter().map(|byte| format!("{byte:02x}")).collect())
}

// ---------------------------------------------------------------------------------- launching

/// The three pipes a supervised engine communicates through.
pub struct EngineStreams {
    pub stdin: Box<dyn AsyncWrite + Unpin + Send>,
    pub stdout: Box<dyn AsyncRead + Unpin + Send>,
    pub stderr: Box<dyn AsyncRead + Unpin + Send>,
}

/// A running engine process, owned so the supervisor can end it deterministically.
pub trait EngineHandle: Send {
    /// End the process and any children it started. Called on shutdown and on restart.
    fn terminate(&mut self);
}

pub struct LaunchedEngine {
    pub streams: EngineStreams,
    pub handle: Box<dyn EngineHandle>,
}

/// How the supervisor obtains a process. The real one spawns; tests script one.
pub trait EngineLauncher: Send + Sync + 'static {
    /// Start the engine in MCP stdio mode with all three streams piped.
    ///
    /// # Errors
    ///
    /// Returns an error when the process cannot be spawned.
    fn launch(&self, spec: &EngineSpec) -> io::Result<LaunchedEngine>;
}

/// Everything needed to start and then trust one engine process.
#[derive(Debug, Clone)]
pub struct EngineSpec {
    pub program: PathBuf,
    pub args: Vec<String>,
    /// The hash from the committed lock; `None` only for a developer override build.
    pub expected_sha256: Option<String>,
    pub expected_mcp_contract: String,
    pub accepted_ir_versions: Vec<String>,
    pub call_timeout: Duration,
}

impl EngineSpec {
    /// The pinned artifact for this platform, or a developer override when one is configured.
    ///
    /// An override is deliberately not hash-checked: it exists so a developer can run an engine
    /// they just built. Packaged builds pass `None` and therefore always verify.
    #[must_use]
    pub fn resolve(
        lock: &EngineLock,
        binaries_dir: &Path,
        target_triple: &str,
        override_path: Option<PathBuf>,
        call_timeout: Duration,
    ) -> Option<Self> {
        let (program, expected_sha256) = match override_path {
            Some(path) => (path, None),
            None => {
                let artifact = lock.artifact_for(target_triple)?;
                (
                    binaries_dir.join(&artifact.file),
                    Some(artifact.sha256.clone()),
                )
            }
        };
        Some(Self {
            program,
            args: vec!["mcp".to_owned(), "serve".to_owned()],
            expected_sha256,
            expected_mcp_contract: lock.mcp_contract_version.clone(),
            accepted_ir_versions: lock.accepted_ir_versions.clone(),
            call_timeout,
        })
    }
}

/// Spawns the real pinned executable with piped stdio.
#[derive(Debug, Default)]
pub struct CommandLauncher;

impl EngineLauncher for CommandLauncher {
    fn launch(&self, spec: &EngineSpec) -> io::Result<LaunchedEngine> {
        let mut child = tokio::process::Command::new(&spec.program)
            .args(&spec.args)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()?;

        let stdin = child.stdin.take().ok_or_else(missing_pipe)?;
        let stdout = child.stdout.take().ok_or_else(missing_pipe)?;
        let stderr = child.stderr.take().ok_or_else(missing_pipe)?;

        Ok(LaunchedEngine {
            streams: EngineStreams {
                stdin: Box::new(stdin),
                stdout: Box::new(stdout),
                stderr: Box::new(stderr),
            },
            handle: Box::new(ChildHandle { child }),
        })
    }
}

fn missing_pipe() -> io::Error {
    io::Error::new(io::ErrorKind::BrokenPipe, "engine stdio was not piped")
}

struct ChildHandle {
    child: tokio::process::Child,
}

impl EngineHandle for ChildHandle {
    fn terminate(&mut self) {
        // A frozen engine can outlive a bare kill by leaving children behind, so on Windows the
        // whole tree is ended by PID; elsewhere the process group dies with the child.
        #[cfg(windows)]
        if let Some(id) = self.child.id() {
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &id.to_string(), "/T", "/F"])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
        }
        let _ = self.child.start_kill();
    }
}

// -------------------------------------------------------------------------------- supervision

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EngineStatus {
    Starting,
    Ready,
    Restarting,
    Incompatible,
    Failed,
}

/// Exactly the engine state the workbench renders; the field names match the frontend port.
// Desktop-owned payloads are camelCase because that is what the WebView declares; engine
// reports keep the snake_case the Pydantic contracts define.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineState {
    pub status: EngineStatus,
    pub handshake: Option<Value>,
    pub artifact_path: Option<String>,
    pub restart_count: u32,
    pub message: Option<String>,
}

impl EngineState {
    #[must_use]
    pub fn starting() -> Self {
        Self {
            status: EngineStatus::Starting,
            handshake: None,
            artifact_path: None,
            restart_count: 0,
            message: None,
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum StartupError {
    #[error("the pinned engine could not be started: {0}")]
    Spawn(#[from] io::Error),
    #[error("the engine artifact hash is {actual}, but the lock pins {expected}")]
    ArtifactMismatch { expected: String, actual: String },
    #[error("the engine did not complete the MCP handshake: {0}")]
    Handshake(#[from] EngineError),
    #[error("the engine reports MCP contract {contract} and IR {ir}, which this build cannot use")]
    Incompatible { contract: String, ir: String },
    #[error("the engine failed to start {attempts} times in a row and was not restarted again")]
    CrashLoop { attempts: u32 },
}

/// Owns the engine lifecycle: verify, launch, handshake, and restart with bounded backoff.
pub struct Supervisor<L: EngineLauncher> {
    launcher: L,
    spec: EngineSpec,
    state: Arc<Mutex<EngineState>>,
    stderr: Arc<Mutex<Vec<String>>>,
    handle: Mutex<Option<Box<dyn EngineHandle>>>,
}

impl<L: EngineLauncher> Supervisor<L> {
    #[must_use]
    pub fn new(launcher: L, spec: EngineSpec) -> Self {
        Self {
            launcher,
            spec,
            state: Arc::new(Mutex::new(EngineState::starting())),
            stderr: Arc::new(Mutex::new(Vec::new())),
            handle: Mutex::new(None),
        }
    }

    #[must_use]
    pub fn state(&self) -> EngineState {
        self.state.lock().expect("engine state").clone()
    }

    /// The retained tail of sidecar stderr, oldest first.
    #[must_use]
    pub fn stderr_tail(&self) -> Vec<String> {
        self.stderr.lock().expect("stderr tail").clone()
    }

    /// Start the engine, retrying with bounded exponential backoff.
    ///
    /// # Errors
    ///
    /// Returns the last failure once `CRASH_LOOP_THRESHOLD` consecutive attempts have failed, or
    /// immediately when the failure is one that retrying cannot fix.
    pub async fn start(&self) -> Result<Arc<McpClient>, StartupError> {
        let mut attempt = 0_u32;
        loop {
            match self.attempt().await {
                Ok(client) => return Ok(client),
                Err(error) => {
                    attempt += 1;
                    if !is_retryable(&error) {
                        self.fail(EngineStatus::Incompatible, &error, attempt);
                        return Err(error);
                    }
                    if attempt >= CRASH_LOOP_THRESHOLD {
                        self.fail(EngineStatus::Failed, &error, attempt);
                        return Err(StartupError::CrashLoop { attempts: attempt });
                    }
                    self.set_status(EngineStatus::Restarting, Some(error.to_string()), attempt);
                    tokio::time::sleep(restart_delay(attempt)).await;
                }
            }
        }
    }

    /// Verify, launch, and handshake exactly once.
    ///
    /// # Errors
    ///
    /// Returns the reason this attempt could not produce a trusted engine.
    pub async fn attempt(&self) -> Result<Arc<McpClient>, StartupError> {
        if let Some(expected) = &self.spec.expected_sha256 {
            let actual = sha256_file(&self.spec.program)?;
            if &actual != expected {
                return Err(StartupError::ArtifactMismatch {
                    expected: expected.clone(),
                    actual,
                });
            }
        }

        let launched = self.launcher.launch(&self.spec)?;
        self.replace_handle(launched.handle);
        let EngineStreams {
            stdin,
            stdout,
            stderr,
        } = launched.streams;

        tokio::spawn(capture_stderr(stderr, Arc::clone(&self.stderr)));
        let client = Arc::new(McpClient::connect(stdout, stdin, self.spec.call_timeout));

        let handshake = self.perform_handshake(&client).await?;
        let mut state = self.state.lock().expect("engine state");
        state.status = EngineStatus::Ready;
        state.artifact_path = Some(self.spec.program.display().to_string());
        state.message = None;
        state.handshake = Some(handshake);
        drop(state);
        Ok(client)
    }

    /// Stop the engine. Closing the write side first lets a healthy engine exit cleanly.
    pub fn shutdown(&self) {
        if let Some(mut handle) = self.handle.lock().expect("engine handle").take() {
            handle.terminate();
        }
    }

    async fn perform_handshake(&self, client: &McpClient) -> Result<Value, StartupError> {
        client
            .call(
                "initialize",
                json!({
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "arcavex-desktop", "version": env!("CARGO_PKG_VERSION")},
                }),
            )
            .await?;
        client.notify("notifications/initialized", json!({}))?;

        let response = client
            .call(
                "tools/call",
                json!({"name": "engine_handshake", "arguments": {}}),
            )
            .await?;
        let report = response
            .get("structuredContent")
            .cloned()
            .unwrap_or(response);

        let contract = report
            .get("mcp_contract_version")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let ir = report
            .get("produced_ir_version")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        if contract != self.spec.expected_mcp_contract
            || !self
                .spec
                .accepted_ir_versions
                .iter()
                .any(|accepted| accepted == &ir)
        {
            return Err(StartupError::Incompatible { contract, ir });
        }
        Ok(report)
    }

    fn replace_handle(&self, handle: Box<dyn EngineHandle>) {
        if let Some(mut previous) = self.handle.lock().expect("engine handle").replace(handle) {
            previous.terminate();
        }
    }

    fn set_status(&self, status: EngineStatus, message: Option<String>, restarts: u32) {
        let mut state = self.state.lock().expect("engine state");
        state.status = status;
        state.message = message;
        state.restart_count = restarts;
    }

    fn fail(&self, status: EngineStatus, error: &StartupError, attempts: u32) {
        self.shutdown();
        let message = if status == EngineStatus::Failed {
            format!(
                "{error}. Extensions are the most common cause; disable them in project policy \
                 before retrying."
            )
        } else {
            error.to_string()
        };
        self.set_status(status, Some(message), attempts);
    }
}

/// An incompatible engine will report the same versions next time, so retrying cannot help.
fn is_retryable(error: &StartupError) -> bool {
    !matches!(
        error,
        StartupError::Incompatible { .. } | StartupError::ArtifactMismatch { .. }
    )
}

async fn capture_stderr<R>(stderr: R, sink: Arc<Mutex<Vec<String>>>)
where
    R: AsyncRead + Unpin + Send + 'static,
{
    let mut reader = BufReader::new(stderr);
    let mut line = Vec::new();
    let mut byte = [0_u8; 1];

    while matches!(reader.read(&mut byte).await, Ok(1)) {
        if byte[0] != b'\n' {
            line.push(byte[0]);
            continue;
        }
        push_line(&sink, &mut line);
    }
    if !line.is_empty() {
        push_line(&sink, &mut line);
    }
}

fn push_line(sink: &Arc<Mutex<Vec<String>>>, line: &mut Vec<u8>) {
    let text = String::from_utf8_lossy(line).trim_end().to_owned();
    line.clear();
    let mut tail = sink.lock().expect("stderr tail");
    tail.push(text);
    if tail.len() > STDERR_TAIL_LINES {
        let excess = tail.len() - STDERR_TAIL_LINES;
        tail.drain(..excess);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backs_off_exponentially_up_to_a_ceiling() {
        assert_eq!(restart_delay(1), Duration::from_millis(250));
        assert_eq!(restart_delay(2), Duration::from_millis(500));
        assert_eq!(restart_delay(3), Duration::from_millis(1_000));
        assert_eq!(restart_delay(20), MAX_RESTART_DELAY);
    }

    #[test]
    fn resolves_the_pinned_artifact_for_this_platform() {
        let lock = EngineLock {
            engine_version: "1.2.3".to_owned(),
            release_tag: "engine-v1.2.3".to_owned(),
            mcp_contract_version: "2025-06-18".to_owned(),
            produced_ir_version: "1.0".to_owned(),
            accepted_ir_versions: vec!["1.0".to_owned()],
            artifacts: BTreeMap::from([(
                "x86_64-pc-windows-msvc".to_owned(),
                LockedArtifact {
                    file: "arcavex.exe".to_owned(),
                    sha256: "ab".repeat(32),
                },
            )]),
        };

        let spec = EngineSpec::resolve(
            &lock,
            Path::new("binaries"),
            "x86_64-pc-windows-msvc",
            None,
            Duration::from_secs(30),
        )
        .expect("this platform is shipped");

        assert_eq!(spec.program, Path::new("binaries").join("arcavex.exe"));
        assert_eq!(spec.expected_sha256, Some("ab".repeat(32)));
        assert_eq!(spec.args, vec!["mcp".to_owned(), "serve".to_owned()]);
        assert!(EngineSpec::resolve(
            &lock,
            Path::new("binaries"),
            "aarch64-unknown-linux-gnu",
            None,
            Duration::from_secs(30),
        )
        .is_none());
    }

    #[test]
    fn a_developer_override_replaces_the_artifact_and_its_hash_check() {
        let lock = EngineLock {
            engine_version: "1.2.3".to_owned(),
            release_tag: "engine-v1.2.3".to_owned(),
            mcp_contract_version: "2025-06-18".to_owned(),
            produced_ir_version: "1.0".to_owned(),
            accepted_ir_versions: vec!["1.0".to_owned()],
            artifacts: BTreeMap::new(),
        };

        let spec = EngineSpec::resolve(
            &lock,
            Path::new("binaries"),
            "x86_64-pc-windows-msvc",
            Some(PathBuf::from("/dev/arcavex")),
            Duration::from_secs(30),
        )
        .expect("an override needs no shipped artifact");

        assert_eq!(spec.program, PathBuf::from("/dev/arcavex"));
        assert_eq!(spec.expected_sha256, None);
    }

    #[test]
    fn hashes_a_file_the_way_the_release_pipeline_does() {
        let path = std::env::temp_dir().join("arcavex-supervisor-hash.bin");
        std::fs::write(&path, b"arcavex").expect("write");

        let digest = sha256_file(&path).expect("hash");

        assert_eq!(digest.len(), 64);
        assert_eq!(digest, sha256_file(&path).expect("hash twice"));
        std::fs::remove_file(&path).expect("cleanup");
    }
}
