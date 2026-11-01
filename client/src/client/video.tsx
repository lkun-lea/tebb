import { usePageActive } from "./page-stack";
import { useEffect, useRef, useState } from "react";
import { rpc, type BackendInfo } from "./api";
import { MdLink } from "./Markdown";
import { invoke } from "@tauri-apps/api/core";

type Settings = { proxy: string; cookie_file: string };
type WikiSettings = { wiki_url: string; video_parent_url: string; profile: string; auto_video_save: boolean };

export function WikiConnectionSettings({ info, debug = false, onSaved }: {
  info: BackendInfo | null; debug?: boolean; onSaved?: () => void;
}) {
  const [settings, setSettings] = useState<WikiSettings>({ wiki_url: "", video_parent_url: "", profile: "", auto_video_save: false });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setLoaded(false);
    if (!info || debug) return;
    let live = true;
    rpc<{ settings: WikiSettings }>(info, "load_wiki_connection").then(result => {
      if (!result.settings || typeof result.settings.auto_video_save !== "boolean") throw new Error("知识库连接设置未加载，请重启更新后的桌宠。");
      if (live) { setSettings(result.settings); setLoaded(true); }
    }).catch(err => { if (live) setMessage(String(err)); });
    return () => { live = false; };
  }, [info, debug]);
  async function save() {
    if (!info || debug || !loaded || busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await rpc<{ ok?: boolean; error?: string; settings: WikiSettings }>(info, "save_wiki_connection", { payload: settings });
      if (result.ok === false) throw new Error(result.error || "知识库连接失败。");
      setSettings(result.settings);
      setMessage(settings.wiki_url ? "知识库已连接。可在知识库页勾选云端文档加入本地检索。" : "已断开知识库连接。");
      onSaved?.();
    } catch (err) { setMessage(String(err)); }
    finally { setBusy(false); }
  }
  return <section aria-label="飞书知识库连接" className="mt-4 rounded-lg border border-border bg-card/70 p-4">
    <h2 className="text-sm font-medium">飞书知识库连接</h2>
    <p className="mt-2 text-sm text-muted-foreground">连接知识空间后，云端文档会列入可添加的知识来源。视频页、桌面对话和飞书私聊读取完成后，可自动归档到独立的视频父文档。</p>
    <div className="mt-3 space-y-3 text-sm">
      <label className="block">知识库页面链接<input aria-label="知识库页面链接" type="url" className="mt-1 block w-full rounded border border-border bg-background p-2"
        value={settings.wiki_url} disabled={!loaded || busy} placeholder="https://…feishu.cn/wiki/…"
        onChange={e => setSettings({ ...settings, wiki_url: e.target.value })} /></label>
      <label className="block">视频笔记父文档链接<input aria-label="视频笔记父文档链接" type="url" className="mt-1 block w-full rounded border border-border bg-background p-2"
        value={settings.video_parent_url} disabled={!loaded || busy} placeholder="同一知识库中用于管理视频笔记的父文档"
        onChange={e => setSettings({ ...settings, video_parent_url: e.target.value })} /></label>
      <label className="block">飞书应用配置名（可选）<input aria-label="飞书应用配置名" className="mt-1 block w-full rounded border border-border bg-background p-2"
        value={settings.profile} disabled={!loaded || busy} placeholder="留空使用当前登录的应用"
        onChange={e => setSettings({ ...settings, profile: e.target.value })} /></label>
      <label className="flex items-center gap-2"><input type="checkbox" aria-label="读取完成后自动保存视频笔记" checked={settings.auto_video_save}
        disabled={!loaded || busy} onChange={e => setSettings({ ...settings, auto_video_save: e.target.checked })} />读取完成后自动保存视频笔记</label>
      <p className="text-xs text-muted-foreground">原视频使用飞书内嵌网页；需要说明流程或概念关系时，笔记可包含飞书原生流程图。</p>
      <p className="text-xs text-muted-foreground">保存按钮会核实目标文档属于同一知识库。完整读取可用字幕后才自动保存；追问保留在会话中，可手动保存。本轮说“不要保存”会跳过归档。关闭开关影响之后提交的任务。</p>
      {settings.wiki_url && <MdLink href={settings.wiki_url}>打开知识库</MdLink>}
      <button className="rounded bg-secondary px-3 py-2 disabled:opacity-40" disabled={!loaded || busy || debug} onClick={() => void save()}>
        {busy ? "正在检查连接…" : "保存知识库连接"}</button>
      {message && <p role="status">{message}</p>}
    </div>
  </section>;
}

