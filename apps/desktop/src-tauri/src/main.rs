// A Windows release build shows a WebView, not a console window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use arcavex_desktop_lib::selfcheck;

/// `--self-check [--project <path>] [--report <path>]` drives the installation headlessly and
/// exits; anything else starts the workbench.
fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match selfcheck::parse_arguments(&arguments) {
        Some(request) => std::process::exit(selfcheck::run(request.project, request.report)),
        None => arcavex_desktop_lib::run(),
    }
}
