//! Debounce, path normalization, and change attribution, driven by an explicit clock.

use std::path::Path;
use std::time::{Duration, Instant};

use arcavex_desktop_lib::projects::{
    is_ignored, relative_posix, ChangeActor, ChangeCoalescer, WatchedProject,
};

const DEBOUNCE: Duration = Duration::from_millis(120);

fn coalescer() -> ChangeCoalescer {
    ChangeCoalescer::new(DEBOUNCE)
}

#[test]
fn collapses_a_write_burst_into_one_change_set() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    // An editor's save is several events on the same file within a few milliseconds.
    coalescer.observe("data.yaml", start);
    coalescer.observe("data.yaml", start + Duration::from_millis(3));
    coalescer.observe("template.yaml", start + Duration::from_millis(9));

    assert!(coalescer.poll(start + Duration::from_millis(50)).is_none());

    let change = coalescer
        .poll(start + Duration::from_millis(200))
        .expect("the burst settled");
    assert_eq!(change.paths, vec!["data.yaml", "template.yaml"]);
}

#[test]
fn keeps_waiting_while_writes_keep_arriving() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    coalescer.observe("data.yaml", start);
    assert!(coalescer.poll(start + Duration::from_millis(100)).is_none());

    coalescer.observe("data.yaml", start + Duration::from_millis(110));
    assert!(coalescer.poll(start + Duration::from_millis(200)).is_none());

    assert!(coalescer.poll(start + Duration::from_millis(240)).is_some());
}

#[test]
fn reports_an_unannounced_write_as_an_external_edit() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    coalescer.observe("template.yaml", start);

    let change = coalescer.poll(start + DEBOUNCE).expect("settled");
    assert_eq!(change.actor, ChangeActor::External);
}

#[test]
fn does_not_call_its_own_write_an_external_edit() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    coalescer.announce("project.ui.yaml");
    coalescer.observe("project.ui.yaml", start);

    let change = coalescer.poll(start + DEBOUNCE).expect("settled");
    assert_eq!(change.actor, ChangeActor::Desktop);
    assert_eq!(change.paths, vec!["project.ui.yaml"]);
}

#[test]
fn one_external_write_makes_the_whole_burst_external() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    coalescer.announce("project.ui.yaml");
    coalescer.observe("project.ui.yaml", start);
    coalescer.observe("data.yaml", start + Duration::from_millis(5));

    let change = coalescer
        .poll(start + Duration::from_millis(200))
        .expect("settled");
    assert_eq!(change.actor, ChangeActor::External);
}

#[test]
fn an_announcement_is_consumed_by_one_event_only() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    coalescer.announce("project.ui.yaml");
    coalescer.observe("project.ui.yaml", start);
    let first = coalescer
        .poll(start + Duration::from_millis(200))
        .expect("first");
    assert_eq!(first.actor, ChangeActor::Desktop);

    // A later write to the same file is somebody else's.
    let later = start + Duration::from_secs(1);
    coalescer.observe("project.ui.yaml", later);
    let second = coalescer
        .poll(later + Duration::from_millis(200))
        .expect("second");
    assert_eq!(second.actor, ChangeActor::External);
}

#[test]
fn engine_output_and_queue_state_never_start_a_burst() {
    let mut coalescer = coalescer();
    let start = Instant::now();

    for path in [
        "outputs/poster-a3.png",
        ".arcavex/pending/9f2c.json",
        ".arcavex/cache/derived/a.bin",
        "data.yaml.tmp",
        ".git/index",
    ] {
        assert!(is_ignored(path), "{path}");
        coalescer.observe(path, start);
    }

    assert!(!coalescer.is_settling());
    assert!(coalescer.poll(start + Duration::from_secs(1)).is_none());
}

#[test]
fn normalizes_event_paths_to_project_relative_posix() {
    let root = Path::new("/projects/poster");

    assert_eq!(
        relative_posix(root, Path::new("/projects/poster/assets/logo.png")).as_deref(),
        Some("assets/logo.png"),
    );
    assert_eq!(relative_posix(root, Path::new("/projects/poster")), None);
    assert_eq!(
        relative_posix(root, Path::new("/projects/other/data.yaml")),
        None,
        "a path outside the project is never project source",
    );
}

#[test]
fn opening_a_project_canonicalizes_the_root_once() {
    let directory = std::env::temp_dir().join("arcavex-watcher-open");
    std::fs::create_dir_all(directory.join("assets")).expect("create");

    let project = WatchedProject::open(&directory).expect("open");

    assert_eq!(
        project
            .relative(&project.root().join("assets").join("logo.png"))
            .as_deref(),
        Some("assets/logo.png"),
    );
    std::fs::remove_dir_all(&directory).expect("cleanup");
}

#[tokio::test]
async fn publishes_a_real_filesystem_write_as_one_external_change() {
    let directory = std::env::temp_dir().join("arcavex-watcher-live");
    let _ = std::fs::remove_dir_all(&directory);
    std::fs::create_dir_all(&directory).expect("create");
    let project = WatchedProject::open(&directory).expect("open");

    let (sink, mut changes) = tokio::sync::mpsc::unbounded_channel();
    let _watcher = arcavex_desktop_lib::projects::ProjectWatcher::start(
        project,
        Duration::from_millis(80),
        sink,
    )
    .expect("watch");

    std::fs::write(directory.join("data.yaml"), "title: hello\n").expect("write");

    let change = tokio::time::timeout(Duration::from_secs(10), changes.recv())
        .await
        .expect("a filesystem event arrived")
        .expect("channel open");

    assert!(
        change.paths.iter().any(|path| path == "data.yaml"),
        "{change:?}"
    );
    assert_eq!(change.actor, ChangeActor::External);
    let _ = std::fs::remove_dir_all(&directory);
}