type LoginState = { platform: string; state: "missing" | "saved" | "expired" | "error"; saved_at?: number; error?: string };
export function VideoLogin({ info, debug = false, url = "" }: { info: BackendInfo | null; debug?: boolean; url?: string }) {
  const [items, setItems] = useState<LoginState[]>([]);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);
  const live = useRef(false);
  useEffect(() => {
    live.current = true;
    if (info && !debug) rpc<{ items: LoginState[] }>(info, "load_video_login").then(result => {
      if (live.current) { setItems(result.items); setLoaded(true); }
    }).catch(err => { if (live.current) setMessage(String(err)); });
    return () => { live.current = false; };
  }, [info, debug]);
  async function action(platform: string, kind: "open" | "view" | "save" | "clear") {
    if (!info || debug || busy || !loaded) return;
    setBusy(platform); setMessage("");
    try {
      if (kind === "open" || kind === "view") {
        const value = await rpc<{ settings: Settings }>(info, "load_video_settings");
        await invoke("open_video_login", { platform, url, proxy: value.settings.proxy, purpose: kind === "open" ? "login" : "video" });
        if (live.current) setMessage(kind === "open" ? "已打开官方登录页。B 站建议用手机 App 扫码登录；短信验证卡住时可再次点击「登录 / 扫码」重新打开页面，已有登录数据会保留。登录后保持窗口打开，返回点击「使用此登录态」。" : "已打开平台视频页面，沿用专用窗口登录态。");
      } else {
        let result: { items: LoginState[] };
        if (kind === "save") {
          const cookies = await invoke<unknown[]>("capture_video_login", { platform });
          result = await rpc(info, "save_video_login", { platform, cookies });
        } else {
          await invoke("clear_video_login_window", { platform });
          result = await rpc(info, "clear_video_login", { platform });
        }
        if (live.current) {
          setItems(result.items);
          setMessage(kind === "save" ? "登录态已加密保存在本机，视频页、桌面对话和飞书任务下次读取即可复用。可在原任务追问「重新获取这个视频」。" : "已清除该平台的读取登录态与专用窗口浏览数据。");
        }
      }
    } catch (err) { if (live.current) setMessage(String(err)); }
    finally { if (live.current) setBusy(""); }
  }
  return <section aria-label="视频平台登录" className="rounded-2xl border border-border bg-card/70 p-5">
    <h2 className="font-medium">平台登录与视频浏览</h2>
    <p className="mt-2 text-sm text-muted-foreground">先点击「登录 / 扫码」→ 在官方账号页登录 → 返回点击「使用此登录态」。再点击「查看视频」浏览原链接。专用窗口保持登录，重启后仍可使用。</p>
    <p className="mt-1 text-xs text-muted-foreground">B 站短信人机验证一直等待时，建议切换手机 App 扫码；也可再次点击「登录 / 扫码」重开官方页面，不需要清除登录数据。</p>
    <div className="mt-4 grid gap-3 md:grid-cols-2">{["Bilibili", "YouTube"].map(platform => {
      const item = items.find(row => row.platform === platform);
      const state = item?.state;
      return <div key={platform} className="rounded-lg border border-border p-4">
        <p className="text-sm font-medium">{platform} · {!loaded ? "读取状态中…" : state === "saved" ? "已保存登录态" : state === "expired" ? "登录态已过期" : state === "error" ? "登录态不可用" : "尚未保存登录态"}</p>
        {item?.saved_at && <p className="mt-1 text-xs text-muted-foreground">保存于 {new Date(item.saved_at * 1000).toLocaleString()}，有效性以平台读取结果为准。</p>}
        {item?.error && <p className="mt-1 text-sm text-destructive">{item.error}</p>}
        <div className="mt-3 flex flex-wrap gap-2">{([
          ["open", "登录 / 扫码"], ["view", "查看视频"], ["save", "使用此登录态"], ["clear", "清除登录态"],
        ] as const).map(([kind, title]) => <button key={kind} className="rounded bg-secondary px-3 py-2 text-sm disabled:opacity-40"
          disabled={!info || debug || !loaded || !!busy} onClick={() => void action(platform, kind)}>{title}</button>)}</div>
      </div>;
    })}</div>
    <p className="mt-3 text-xs text-muted-foreground">登录数据只供本机读取，不发送给模型或飞书。登录成功仍可能遇到平台限流；YouTube 若拒绝内嵌登录，可在下方配置自己导出的字幕登录文件。手动登录文件优先于此处保存的登录态。</p>
    {message && <p className="mt-3 text-sm" role="status">{message}</p>}
  </section>;
}
type Source = { source_id: string; title: string; author: string; url: string; platform: string;
  subtitle_notice: string; subtitle_language: string; segment_count: number; truncated: boolean;
  chapters: { title: string; start: number }[]; export_state?: string; document_url?: string; presentation_warnings?: string[] };

