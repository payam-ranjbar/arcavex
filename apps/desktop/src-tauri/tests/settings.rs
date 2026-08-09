//! Approved defaults, atomic writes, and what happens to a settings file that cannot be read.

use std::path::PathBuf;

use arcavex_desktop_lib::settings::{
    AutomationMode, ExtensionMode, LiveRenderMode, SettingsStore, MAX_RECENT_PROJECTS,
    SETTINGS_FILENAME,
};

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("arcavex-settings-{name}"));
    let _ = std::fs::remove_dir_all(&directory);
    std::fs::create_dir_all(&directory).expect("create scratch directory");
    directory
}

#[test]
fn a_first_launch_uses_the_approved_defaults() {
    let directory = scratch("defaults");

    let loaded = SettingsStore::load(&directory);

    let settings = loaded.store.get();
    assert!(loaded.diagnostic.is_none());
    assert_eq!(settings.automation, AutomationMode::Unrestricted);
    assert_eq!(settings.extensions, ExtensionMode::Unrestricted);
    assert_eq!(settings.live_render, LiveRenderMode::EveryChange);
    assert!(!settings.check_for_updates, "update checks are opt-in");
    assert_eq!(settings.theme_id, "arcavex-dark");
    assert!(settings.recent_projects.is_empty());
}

#[test]
fn a_saved_change_survives_a_reload() {
    let directory = scratch("roundtrip");
    let loaded = SettingsStore::load(&directory);

    loaded
        .store
        .update(|settings| {
            settings.live_render = LiveRenderMode::Manual;
            settings.theme_id = "arcavex-high-contrast".to_owned();
            settings.remember_project("/workspace/poster");
        })
        .expect("persist");

    let reloaded = SettingsStore::load(&directory).store.get();
    assert_eq!(reloaded.live_render, LiveRenderMode::Manual);
    assert_eq!(reloaded.theme_id, "arcavex-high-contrast");
    assert_eq!(reloaded.recent_projects, vec!["/workspace/poster"]);
}

#[test]
fn recents_are_most_recent_first_deduplicated_and_bounded() {
    let directory = scratch("recents");
    let loaded = SettingsStore::load(&directory);

    let settings = loaded
        .store
        .update(|settings| {
            for index in 0..MAX_RECENT_PROJECTS + 5 {
                settings.remember_project(&format!("/workspace/project-{index}"));
            }
            settings.remember_project("/workspace/project-3");
        })
        .expect("persist");

    assert_eq!(settings.recent_projects.len(), MAX_RECENT_PROJECTS);
    assert_eq!(settings.recent_projects[0], "/workspace/project-3");
    assert_eq!(
        settings
            .recent_projects
            .iter()
            .filter(|entry| *entry == "/workspace/project-3")
            .count(),
        1,
    );
}

#[test]
fn forgetting_a_project_removes_only_that_entry() {
    let directory = scratch("forget");
    let loaded = SettingsStore::load(&directory);

    let settings = loaded
        .store
        .update(|settings| {
            settings.remember_project("/workspace/a");
            settings.remember_project("/workspace/b");
            settings.forget_project("/workspace/a");
        })
        .expect("persist");

    assert_eq!(settings.recent_projects, vec!["/workspace/b"]);
}

#[test]
fn a_corrupt_file_falls_back_to_defaults_and_is_kept_for_repair() {
    let directory = scratch("corrupt");
    std::fs::write(directory.join(SETTINGS_FILENAME), "{ this is not json").expect("write");

    let loaded = SettingsStore::load(&directory);

    assert_eq!(loaded.store.get(), Default::default());
    let diagnostic = loaded.diagnostic.expect("the user is told why");
    assert!(diagnostic.contains("Defaults are in use"), "{diagnostic}");
    assert!(
        directory.join("settings.invalid.json").exists(),
        "the unreadable file is preserved rather than discarded",
    );
}

#[test]
fn an_unknown_field_does_not_discard_the_rest_of_the_file() {
    let directory = scratch("forward-compatible");
    std::fs::write(
        directory.join(SETTINGS_FILENAME),
        r#"{"themeId": "arcavex-light", "somethingFromALaterVersion": 42}"#,
    )
    .expect("write");

    let loaded = SettingsStore::load(&directory);

    assert!(loaded.diagnostic.is_none());
    assert_eq!(loaded.store.get().theme_id, "arcavex-light");
    assert_eq!(
        loaded.store.get().automation,
        AutomationMode::Unrestricted,
        "fields the file omits fall back to their defaults",
    );
}

#[test]
fn writing_leaves_no_temporary_file_behind() {
    let directory = scratch("atomic");
    let loaded = SettingsStore::load(&directory);

    loaded
        .store
        .update(|settings| settings.check_for_updates = true)
        .expect("first");
    loaded
        .store
        .update(|settings| settings.check_for_updates = false)
        .expect("second");

    let leftovers: Vec<_> = std::fs::read_dir(&directory)
        .expect("read")
        .filter_map(Result::ok)
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .filter(|name| name.ends_with(".tmp"))
        .collect();
    assert!(leftovers.is_empty(), "{leftovers:?}");
}
