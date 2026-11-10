import { createRoot } from "react-dom/client";
import { lazy, Suspense } from "react";
import { RenderBoundary, renderDiagnostics } from './render-boundary';
import { AccountBootstrap } from './account-bootstrap';
import "reend-components/styles.css";
import "./index.css";
import "./chat-prototype.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("缺少 #root。恢复：检查 settings.html");
}
const SettingsApp = lazy(() => import("./settings-app").then(module => ({ default: module.SettingsApp })));
// 独立设置窗口：与主窗口共用同一本地后端，自身管理模型/人设/连接与外观状态。
Object.defineProperty(window, '__DESK_UI_DIAGNOSTICS__', { value: renderDiagnostics, configurable: true });
createRoot(root).render(<RenderBoundary><Suspense fallback={<p className="p-6">正在载入设置…</p>}><AccountBootstrap><SettingsApp /></AccountBootstrap></Suspense></RenderBoundary>);