export function VideoSettings({ info, debug = false, expanded = false }: { info: BackendInfo | null; debug?: boolean; expanded?: boolean }) {
  const [settings, setSettings] = useState<Settings>({ proxy: "", cookie_file: "" });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!info || debug) return;
    let live = true;
    rpc<{ settings: Settings }>(info, "load_video_settings").then(value => {
      if (live) { setSettings(value.settings); setLoaded(true); }
    }).catch(err => { if (live) setMessage(String(err)); });
    return () => { live = false; };
  }, [info, debug]);
  async function save() {
    if (!info || !loaded || busy) return;
    setBusy(true); setMessage("");
    try {
      await rpc(info, "save_video_settings", settings);
      setMessage("视频设置已保存，下次读取视频时生效。");
    } catch (err) { setMessage(String(err)); }
    finally { setBusy(false); }
  }
  return <details open={expanded || undefined} className="mt-4 rounded-lg border border-border bg-card/70 p-4">
    <summary className="cursor-pointer text-sm">视频读取设置</summary>
    <p className="mt-2 text-sm text-muted-foreground">也可在桌面对话或飞书私聊发送 Bilibili / YouTube 链接。只读取信息和字幕；没有字幕会明确提示。</p>
    <div className="mt-3 space-y-3 text-sm">
      <label className="block">网络代理（可选）<input className="mt-1 block w-full rounded border border-border bg-background p-2" value={settings.proxy}
        disabled={!loaded || busy} placeholder="例如 http://127.0.0.1:7890；留空沿用系统网络"
        onChange={e => setSettings({ ...settings, proxy: e.target.value })} /></label>
      <label className="block">字幕登录文件（可选）<input className="mt-1 block w-full rounded border border-border bg-background p-2" value={settings.cookie_file}
        disabled={!loaded || busy} placeholder="自己导出的 Netscape 格式 cookies.txt 的完整路径"
        onChange={e => setSettings({ ...settings, cookie_file: e.target.value })} /></label>
      <p className="text-xs text-muted-foreground">Bilibili 部分字幕需要登录。登录文件只供本机读取，不上传到飞书；tebb 不会自动读取浏览器登录信息。更改设置后，可在追问中说“重新获取这个视频”。</p>
      <button className="rounded bg-secondary px-3 py-2 disabled:opacity-40" disabled={!loaded || busy || debug} onClick={() => void save()}>保存视频设置</button>
      {message && <p role="status">{message}</p>}
    </div>
  </details>;
}

