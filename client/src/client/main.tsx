import { createRoot } from "react-dom/client";
import { lazy, Suspense } from "react";
import { RenderBoundary, renderDiagnostics } from './render-boundary';
import {AccountBootstrap} from './account-bootstrap';
import "reend-components/styles.css";
import "./index.css";
import "./chat-prototype.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("缺少 #root。恢复：检查 client.html");
}
const ChatPreview = lazy(() => import("./chat-prototype").then(module => ({ default: module.ChatPrototype })));
const LiveCollaboration = lazy(() => import("./live-collaboration").then(module => ({ default: module.LiveCollaboration })));
const App = lazy(() => import("./App").then(module => ({ default: module.App })));
const ChatMotionDebug = import.meta.env.DEV ? lazy(() => import('./ui-chat-debug').then(module=>({default:module.ChatMotionDebug}))) : null;
const motionPreview = !!ChatMotionDebug && new URLSearchParams(window.location.search).get('preview') === 'motion';
const UiCheckTools = import.meta.env.DEV ? lazy(() => import('./ui-check-tools').then(module=>({default:module.UiCheckTools}))) : null;
const uiCheckParams = new URLSearchParams(window.location.search);
const uiCheck = !!UiCheckTools && (uiCheckParams.get('ui-check') === '1' || uiCheckParams.get('debug') === 'work');
const preview = new URLSearchParams(window.location.search).get("preview") === "chat";
// The standalone preview never mounts App: no backend startup, credentials, or real chat requests.
const live = preview && new URLSearchParams(window.location.search).get("live") === "1";
Object.defineProperty(window, '__DESK_UI_DIAGNOSTICS__', { value: renderDiagnostics, configurable: true });
createRoot(root).render(<RenderBoundary><Suspense fallback={<p>正在载入界面…</p>}>{motionPreview && ChatMotionDebug ? <ChatMotionDebug/> : live ? <LiveCollaboration standalone /> : preview ? <ChatPreview standalone /> : <AccountBootstrap><App /></AccountBootstrap>}</Suspense>{uiCheck&&UiCheckTools&&<Suspense fallback={null}><UiCheckTools/></Suspense>}</RenderBoundary>);
