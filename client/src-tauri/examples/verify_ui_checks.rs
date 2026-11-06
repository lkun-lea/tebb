//! Isolated UI host: real frontend and production side-browser commands, no backend startup.
use desk_companion_client_lib::side_browser;
fn main() {
    let args:Vec<String>=std::env::args().collect();
    let work=args.get(1).map(std::path::PathBuf::from).unwrap_or_else(||std::env::temp_dir().join(format!("tebb-ui-probe-{}",std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis())));
    assert!(work.is_absolute()&&!work.exists(),"验收目录必须是新的绝对路径");
    std::fs::create_dir_all(&work).unwrap();
    let base=tauri::Url::parse(args.get(2).map(String::as_str).unwrap_or("http://127.0.0.1:1432/")).unwrap();
    assert!(matches!(base.host_str(),Some("localhost"|"127.0.0.1"))&&base.scheme()=="http");
    let page=base.join("client.html?debug=work&ui-check=1").unwrap();
    let mut context=tauri::generate_context!();
    context.config_mut().identifier="cn.deskcompanion.verify290.ui".into();
    context.config_mut().build.dev_url=Some(base);
    context.config_mut().app.windows.clear();
    tauri::Builder::default().invoke_handler(tauri::generate_handler![side_browser::open_side_browser,side_browser::side_browser_layout,side_browser::side_browser_action]).setup(move|app|{
        tauri::WebviewWindowBuilder::new(app,"main",tauri::WebviewUrl::External(page))
            .title("tebb UI 验收 · 合成数据 · 检查入口").inner_size(1280.,900.)
            .data_directory(work.join("webview")).build()?;
        std::fs::write(work.join("host.json"),serde_json::to_vec_pretty(&serde_json::json!({
            "pid":std::process::id(),"backend_started":false,"synthetic_data":true,
            "side_browser":"production commands","identifier":"cn.deskcompanion.verify290.ui"
        })).unwrap())?;
        Ok(())
    }).build(context).unwrap().run(|app,event|{
        if let tauri::RunEvent::WindowEvent{label,event:tauri::WindowEvent::CloseRequested{..},..}=event {
            if label=="main" { app.exit(0); }
        }
    });
}
