use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};



#[derive(Clone, Default, serde::Serialize)]
pub struct SettingsTarget {
    pub section: Option<String>,
    pub profile: Option<String>,
    pub trace: Option<String>,
    pub service: Option<String>,
}

pub struct PendingSettingsTarget(pub Mutex<Option<SettingsTarget>>);

#[tauri::command]
pub async fn open_settings_window(app: AppHandle, section: Option<String>, profile: Option<String>, trace: Option<String>, service: Option<String>) -> Result<(), String> {
    let target = SettingsTarget { section, profile, trace, service };
    let state = app.state::<PendingSettingsTarget>();
    *state.0.lock().map_err(|e|e.to_string())? = Some(target);
    crate::main_window::show(&app)?;
    app.emit_to("main", "settings-requested", ()).map_err(|e|e.to_string())

}

#[tauri::command]
pub fn take_settings_target(app: AppHandle) -> Result<Option<SettingsTarget>, String> {
    let state = app.state::<PendingSettingsTarget>();
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    Ok(guard.take())
}

// 背景截取需要主窗口的纵横比，保证截取结果与主窗口所见一致。
#[tauri::command]
pub fn main_window_inner_size(app: AppHandle) -> Result<serde_json::Value, String> {
    let window = app.get_webview_window("main").ok_or("找不到主窗口。恢复：重启客户端。")?;
    let size = window.inner_size().map_err(|e| e.to_string())?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    Ok(serde_json::json!({ "width": size.width as f64 / scale, "height": size.height as f64 / scale }))
}
