//! Headless verification of an installed Arcavex Desktop.
//!
//! The workbench starts no engine until someone opens a project, which is the right behaviour and
//! also means that launching the packaged application proves almost nothing on its own: a window
//! appears whether or not the bundled engine is present, trusted, or able to render.
//!
//! `Arcavex Desktop.exe --self-check` runs the same startup path the workbench does — resolve the
//! pinned artifact, verify its digest, hand it to the supervisor, complete the MCP handshake, open
//! a project, render, restart the engine, render again — with no window and no user. It is what
//! `scripts/verify_desktop_bundle.ps1` drives against a real installation, and what a support
//! request can ask someone to run.
//!
//! A Windows release build has no console, so the report is written to a file rather than stdout.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::gateway::SharedState;
use crate::rendering::RenderState;

/// How long one render may take before the check gives up. Generous: a cold engine compiling a
/// first template on a loaded CI runner is slow, and a false failure here is worse than a slow pass.
const RENDER_TIMEOUT: Duration = Duration::from_secs(180);

/// How often the render state is sampled while waiting.
const POLL_INTERVAL: Duration = Duration::from_millis(250);

#[derive(Debug, Serialize)]
pub struct SelfCheckStep {
    pub name: String,
    pub ok: bool,
    pub ms: u128,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct SelfCheckReport {
    pub ok: bool,
    pub desktop_version: String,
    pub target_triple: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_artifact: Option<String>,
    pub steps: Vec<SelfCheckStep>,
}

/// Collects steps so a failure is reported alongside everything that did work.
struct Recorder {
    steps: Vec<SelfCheckStep>,
}

impl Recorder {
    fn new() -> Self {
        Self { steps: Vec::new() }
    }

    fn record(&mut self, name: &str, started: Instant, result: Result<(), String>) -> bool {
        let ok = result.is_ok();
        self.steps.push(SelfCheckStep {
            name: name.to_owned(),
            ok,
            ms: started.elapsed().as_millis(),
            detail: result.err(),
        });
        ok
    }
}

async fn wait_for_render(state: &SharedState) -> Result<(), String> {
    let deadline = Instant::now() + RENDER_TIMEOUT;
    loop {
        let status = state.render_status();
        match status.state {
            RenderState::Current => return Ok(()),
            RenderState::Failed => {
                return Err(format!("render failed: {:?}", status.diagnostics));
            }
            _ if Instant::now() >= deadline => {
                return Err(format!("render did not settle within {RENDER_TIMEOUT:?}"));
            }
            _ => tokio::time::sleep(POLL_INTERVAL).await,
        }
    }
}

/// Run every check against a state built exactly the way the workbench builds it.
pub async fn self_check(project: Option<&Path>, settings_directory: &Path) -> SelfCheckReport {
    let state: SharedState = Arc::new(crate::build_state(settings_directory));
    let mut recorder = Recorder::new();

    // Starting the client is the whole trust chain in one call: resolve the pinned path, hash the
    // artifact, refuse it on mismatch, spawn it, and complete the MCP initialize exchange.
    let started = Instant::now();
    let handshake = state.client().await.map(|_| ());
    let mut ok = recorder.record("engine handshake", started, handshake);

    let engine = state.engine_state();
    let engine_version = engine
        .handshake
        .as_ref()
        .and_then(|value| value.get("identity"))
        .and_then(|identity| identity.get("engine_version"))
        .and_then(|version| version.as_str())
        .map(str::to_owned);

    let started = Instant::now();
    let identified = match (&engine_version, &engine.artifact_path) {
        (Some(_), Some(_)) => Ok(()),
        _ => Err(format!(
            "the engine did not identify itself: status {:?}, message {:?}",
            engine.status, engine.message
        )),
    };
    ok &= recorder.record("engine identity", started, identified);

    if let Some(project) = project {
        let started = Instant::now();
        let opened = state
            .open_project(&project.display().to_string())
            .await
            .map(|_| ());
        ok &= recorder.record("open project", started, opened);

        // Through the scheduler rather than a direct tool call: latest-wins scheduling and image
        // publication are the parts a packaged build can break on its own.
        let started = Instant::now();
        state.request_render();
        ok &= recorder.record("render preview", started, wait_for_render(&state).await);

        // Killing and replacing the engine is the documented recovery path; a packaged build that
        // cannot restart its sidecar looks fine until the first crash.
        let started = Instant::now();
        let restarted = state.restart().await.map(|_| ());
        ok &= recorder.record("engine restart", started, restarted);

        let started = Instant::now();
        state.request_render();
        ok &= recorder.record(
            "render after restart",
            started,
            wait_for_render(&state).await,
        );
    }

    state.shutdown();

    SelfCheckReport {
        ok,
        desktop_version: env!("CARGO_PKG_VERSION").to_owned(),
        target_triple: crate::TARGET_TRIPLE.to_owned(),
        engine_version,
        engine_artifact: engine.artifact_path,
        steps: recorder.steps,
    }
}

/// The arguments `--self-check` accepts, or `None` when the flag is absent and the workbench
/// should start normally.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct Arguments {
    pub project: Option<PathBuf>,
    pub report: Option<PathBuf>,
}

