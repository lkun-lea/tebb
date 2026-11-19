import { useEffect, useState } from 'react';
import { rpc, type BackendInfo } from './api';
import { UiButton, UiFeedback, UiField } from './ui-controls';

type Dispatch = {
  id: string;
  title: string;
  stage: 'development' | 'testing';
  source: string;
  input: { repository: string; commit: string; requirement_revision: number; plan_revision: number; criteria: string[]; checks: string[];
    automatic?: boolean; patch_only?: boolean; instruction?: string };
};
type DeliveryRun = Dispatch & { phase: string; receipt_status?: string; runs: string[]; error: string;
  coding_run?: string; upload?: { received: number; total: number } };
type State = { device: { origin: string; label: string | null } | null; connection: 'offline' | 'online' | 'pairing' | 'denied';
  queue: Dispatch[]; runs: DeliveryRun[] };

const phases: Record<string, string> = { authorized: '等待领取', claimed: '已领取', ready: '准备运行', intent: '核对本机运行',
  coding_intent: '正在编码或等待核对', outbox: '等待补传', uploaded: '已回传', blocked: '已阻塞' };
const outcomes: Record<string, string> = { succeeded: '已完成', failed: '执行失败', cancelled: '已取消', needs_review: '待核对', historical: '历史回执' };

export function MyAgentDeskPane({ info }: { info: BackendInfo | null }) {
  const [state, setState] = useState<State>();
  const [pack, setPack] = useState('');
  const [editingDevice, setEditingDevice] = useState(false);
  const [selected, setSelected] = useState<string>();
  const [directory, setDirectory] = useState('');
  const [recipe, setRecipe] = useState('');
  const [sources, setSources] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const task = state?.queue.find(item => item.id === selected);

  useEffect(() => {
    if (!info) return;
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const result = await rpc<State>(info, 'myagentdesk_delivery');
        if (active) setState(result);
      } catch {
        if (active) setError('暂时无法读取本机交付状态。');
      } finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2200);
    return () => { active = false; window.clearInterval(timer); };
  }, [info]);

  async function act(args: Record<string, unknown>, onDone: () => void) {
    if (!info) return;
    setError(''); setBusy(true);
    try {
      setState(await rpc<State>(info, 'myagentdesk_delivery', args));
      onDone();
    } catch (failure) { setError(failure instanceof Error ? failure.message : '操作未确认。'); }
    finally { setBusy(false); }
  }

  return <section className="settings-card">
    <h2>MyAgentDesk 交付</h2>
    {error && <UiFeedback state="error" title={error} />}
    {!state && !error && <UiFeedback state="loading" title="正在读取本机交付状态" />}
    {state?.device && <p>{state.device.label || '设备'} · {state.device.origin} · {
      { online: '已配对', offline: '工作台离线', pairing: '等待配对确认', denied: '配对或设备授权待核对' }[state.connection]
    }</p>}
    {state && (!state.device || editingDevice) && <form onSubmit={event => {
      event.preventDefault();
      void act({ action: 'pair', package: pack }, () => { setPack(''); setEditingDevice(false); });
    }}>
      <UiField label="工作台配对信息" help="从 MyAgentDesk 复制本设备的一次性配对信息。"><input type="password" required
        autoComplete="off" value={pack} onChange={event => setPack(event.target.value)} /></UiField>
      <UiButton type="submit" busy={busy} variant="primary">配对本机</UiButton>
    </form>}
    {state?.device && !editingDevice && <UiButton onClick={() => setEditingDevice(true)}>更换配对</UiButton>}
    {state?.connection === 'online' && !state.queue.length && <p>暂无待领取的派发。</p>}
    {state?.queue.map(item => <div key={item.id}>
      <p>{item.title} · {item.stage === 'testing' ? '独立验收' : '实现与自测'}</p>
      <UiButton onClick={() => { setSelected(item.id); setDirectory(''); setRecipe(''); setSources(''); setError(''); }}
        disabled={busy} aria-pressed={selected === item.id}>核对并授权</UiButton>
    </div>)}
    {task && <form onSubmit={event => {
      event.preventDefault();
      void act({ action: 'approve', identifier: task.id, directory, recipe, sources }, () => {
        setSelected(undefined); setDirectory(''); setRecipe(''); setSources('');
      });
    }}>
      <h3>{task.title}</h3>
      <p>{task.input.repository} · 需求 v{task.input.requirement_revision} · 计划 v{task.input.plan_revision}</p>
      <p>{task.input.automatic || task.input.patch_only ? '固定基准' : '固定候选'} <code>{task.input.commit}</code></p>
      {task.input.instruction && <p>{task.input.instruction}</p>}
      <ul>{task.input.criteria.concat(task.input.checks).map((item, index) => <li key={index}>{item}</li>)}</ul>
      <UiField label="授权本机克隆目录" help="输入绝对路径。命令只在该提交的隔离快照中执行。">
        <input required value={directory} onChange={event => setDirectory(event.target.value)} />
      </UiField>
      {task.input.automatic && <UiField label="授权 Agent 读写的源码" help="每行一个仓库相对路径。Agent 只读写清单内的已有文本文件。">
        <textarea required rows={3} maxLength={5000} value={sources} onChange={event => setSources(event.target.value)} />
      </UiField>}
      <UiField label="本机命令清单" help="粘贴 JSON。研发使用 implementation；独立验收按顺序使用 criterion:1 和 check:1 等编号。">
        <textarea required rows={4} maxLength={20000} value={recipe} onChange={event => setRecipe(event.target.value)} />
      </UiField>
      <p>确认后回传本次授权的补丁及有界命令输出。</p>
      <UiButton type="submit" busy={busy} variant="primary">授权目录并领取</UiButton>
      <UiButton disabled={busy} onClick={() => setSelected(undefined)}>取消</UiButton>
    </form>}
    {state?.runs.map(item => <div key={item.id}>
      <p>{item.title} · {item.id.slice(0, 8)} · {phases[item.phase]}
        {item.receipt_status && ' · ' + outcomes[item.receipt_status]}</p>
      {!!item.runs.length && <p>原运行 <code>{item.runs.join(' · ')}</code></p>}
      {item.coding_run && <p>编码运行 <code>{item.coding_run}</code></p>}
      {item.upload && <p>已上传 {item.upload.received} / {item.upload.total} 个补丁分片</p>}
      {item.error && <p role="alert">{item.error}</p>}
    </div>)}
  </section>;
}
