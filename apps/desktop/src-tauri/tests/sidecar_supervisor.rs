//! Supervision behaviour: what the desktop does when the engine is wrong, slow, or gone.

#[path = "fake_mcp.rs"]
mod fake_mcp;

use std::path::PathBuf;
use std::time::Duration;

use arcavex_desktop_lib::engine::{
    EngineSpec, EngineStatus, StartupError, Supervisor, CRASH_LOOP_THRESHOLD,
};
use fake_mcp::{FakeEngineScript, FakeLauncher};

fn spec() -> EngineSpec {
    EngineSpec {
        program: PathBuf::from("fake-engine"),
        args: vec!["mcp".to_owned(), "serve".to_owned()],
        expected_sha256: None,
        expected_mcp_contract: "2025-06-18".to_owned(),
        accepted_ir_versions: vec!["1.0".to_owned()],
        call_timeout: Duration::from_millis(500),
    }
}

#[tokio::test]
async fn reaches_ready_only_after_a_compatible_handshake() {
    let supervisor = Supervisor::new(FakeLauncher::new(FakeEngineScript::default()), spec());

    let client = supervisor.start().await.expect("engine started");

    assert_eq!(supervisor.state().status, EngineStatus::Ready);
    let handshake = supervisor.state().handshake.expect("handshake retained");
    assert_eq!(handshake["mcp_contract_version"], "2025-06-18");
    assert!(client
        .call(
            "tools/call",
            serde_json::json!({"name": "project_snapshot"})
        )
        .await
        .is_ok());
}

#[tokio::test]
async fn enters_diagnostic_mode_instead_of_using_an_incompatible_engine() {
    let supervisor = Supervisor::new(
        FakeLauncher::new(FakeEngineScript {
            mcp_contract_version: "2024-11-05".to_owned(),
            ..FakeEngineScript::default()
        }),
        spec(),
    );

    let error = supervisor.start().await.expect_err("incompatible engine");

    assert!(matches!(error, StartupError::Incompatible { .. }));
    assert_eq!(supervisor.state().status, EngineStatus::Incompatible);
    assert!(supervisor
        .state()
        .message
        .expect("reason")
        .contains("2024-11-05"));
}

#[tokio::test]
async fn does_not_retry_an_engine_whose_versions_cannot_change() {
    let launcher = FakeLauncher::new(FakeEngineScript {
        produced_ir_version: "9.0".to_owned(),
        ..FakeEngineScript::default()
    });
    let supervisor = Supervisor::new(launcher, spec());

    supervisor.start().await.expect_err("incompatible engine");

    assert_eq!(supervisor.state().restart_count, 1);
}

#[tokio::test]
async fn refuses_an_artifact_whose_hash_is_not_the_pinned_one() {
    let program = std::env::temp_dir().join("arcavex-supervisor-artifact.bin");
    std::fs::write(&program, b"not the pinned build").expect("write artifact");
    let supervisor = Supervisor::new(
        FakeLauncher::new(FakeEngineScript::default()),
        EngineSpec {
            program: program.clone(),
            expected_sha256: Some("00".repeat(32)),
            ..spec()
        },
    );

    let error = supervisor.start().await.expect_err("hash mismatch");

    assert!(matches!(error, StartupError::ArtifactMismatch { .. }));
    assert_eq!(supervisor.state().status, EngineStatus::Incompatible);
    std::fs::remove_file(&program).expect("cleanup");
}

#[tokio::test]
async fn retries_a_failed_launch_and_succeeds_once_the_engine_appears() {
    let launcher = FakeLauncher::new(FakeEngineScript {
        failed_launches: 1,
        ..FakeEngineScript::default()
    });
    let supervisor = Supervisor::new(launcher, spec());

    supervisor.start().await.expect("second attempt succeeded");

    assert_eq!(supervisor.state().status, EngineStatus::Ready);
    assert_eq!(supervisor.state().restart_count, 1);
}

#[tokio::test]
async fn stops_restarting_after_a_crash_loop_and_says_why() {
    let launcher = FakeLauncher::new(FakeEngineScript {
        failed_launches: 100,
        ..FakeEngineScript::default()
    });
    let supervisor = Supervisor::new(launcher, spec());

    let error = supervisor.start().await.expect_err("crash loop");

    assert!(matches!(
        error,
        StartupError::CrashLoop { attempts } if attempts == CRASH_LOOP_THRESHOLD
    ));
    assert_eq!(supervisor.state().status, EngineStatus::Failed);
    assert!(supervisor
        .state()
        .message
        .expect("reason")
        .contains("Extensions"));
}

#[tokio::test]
async fn gives_up_on_an_engine_that_never_answers_the_handshake() {
    let supervisor = Supervisor::new(
        FakeLauncher::new(FakeEngineScript {
            silent: true,
            ..FakeEngineScript::default()
        }),
        EngineSpec {
            call_timeout: Duration::from_millis(30),
            ..spec()
        },
    );

    let error = supervisor.start().await.expect_err("handshake timed out");

    assert!(matches!(error, StartupError::CrashLoop { .. }));
    assert_eq!(supervisor.state().status, EngineStatus::Failed);
}

#[tokio::test]
async fn reports_a_transport_that_closes_mid_handshake() {
    let supervisor = Supervisor::new(
        FakeLauncher::new(FakeEngineScript {
            close_after_requests: Some(1),
            ..FakeEngineScript::default()
        }),
        spec(),
    );

    let error = supervisor.start().await.expect_err("engine exited");

    assert!(matches!(error, StartupError::CrashLoop { .. }));
}

#[tokio::test]
async fn keeps_engine_stderr_for_the_diagnostics_panel() {
    let supervisor = Supervisor::new(
        FakeLauncher::new(FakeEngineScript {
            stderr_lines: vec![
                "ARC-EXT-004 extension failed to load".to_owned(),
                "falling back to built-ins".to_owned(),
            ],
            ..FakeEngineScript::default()
        }),
        spec(),
    );

    supervisor.start().await.expect("engine started");
    tokio::time::sleep(Duration::from_millis(50)).await;

    let tail = supervisor.stderr_tail();
    assert_eq!(
        tail.first().map(String::as_str),
        Some("ARC-EXT-004 extension failed to load")
    );
    assert_eq!(tail.len(), 2);
}

#[tokio::test]
async fn ends_the_previous_process_before_running_another() {
    let launcher = FakeLauncher::new(FakeEngineScript::default());
    let counters = launcher.counters();
    let supervisor = Supervisor::new(launcher, spec());

    supervisor.start().await.expect("first engine");
    supervisor.start().await.expect("second engine");
    assert_eq!(counters.launches(), 2);
    assert_eq!(counters.terminations(), 1, "the replaced process was ended");

    supervisor.shutdown();

    assert_eq!(
        counters.terminations(),
        2,
        "shutdown ended the live process"
    );
}