/// Parse a process argument list (without the executable name).
#[must_use]
pub fn parse_arguments(arguments: &[String]) -> Option<Arguments> {
    if !arguments.iter().any(|argument| argument == "--self-check") {
        return None;
    }
    let value_after = |flag: &str| -> Option<PathBuf> {
        arguments
            .iter()
            .position(|argument| argument == flag)
            .and_then(|index| arguments.get(index + 1))
            .filter(|value| !value.starts_with("--"))
            .map(PathBuf::from)
    };
    Some(Arguments {
        project: value_after("--project"),
        report: value_after("--report"),
    })
}

/// Entry point for `--self-check`: run the checks, write the report, return a process exit code.
#[must_use]
pub fn run(project: Option<PathBuf>, report_path: Option<PathBuf>) -> i32 {
    let settings_directory = std::env::temp_dir().join("arcavex-desktop-self-check");
    let _ = std::fs::remove_dir_all(&settings_directory);
    if let Err(error) = std::fs::create_dir_all(&settings_directory) {
        eprintln!("could not create a scratch settings directory: {error}");
        return 2;
    }

    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("could not start a runtime: {error}");
            return 2;
        }
    };

    let report = runtime.block_on(self_check(project.as_deref(), &settings_directory));
    let rendered = serde_json::to_string_pretty(&report).unwrap_or_else(|error| {
        format!("{{\"ok\":false,\"detail\":\"report could not be serialized: {error}\"}}")
    });

    println!("{rendered}");
    if let Some(path) = report_path {
        if let Err(error) = std::fs::write(&path, format!("{rendered}\n")) {
            eprintln!("could not write {}: {error}", path.display());
            return 2;
        }
    }

    i32::from(!report.ok)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    #[test]
    fn without_the_flag_the_workbench_starts_normally() {
        assert_eq!(parse_arguments(&args(&[])), None);
        // A file association or shell integration may pass a path; that is not a self-check.
        assert_eq!(parse_arguments(&args(&["C:/projects/poster"])), None);
    }

    #[test]
    fn the_flag_alone_checks_only_the_engine() {
        assert_eq!(
            parse_arguments(&args(&["--self-check"])),
            Some(Arguments::default())
        );
    }

    #[test]
    fn project_and_report_paths_are_read_from_their_flags() {
        let parsed = parse_arguments(&args(&[
            "--self-check",
            "--project",
            "C:/projects/poster",
            "--report",
            "C:/temp/report.json",
        ]))
        .expect("self-check requested");
        assert_eq!(parsed.project, Some(PathBuf::from("C:/projects/poster")));
        assert_eq!(parsed.report, Some(PathBuf::from("C:/temp/report.json")));
    }

    #[test]
    fn a_flag_missing_its_value_is_not_treated_as_a_path() {
        // Otherwise `--project --report x` would open a project literally named "--report".
        let parsed = parse_arguments(&args(&[
            "--self-check",
            "--project",
            "--report",
            "out.json",
        ]))
        .expect("self-check requested");
        assert_eq!(parsed.project, None);
        assert_eq!(parsed.report, Some(PathBuf::from("out.json")));
    }

    #[test]
    fn a_trailing_flag_without_a_value_is_ignored() {
        let parsed =
            parse_arguments(&args(&["--self-check", "--report"])).expect("self-check requested");
        assert_eq!(parsed.report, None);
    }
}
