import {WorkspaceDialog} from './workspace-dialog';
import {UiButton,UiField} from './ui-controls';
import { usePageActive } from "./page-stack";
import { useEffect, useState } from "react";
import { rpc, type BackendInfo, type ChatItem } from "./api";
import { Markdown } from "./Markdown";
import { TaskVideos } from "./video";
import { TaskBudgetView,type TaskBudget } from './task-budget';
import{CalendarProposalCards}from'./calendar-proposal';
import{proposalsFromEvents}from'./calendar-proposal-state';
import {ExecutionEntry} from './execution-entry';

type Settings = { parallel: number; call_timeout: number; task_timeout: number; pet_progress: boolean };
type Event = { seq: number; kind: string; ts: number; data: string | { tool?: string; status?: string; duration_ms?: number; message?: string } };
type Task = { id: string; session: string; channel: string; text: string; state: string; answer: string; error: string;
  task_budget?:TaskBudget|null;
  created: number; elapsed: number; events?: Event[]; source: { message_id?: string; send_back?: boolean } };
const STATES: Record<string, string> = { queued: "排队中", running: "执行中", cancelling: "正在停止", succeeded: "完成",
  failed: "失败", cancelled: "已停止", timed_out: "超时", interrupted: "上次运行中断" };
const active = (t: Task) => ["queued", "running", "cancelling"].includes(t.state);