export function TaskVideos({ info, taskId, state }: { info: BackendInfo | null; taskId: string; state: string }) {
  const activeTask = useRef(taskId);
  activeTask.current = taskId;
  const pageActive = usePageActive();
  const [items, setItems] = useState<Source[]>([]);
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [absent, setAbsent] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (!pageActive || !info || !taskId) return;
    let live = true;
    let pending = false;
    setItems([]); setSaved({}); setError(""); setAbsent({});
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await rpc<{ items: Source[] }>(info, "list_task_videos", { task_id: taskId });
        if (live) setItems(value.items);
      } catch (err) { if (live) setError(String(err)); }
      finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => { live = false; window.clearInterval(timer); };
  }, [pageActive, info, taskId, state]);
  async function save(source: Source) {
    if (!info || busy) return;
    setBusy(source.source_id); setError("");
    try {
      const args: Record<string, unknown> = { task_id: taskId, source_id: source.source_id };
      if (source.export_state === "pending" && absent[source.source_id]) args.confirmed_absent = true;
      const result = await rpc<{ url: string }>(info, "export_task_video", args);
      if (activeTask.current === taskId) setSaved(previous => ({ ...previous, [source.source_id]: result.url }));
    } catch (err) { if (activeTask.current === taskId) setError(String(err)); }
    finally { setBusy(""); }
  }
  if (!items.length && !error) return null;
  return <section aria-label="本会话视频来源" className="rounded-lg border border-border p-3 text-sm">
    <h3>本会话视频来源</h3>
    <p className="mt-1 text-xs text-muted-foreground">可在下方继续追问。保存会将当前任务答案与所选原视频一起写入飞书文档。</p>
    {items.map(source => <div key={source.source_id} className="mt-3 rounded bg-secondary/50 p-3">
      <MdLink href={source.url}>{source.title}</MdLink>
      <p className="mt-1 text-muted-foreground">{source.platform} · {source.author || "作者未知"}</p>
      <p className="mt-1">{source.subtitle_notice} {source.segment_count > 0 && `${source.segment_count} 段 · ${source.subtitle_language}`}</p>
      {source.export_state === "pending" && !saved[source.source_id] && <label className="mt-2 block text-primary">
        上次保存结果未确认，请先检查飞书云空间。
        <span className="mt-1 block"><input type="checkbox" checked={!!absent[source.source_id]}
          onChange={e => setAbsent({ ...absent, [source.source_id]: e.target.checked })} /> 我已核实没有生成文档，允许重新保存</span>
      </label>}
      {source.chapters.length > 0 && <details className="mt-2"><summary>平台章节（{source.chapters.length}）</summary>
        <ul className="mt-2 space-y-1">{source.chapters.map((chapter, i) => <li key={i}>{Math.floor(chapter.start / 60)}:{String(Math.floor(chapter.start % 60)).padStart(2, "0")} · {chapter.title}</li>)}</ul>
      </details>}
      <button className="mt-2 rounded bg-secondary px-3 py-2 disabled:opacity-40" disabled={!!busy || state !== "succeeded" || source.export_state === "saved" || !!saved[source.source_id] || (source.export_state === "pending" && !absent[source.source_id])}
        onClick={() => void save(source)}>{busy === source.source_id ? "正在保存…" : source.export_state === "saved" || saved[source.source_id] ? "已保存到飞书" : "保存当前答案到飞书文档"}</button>
      {(saved[source.source_id] || source.document_url) && <MdLink href={saved[source.source_id] || source.document_url}>打开视频笔记</MdLink>}
      {source.presentation_warnings?.length ? <p className="mt-1 text-xs text-muted-foreground">{source.presentation_warnings.join("；")}</p> : null}
    </div>)}
    {error && <p className="mt-2 text-destructive" role="alert">{error}</p>}
  </section>;
}
