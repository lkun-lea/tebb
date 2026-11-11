import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Copy, Minus, Square, X } from "lucide-react";
import "./window-chrome.css";

// 主窗自绘标题栏：背景、文字、边框和窗口按钮全部跟随当前主题变量。
export function WindowTitleBar() {
  const tauri = isTauri();
  const [maximized, setMaximized] = useState(false);

  // 最大化状态由窗口尺寸事件同步，保证按钮图标与真实窗口一致。
  useEffect(() => {
    if (!tauri) return;
    const appWindow = getCurrentWindow();
    let active = true;
    const sync = () => {
      void appWindow.isMaximized().then((value) => { if (active) setMaximized(value); }).catch(() => {});
    };
    sync();
    const unlisten = appWindow.onResized(sync);
    return () => {
      active = false;
      void unlisten.then((stop) => stop()).catch(() => {});
    };
  }, [tauri]);

  return (
    <header className="tebb-window-titlebar" data-tauri-drag-region>
      <span className="tebb-window-title" data-tauri-drag-region>tebb</span>
      {tauri ? (
        <div className="tebb-window-controls">
          <button type="button" aria-label="最小化窗口" title="最小化" onClick={() => void getCurrentWindow().minimize().catch(() => {})}>
            <Minus size={14} aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label={maximized ? "还原窗口" : "最大化窗口"}
            title={maximized ? "还原" : "最大化"}
            onClick={() => void getCurrentWindow().toggleMaximize().catch(() => {})}
          >
            {maximized ? <Copy size={12} aria-hidden="true" /> : <Square size={12} aria-hidden="true" />}
          </button>
          <button type="button" className="tebb-window-control-close" aria-label="关闭窗口" title="关闭" onClick={() => void getCurrentWindow().close().catch(() => {})}>
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </header>
  );
}

// 设置窗不渲染标题栏，只保留右上角关闭按钮。
export function WindowCloseButton() {
  if (!isTauri()) return null;
  return (
    <button type="button" className="tebb-window-close-floating" aria-label="关闭窗口" title="关闭" onClick={() => void getCurrentWindow().close().catch(() => {})}>
      <X size={14} aria-hidden="true" />
    </button>
  );
}
