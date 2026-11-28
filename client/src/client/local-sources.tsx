import { useEffect, useRef, useState } from "react";
import { rpc, type BackendInfo } from "./api";
import { LoadingText } from "./loading-text";

export type LocalSource = { id: string; noteKey?:string; note_title?:string; kind: "file" | "folder"; name: string; path: string; relative?: string;
  chars: number; lines?: number; files?: LocalSource[]; skipped?: number; errors?: { name: string; error: string }[] };
type Result = { ok: boolean; sources: LocalSource[]; errors: { name: string; error: string }[]; error?: string };

export function LocalSourcesDialog({ info, initialKind, debug, onClose, onAttach, onIndex, onPreview, onMinimizedChange }: {
  info: BackendInfo | null; initialKind: "file" | "folder"; debug?: boolean;
  onClose: () => void; onAttach: (sources: LocalSource[]) => void;
  onIndex: (source: LocalSource) => Promise<{ ok: boolean; error: string }>;
  onPreview?: (source: LocalSource) => void;
  onMinimizedChange?: (minimized: boolean) => void;
}) {
  const [sources, setSources] = useState<LocalSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [issues, setIssues] = useState<Result["errors"]>([]);
  const [path, setPath] = useState("");
  const [kind, setKind] = useState(initialKind);
  const [preview, setPreview] = useState<{ id: string; name: string; text: string; next_offset: number | null; chars: number } | null>(null);
  const [minimized, setMinimized] = useState(false);
  useEffect(() => { onMinimizedChange?.(minimized); }, [minimized, onMinimizedChange]);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const alive = useRef(true);
  const serial = useRef(0);
  const request = useRef<{ info: BackendInfo; id: string } | null>(null);
  const activity = useRef("selection");
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    if (typeof window === "undefined" || !window.addEventListener) return;
    function keepVisible() {
      const box = dialog.current?.getBoundingClientRect();
      if (!box) return;
      setPosition(p => p ? { x: Math.max(8, Math.min(window.innerWidth - box.width - 8, p.x)),
        y: Math.max(44, Math.min(window.innerHeight - box.height - 8, p.y)) } : null);
    }
    keepVisible(); window.addEventListener("resize", keepVisible);
    return () => window.removeEventListener("resize", keepVisible);
  }, [minimized]);
  function cancelRequest() {
    const pending = request.current; request.current = null;
    if (pending) void rpc(pending.info, "cancel_local_source_request", { request_id: pending.id }).catch(() => {});
  }
  function stop() {
    serial.current++; cancelRequest(); setBusy(false);
    setNote(activity.current === "index" ? "已停止等待；正在入库的单个文件会完成，其余文件不再继续。" : "已取消本次资料选择或读取。");
  }
  function close() { alive.current = false; serial.current++; cancelRequest(); onClose(); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; serial.current++; cancelRequest(); }; }, []);
  const all = sources.flatMap(s => s.kind === "folder" ? [s, ...(s.files || [])] : [s]);
  const chosen = all.filter(s => selected.includes(s.id));
  async function choose(nextKind: "file" | "folder", manual = false) {
    if (busy) return;
    if (!info || debug) { setError(debug ? "调试页不读取本地文件。" : "本地后端尚未连接。"); return; }
    setBusy(true); setError(""); setKind(nextKind); setNote("");
    const operation = ++serial.current;
    activity.current = "selection";
    const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)), v => v.toString(16).padStart(2, "0")).join("");
    request.current = { info, id: requestId };
    try {
      const value = await rpc<Result>(info, manual ? "stage_local_sources" : "pick_local_sources",
        manual ? { kind: nextKind, request_id: requestId, paths: path.split(/\r?\n/).map(p => p.trim().replace(/^"|"$/g, "")).filter(Boolean) } : { kind: nextKind, request_id: requestId });
      if (!alive.current || operation !== serial.current) return;
      if (!value.ok) throw new Error(value.error || "资料未能读取。");
      if (value.sources?.length) {
        setSources(value.sources); setSelected(value.sources.filter(s => s.kind === "file" || s.files?.length).map(s => s.id)); setPreview(null);
      } else if (value.errors?.length) {
        setSources([]); setSelected([]); setPreview(null);
      }
      setIssues(value.errors || []);
    } catch (err) { if (alive.current && operation === serial.current) setError(String(err)); }
    finally { if (alive.current && operation === serial.current) { request.current = null; setBusy(false); } }
  }
  function check(source: LocalSource, enabled: boolean) {
    setSelected(ids => enabled ? [...new Set([...ids.filter(id => source.kind === "file" ? !sources.some(s => s.kind === "folder" && s.id === id && s.files?.some(f => f.id === source.id)) : !(source.files || []).some(f => f.id === id)), source.id])] : ids.filter(id => id !== source.id));
  }
  async function show(source: LocalSource, more = false) {
    if (!more && onPreview) { onPreview(source); setMinimized(true); return; }
    if (!info || busy) return;
    setBusy(true); setError("");
    const operation = ++serial.current;
    activity.current = "preview";
    try {
      const result = await rpc<{ ok: boolean; error?: string; source: { text: string; next_offset: number | null; chars: number } }>(info, "read_local_source", { source_id: source.id, offset: more ? preview?.next_offset || 0 : 0 });
      if (!alive.current || operation !== serial.current) return;
      if (!result.ok) throw new Error(result.error || "预览读取失败。");
      setPreview({ id: source.id, name: source.name, ...result.source, text: more ? (preview?.text || "") + result.source.text : result.source.text });
    } catch (err) { if (alive.current && operation === serial.current) setError(String(err)); }
    finally { if (alive.current && operation === serial.current) setBusy(false); }
  }
  async function index() {
    if (busy) return;
    const files = [...new Map(chosen.flatMap(s => s.kind === "folder" ? s.files || [] : [s]).map(s => [s.id, s])).values()];
    setBusy(true); setError("");
    const operation = ++serial.current;
    activity.current = "index";
    let done = 0;
    try {
      for (const file of files) {
        if (!alive.current || operation !== serial.current) return;
        setNote(`正在入库 ${done + 1}/${files.length}：${file.name}`);
        const result = await onIndex(file);
        if (!alive.current || operation !== serial.current) return;
        if (!result.ok) throw new Error(result.error);
        done++;
      }
      setNote(`已加入 ${done} 个文件，保存在本地知识库。`);
    } catch (err) { if (alive.current && operation === serial.current) setError(`已加入 ${done} 个文件；${String(err)}`); }
    finally { if (alive.current && operation === serial.current) setBusy(false); }
  }
  return <section ref={dialog} role="dialog" aria-modal="false" aria-label="本地文件与附件"
      style={position ? { left: position.x, top: position.y } : undefined}
      onKeyDown={event => {
        if (event.key === "Escape") { event.stopPropagation(); close(); }
      }} className="fixed right-5 top-16 z-30 flex max-h-[min(62vh,560px)] w-[460px] max-w-[calc(100vw-32px)] flex-col rounded-lg border border-border bg-background shadow-lg">
      <header className="flex touch-none select-none items-center justify-between border-b border-border px-4 py-2 cursor-move"
        onPointerDown={event => {
          if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
          const box = dialog.current!.getBoundingClientRect();
          drag.current = { x: event.clientX, y: event.clientY, left: box.left, top: box.top };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={event => {
          if (!drag.current) return;
          const width = dialog.current!.getBoundingClientRect().width;
          const height = dialog.current!.getBoundingClientRect().height;
          setPosition({ x: Math.max(8, Math.min(window.innerWidth - width - 8, drag.current.left + event.clientX - drag.current.x)),
            y: Math.max(44, Math.min(window.innerHeight - height - 8, drag.current.top + event.clientY - drag.current.y)) });
        }} onPointerUp={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}>
        <h2 className="text-sm font-semibold">本地文件与附件{minimized && busy ? " · 处理中" : ""}</h2>
        <div className="flex gap-1"><button className="desk-menu-item text-xs" onClick={() => setMinimized(v => !v)}>{minimized ? "展开" : "收起"}</button>
          <button className="desk-menu-item text-xs" onClick={close}>关闭</button></div>
      </header>
      <div hidden={minimized} className="min-h-0 flex-col overflow-y-auto p-4" style={{ display: minimized ? "none" : "flex" }}>
      <p className="mt-2 text-xs text-muted-foreground">支持文本、代码、PDF、Word、Excel、PowerPoint。文件夹递归读取可用资料，跳过隐藏目录和依赖目录；扫描 PDF 暂不支持。</p>
      <div className="my-3 flex gap-2"><button className="desk-btn" disabled={busy} onClick={() => void choose("file")}>选择文件</button><button className="desk-btn" disabled={busy} onClick={() => void choose("folder")}>选择文件夹</button></div>
      <details className="mb-3 text-xs"><summary className="cursor-pointer">输入文件或文件夹路径</summary>
        <textarea aria-label="本地资料路径" placeholder="每行一个绝对路径" className="mt-2 w-full rounded border border-border bg-card p-2" value={path} onChange={e => setPath(e.target.value)} />
        <select aria-label="路径类型" value={kind} onChange={e => setKind(e.target.value as "file" | "folder")} className="mr-2 bg-card p-1"><option value="file">文件</option><option value="folder">文件夹</option></select>
        <button className="desk-btn" disabled={busy || !path.trim()} onClick={() => void choose(kind, true)}>读取路径</button>
      </details>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto text-sm">
        {!sources.length && <p className="text-muted-foreground">选择资料后可预览、附到当前对话，或加入知识库。</p>}
        {sources.map(source => <div key={source.id} className="rounded-lg border border-border p-3">
          <label className="flex items-center gap-2"><input type="checkbox" disabled={busy || source.kind === "folder" && !source.files?.length} checked={selected.includes(source.id)} onChange={e => check(source, e.target.checked)} />
            <span>{source.name}{source.kind === "folder" ? ` · ${source.files?.length || 0} 个文件 · 整个文件夹按需读取` : ` · ${source.chars} 字`}</span>
            {source.kind === "file" && <button type="button" className="desk-btn ml-auto" disabled={busy} onClick={() => void show(source)}>预览</button>}
          </label><p className="mt-1 break-all text-xs text-muted-foreground">{source.path}</p>
          {source.kind === "folder" && <><p className="my-2 text-xs text-muted-foreground">也可单独勾选文件；跳过 {source.skipped || 0} 个不支持或隐藏文件。</p>
            {(source.files || []).map(file => <div key={file.id} className="ml-4 flex items-center gap-2 py-1"><input aria-label={`选择 ${file.relative}`} type="checkbox" disabled={busy} checked={selected.includes(file.id)} onChange={e => check(file, e.target.checked)} />
              <span className="min-w-0 flex-1 truncate" title={file.relative}>{file.relative} · {file.chars} 字</span><button className="desk-btn" disabled={busy} onClick={() => void show(file)}>预览</button></div>)}</>}
        </div>)}
        {issues.length > 0 && <div role="alert" className="text-amber-500">{issues.map((issue, i) => <p key={i}>{issue.name}：{issue.error}</p>)}</div>}
        {preview && <section className="rounded border border-border p-3"><h3>{preview.name} · 已预览 {preview.text.length}/{preview.chars} 字</h3><pre className="my-2 max-h-60 overflow-auto whitespace-pre-wrap text-xs">{preview.text}</pre>
          {preview.next_offset !== null && <button className="desk-btn" disabled={busy} onClick={() => void show(all.find(s => s.id === preview.id)!, true)}>继续读取</button>}</section>}
      </div>
      {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
      {note && <p role="status" className="my-2 text-sm">{note}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2"><button className="desk-btn desk-btn-solid" disabled={busy || !chosen.length || chosen.length > 50} onClick={() => onAttach(chosen)}>附到对话（{chosen.length}）</button>
        <button className="desk-btn" disabled={busy || !chosen.length} onClick={() => void index()}>加入知识库</button>{busy && <button className="desk-menu-item text-xs" onClick={stop}>停止等待</button>}</div>
      {busy && <p role="status" className="mt-2 text-xs text-muted-foreground"><LoadingText text="正在处理…" /> 可收起或关闭，聊天和 Agent 仍可使用。</p>}
      </div>
    </section>;
}
