// A Windows release build shows a WebView, not a console window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    arcavex_desktop_lib::run()
}
