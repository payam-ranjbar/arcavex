//! Latest-wins scheduling: what the user sees while renders race each other.

use std::collections::BTreeMap;

use arcavex_desktop_lib::rendering::{
    Completion, RenderJob, RenderKey, RenderOutput, RenderScheduler, RenderState,
};
use serde_json::json;

fn key(revision: &str) -> RenderKey {
    RenderKey {
        render_revision: revision.to_owned(),
        format: Some("poster-a3".to_owned()),
        locale: Some("en-US".to_owned()),
        options: BTreeMap::new(),
    }
}

fn output(job: &RenderJob) -> RenderOutput {
    RenderOutput {
        key: job.key.clone(),
        image_url: format!("arcavex://render/{}.png", job.id),
        width_px: 1684,
        height_px: 2382,
        content_sha256: None,
        compile_ms: Some(10),
        render_ms: Some(80),
    }
}

#[test]
fn starts_the_first_request_immediately() {
    let mut scheduler = RenderScheduler::new();

    let job = scheduler.request(key("r1")).expect("a job to run");

    assert_eq!(job.key, key("r1"));
    assert_eq!(scheduler.status().state, RenderState::Rendering);
}

#[test]
fn keeps_only_the_newest_queued_job_while_one_is_running() {
    let mut scheduler = RenderScheduler::new();
    let running = scheduler.request(key("r1")).expect("first job");

    assert!(
        scheduler.request(key("r2")).is_none(),
        "one job runs at a time"
    );
    assert!(scheduler.request(key("r3")).is_none());

    let (completion, next) = scheduler.complete(&running, Ok(output(&running)));

    // r1 finished for a revision the user has already moved past, so it is not shown.
    assert_eq!(completion, Completion::Discarded);
    // r2 was superseded before it ever ran; only the newest queued job survives.
    assert_eq!(next.expect("queued job").key, key("r3"));
}

#[test]
fn discards_a_result_whose_revision_is_no_longer_wanted() {
    let mut scheduler = RenderScheduler::new();
    let stale = scheduler.request(key("r1")).expect("first job");
    scheduler.request(key("r2"));

    let (completion, next) = scheduler.complete(&stale, Ok(output(&stale)));

    assert_eq!(completion, Completion::Discarded);
    assert_eq!(next.expect("queued job").key, key("r2"));
    assert!(
        scheduler.status().last_good.is_none(),
        "a result nobody wants must never be published",
    );
}

#[test]
fn keeps_the_last_good_picture_when_a_render_fails() {
    let mut scheduler = RenderScheduler::new();
    let good = scheduler.request(key("r1")).expect("first job");
    let published = output(&good);
    scheduler.complete(&good, Ok(published.clone()));

    let failing = scheduler.request(key("r2")).expect("second job");
    let (completion, _) = scheduler.complete(
        &failing,
        Err(vec![
            json!({"code": "ARC-TPL-001", "message": "unknown key"}),
        ]),
    );

    assert_eq!(completion, Completion::Failed);
    let status = scheduler.status();
    assert_eq!(status.state, RenderState::Failed);
    assert_eq!(
        status.last_good,
        Some(published),
        "the last good picture stays visible"
    );
    assert_eq!(status.diagnostics.len(), 1);
}

#[test]
fn a_later_success_clears_the_diagnostics_of_an_earlier_failure() {
    let mut scheduler = RenderScheduler::new();
    let failing = scheduler.request(key("r1")).expect("first job");
    scheduler.complete(&failing, Err(vec![json!({"code": "ARC-TPL-001"})]));

    let fixed = scheduler.request(key("r2")).expect("second job");
    scheduler.complete(&fixed, Ok(output(&fixed)));

    let status = scheduler.status();
    assert_eq!(status.state, RenderState::Current);
    assert!(status.diagnostics.is_empty());
}

#[test]
fn changing_the_active_target_marks_the_picture_stale_without_losing_it() {
    let mut scheduler = RenderScheduler::new();
    let job = scheduler.request(key("r1")).expect("job");
    let published = output(&job);
    scheduler.complete(&job, Ok(published.clone()));

    scheduler.target_changed();

    let status = scheduler.status();
    assert_eq!(status.state, RenderState::Stale);
    assert_eq!(status.last_good, Some(published));
}

#[test]
fn a_job_completing_after_the_target_changed_is_not_published() {
    let mut scheduler = RenderScheduler::new();
    let inflight = scheduler.request(key("r1")).expect("job");

    scheduler.target_changed();
    let (completion, next) = scheduler.complete(&inflight, Ok(output(&inflight)));

    assert_eq!(completion, Completion::Discarded);
    assert!(next.is_none());
    assert!(scheduler.status().last_good.is_none());
}

#[test]
fn a_sidecar_restart_retries_the_newest_request_and_keeps_the_picture() {
    let mut scheduler = RenderScheduler::new();
    let first = scheduler.request(key("r1")).expect("job");
    let published = output(&first);
    scheduler.complete(&first, Ok(published.clone()));
    let lost = scheduler.request(key("r2")).expect("job");

    scheduler.engine_restarted();

    assert_eq!(scheduler.status().state, RenderState::Stale);
    assert_eq!(scheduler.status().last_good, Some(published));

    let resumed = scheduler.resume().expect("the newest request is retried");
    assert_eq!(resumed.key, key("r2"));
    assert_ne!(resumed.id, lost.id, "the lost job cannot complete twice");

    let (completion, _) = scheduler.complete(&lost, Ok(output(&lost)));
    assert_eq!(
        completion,
        Completion::Discarded,
        "a result from the process that died must never be published",
    );
}

#[test]
fn resuming_without_a_pending_request_starts_nothing() {
    let mut scheduler = RenderScheduler::new();

    assert!(scheduler.resume().is_none());
    assert_eq!(scheduler.status().state, RenderState::Idle);
}
