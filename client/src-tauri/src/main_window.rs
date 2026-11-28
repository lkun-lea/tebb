//! The resident workbench owns one window; closing it preserves its webview.
use tauri::{AppHandle, Emitter, Manager, Runtime, WebviewWindow};

/// Windows uses ICON_BIG for the task switcher. Load the same shared group icon
/// as Explorer and the installer shortcut, at the system's preferred size.
#[cfg(windows)]
fn apply_taskbar_icon<R: Runtime>(window: &WebviewWindow<R>) {
    #[link(name = "kernel32")]
    extern "system" { fn GetModuleHandleW(name: *const u16) -> isize; }
    #[link(name = "user32")]
    extern "system" {
        fn LoadImageW(instance: isize, name: *const u16, kind: u32, width: i32, height: i32, flags: u32) -> isize;
        fn SendMessageW(hwnd: isize, message: u32, wparam: usize, lparam: isize) -> isize;
    }
    if let Ok(hwnd) = window.hwnd() {
        // Tauri's executable icon resource is 32512. LR_SHARED keeps ownership with Windows.
        unsafe {
            let module = GetModuleHandleW(std::ptr::null());
            let icon = LoadImageW(module, 32512usize as *const u16, 1, 0, 0, 0x8040);
            if icon != 0 { SendMessageW(hwnd.0 as isize, 0x0080, 1, icon); }
        }
    }
}

pub fn retain_on_close<R: Runtime>(window: &WebviewWindow<R>) {
    #[cfg(windows)]
    apply_taskbar_icon(window);
    let main = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            if let Err(error) = main.hide() {
                eprintln!("收起工作台失败：{error}");
            }
        }
    });
}

pub fn show<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("找不到主窗口。恢复：重启客户端。")?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn show_main(app: AppHandle) -> Result<(), String> {
    show(&app)
}

#[tauri::command]
pub fn open_today(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("找不到主窗口。恢复：重启客户端。")?;
    window
        .emit("open-today", true)
        .map_err(|error| error.to_string())
}
