//! 独立设置窗口：承载 settings.html，按需创建或唤起并定位到目标分类。
//! 本地凭证窗口不得导航到远程内容（与 pet-chat 相同的白名单约束）。
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

const LABEL: &str = "settings";

#[derive(Clone, Default, serde::Serialize)]
pub struct SettingsTarget {
    pub section: Option<String>,
    pub profile: Option<String>,
}

pub struct PendingSettingsTarget(pub Mutex<Option<SettingsTarget>>);

#[tauri::command]
pub async fn open_settings_window(app: AppHandle, section: Option<String>, profile: Option<String>) -> Result<(), String> {
    let target = SettingsTarget { section, profile };
    if let Some(existing) = app.get_webview_window(LABEL) {
        existing.show().map_err(|e| e.to_string())?;
        existing.set_focus().map_err(|e| e.to_string())?;
        // 已打开的窗口监听器就绪，直接推送目标分类。
        existing.emit("settings-section", &target).map_err(|e| e.to_string())?;
        return Ok(());
    }
    // 新窗口尚未注册监听：暂存目标，设置页挂载后主动来取，避免事件竞态。
    if let Some(state) = app.try_state::<PendingSettingsTarget>() {
        if let Ok(mut guard) = state.0.lock() { *guard = Some(target); }
    }
    let dev_url = app.config().build.dev_url.clone();
    let window = WebviewWindowBuilder::new(&app, LABEL, WebviewUrl::App("settings.html".into()))
        .title("tebb 设置").inner_size(960., 680.).min_inner_size(720., 540.)
        .decorations(false)
        .visible(true)
        .on_navigation(move |url| url.path() == "/settings.html" && (
            (url.scheme() == "tauri" && url.host_str() == Some("localhost")) ||
            (url.scheme() == "http" && url.host_str() == Some("tauri.localhost") && url.port_or_known_default() == Some(80)) ||
            dev_url.as_ref().is_some_and(|dev| dev.scheme() == url.scheme() && dev.host_str() == url.host_str() && dev.port_or_known_default() == url.port_or_known_default())
        ))
        .build().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn take_settings_target(app: AppHandle) -> Result<SettingsTarget, String> {
    let state = app.state::<PendingSettingsTarget>();
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    Ok(guard.take().unwrap_or_default())
}

// 背景截取需要主窗口的纵横比，保证截取结果与主窗口所见一致。
#[tauri::command]
pub fn main_window_inner_size(app: AppHandle) -> Result<serde_json::Value, String> {
    let window = app.get_webview_window("main").ok_or("找不到主窗口。恢复：重启客户端。")?;
    let size = window.inner_size().map_err(|e| e.to_string())?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    Ok(serde_json::json!({ "width": size.width as f64 / scale, "height": size.height as f64 / scale }))
}