export function AgentMonitor({ info, debug = false }: { info: BackendInfo | null; debug?: boolean }) {
  const pageActive = usePageActive();
  const [policyOpen,setPolicyOpen] = useState(false);
  const [limit,setLimit] = useState(12);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, select] = useState("");
  const [detail, setDetail] = useState<Task | null>(null);
  const [history, setHistory] = useState<ChatItem[]>([]);
  const [channel, setChannel] = useState("feishu");
  const [settings, setSettings] = useState<Settings>({ parallel: 2, call_timeout: 90, task_timeout: 300, pet_progress: true });
  const [dirty, setDirty] = useState(false);
  const [text, setText] = useState("");
  const [sendBack, setSendBack] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!pageActive || !info || debug) return;
    let live = true;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const value = await rpc<{ items: Task[]; settings: Settings }>(info, "list_agent_tasks", { channel });
        if (!live) return;
        setTasks(value.items);
        if (!dirty) setSettings(value.settings);
        const id = selected;
        if (id) {
          const found = await rpc<{ task: Task; history: ChatItem[] }>(info, "get_agent_task", { task_id: id });
          if (live) { setDetail(found.task); setHistory(found.history); }
        } else { setDetail(null); setHistory([]); }
      } catch (err) { if (live) setError(String(err)); }
      finally { loading = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { live = false; window.clearInterval(timer); };
  }, [pageActive, info, debug, selected, channel, dirty]);

  async function run(method: string, args: Record<string, unknown>) {
    if (!info || debug || busy) return;
    setBusy(true); setError("");
    try {
      const result = await rpc<{ ok: boolean; error?: string; task_id?: string; task?: Task }>(info, method, args);
      if (result.ok === false) throw new Error(result.error || "操作失败");
      if (result.task_id) { select(result.task_id); setText(""); }
      if (result.task) setDetail(result.task);
      if (method === "save_agent_task_settings") {setDirty(false);setPolicyOpen(false);}
    } catch (err) { setError(String(err)); }
    finally { setBusy(false); }
  }

  return <section className="channel-monitor" aria-label="聊天任务监控台">
    <header className="channel-heading"><h2>渠道任务</h2><UiButton onClick={()=>setPolicyOpen(true)}>执行设置</UiButton></header>
    {policyOpen&&<WorkspaceDialog title="执行设置" onClose={()=>setPolicyOpen(false)}>
      <div className="channel-policy">
        {([["parallel", "同时执行任务数", 1, 4], ["call_timeout", "调用等待时限（秒）", 10, 300], ["task_timeout", "任务总时限（秒）", 10, 1800]] as const).map(([key, label, min, max]) =>
          <UiField key={key} label={label}><input type="number" min={min} max={max} value={settings[key]}
            onChange={e => { setDirty(true); setSettings({ ...settings, [key]: Number(e.target.value) }); }} /></UiField>)}
        <label><input type="checkbox" checked={settings.pet_progress} onChange={e => { setDirty(true); setSettings({ ...settings, pet_progress: e.target.checked }); }} /> 凯尔希播报真实进度</label>
        <UiButton variant="primary" disabled={busy || !dirty || debug} onClick={() => void run("save_agent_task_settings", settings)}>保存执行设置</UiButton>
      </div>
      <details><summary>时限说明</summary><p className="mt-2 text-xs text-muted-foreground">时限设置也用于之后提交的伙伴聊天任务，已有任务保持原时限。模型持续输出时继续等待，单次最多 5 分钟；编码命令按自身时限执行并预留20秒收尾，总任务时限始终有效。伙伴聊天固定2项长任务与1条聊天并行。视频笔记总时限至少15分钟，可随时停止。</p></details>
    </WorkspaceDialog>}
    <label className="mt-4 block text-sm">查看范围 <select className="ml-2 rounded bg-secondary p-2" value={channel}
      onChange={e => { setLimit(12); setChannel(e.target.value); select(""); setDetail(null); }}><option value="feishu">飞书聊天</option><option value="">全部任务</option><option value="desktop">桌面对话</option><option value="video">视频读取</option><option value="debug">调用与参数验证</option></select></label>
    <div className="channel-results">
      <div className="channel-records">
        {!tasks.length && <p className="text-sm text-muted-foreground">当前渠道暂无任务。</p>}
        {tasks.slice(0,limit).map(t => <button key={t.id} className={`block w-full rounded-lg border p-3 text-left ${detail?.id === t.id ? "border-primary/60 bg-secondary" : "border-border"}`}
          onClick={() => { setDetail(t); select(t.id); setText(""); setSendBack(false); }}>
          <span className="block break-words text-sm">{t.text}</span>
          <span className="mt-1 block text-xs text-muted-foreground">{STATES[t.state] || t.state} · {t.elapsed} 秒 · {({ feishu: "飞书", desktop: "桌面", automation: "定时任务", video: "视频" } as Record<string, string>)[t.channel] || t.channel}</span>
          <span className="block text-xs text-muted-foreground">{new Date(t.created * 1000).toLocaleString()}</span>
        </button>)}
      </div>
      {tasks.length>limit&&<UiButton onClick={()=>setLimit(n=>n+12)}>显示更多任务</UiButton>}
      {selected && detail?.id===selected && <WorkspaceDialog title={detail.text || "任务详情"} onClose={()=>{select("");setDetail(null);setHistory([])}}><div className="min-w-0 space-y-4">
        <div className="flex items-center justify-between"><span>{STATES[detail.state]} · {detail.elapsed} 秒</span>
          <button className="rounded bg-red-400/10 px-3 py-2 text-sm" hidden={!active(detail)} disabled={busy || !active(detail)} onClick={() => void run("cancel_agent_task", { task_id: detail.id })}>停止任务</button></div>
        <ExecutionEntry info={info} task={detail.id}/>
        {detail.error && <p role="alert" className="rounded bg-red-400/10 p-3 text-sm">{detail.error}</p>}
        <TaskBudgetView budget={detail.task_budget}/>
        <div className="rounded-lg bg-secondary p-4"><p className="mb-2 text-xs text-muted-foreground">当前答案{active(detail) ? " · 正在更新" : ""}</p><Markdown text={detail.answer || "尚未生成正文。"} /></div>
        {!debug && <TaskVideos info={info} taskId={detail.id} state={detail.state} />}
        <details open><summary className="cursor-pointer text-sm">任务时间线</summary><ol className="mt-2 space-y-2 text-xs text-muted-foreground">
          {!(detail.events||[]).some(e=>!["token","think"].includes(e.kind))&&<li>此任务未记录阶段事件。</li>}
          {(detail.events || []).filter(e => !["token", "think"].includes(e.kind)).map(e => <li key={e.seq}>
            {new Date(e.ts * 1000).toLocaleTimeString()} · {e.kind==="done"?"任务结束":typeof e.data === "string" ? e.data : e.kind === "task_budget" ? "更新整个目标的任务预算" : e.kind === "failure" ? e.data.message || "任务失败" : e.data?.tool ? `${e.kind === "tool_start" ? "调用" : "返回"} ${e.data?.tool} ${e.data.status || ""} ${e.data.duration_ms !== undefined ? `${e.data.duration_ms}ms` : ""}` : e.kind === "llm_start" ? "开始调用模型" : "模型返回"}
          </li>)}</ol></details>
        <CalendarProposalCards info={info} proposals={proposalsFromEvents(detail.events||[])}/>
        <details><summary className="cursor-pointer text-sm">本会话聊天记录（{history.length} 条）</summary><div className="mt-3 max-h-80 overflow-auto space-y-3">
          {history.map((item, i) => <div key={i} className="rounded-lg bg-secondary p-3"><p className="mb-1 text-xs text-muted-foreground">{item.role === "user" ? "博士" : "凯尔希"}</p><Markdown text={item.text} /></div>)}
        </div></details>
        <label className="block text-sm">继续这段对话<textarea className="mt-2 block w-full rounded-lg bg-secondary p-3" rows={3} value={text} onChange={e => setText(e.target.value)} placeholder="补充问题或要求。会保留当前会话的上下文。" /></label>
        {detail.channel === "feishu" && <label className="block text-sm"><input type="checkbox" checked={sendBack} onChange={e => setSendBack(e.target.checked)} /> 将这次回答发送回原飞书私聊</label>}
        <button className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground" disabled={busy || active(detail) || !text.trim() || debug}
          onClick={() => void run("continue_agent_task", { task_id: detail.id, text, send_back: sendBack })}>{sendBack ? "继续并回复飞书" : "在本地继续"}</button>
      </div></WorkspaceDialog>}
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
  </section>;
}
