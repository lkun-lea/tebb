import {LoadingText} from "./loading-text";
import {PageStack,usePageActive} from "./page-stack";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { emitTo } from "@tauri-apps/api/event";
import { backendInfo, rpc, type BackendInfo } from "./api";
import { debugPane, installDeskDebug, STATUS_FIXTURE } from "./debug";
import { accountStorage } from "./account-storage";
import {
  BackgroundCrop,
  clearStoredBackground,
  readBackgroundFile,
  readStoredBackground,
  SettingsPane,
  storeBackground,
} from "./settings";
import { useFeishuConnection, useModelSettings } from "./settings-state";
import { SetupGuide, type SetupStatus } from "./onboarding";
import type { ModelSetupState } from "./onboarding-state";
import { AccountsPane } from "./accounts";
import { MobilePairingPane } from "./mobile-pairing";
import { ReminderSettings } from "./reminders";
import { PersonalUsagePane } from "./usage-center";
import { ReleaseIntro, ReleaseSettings, useReleaseIntro } from "./release";
import { ModelNetworkSettings } from "./model-network";
import { SearchSettings } from "./search-settings";
import { FeishuPane, feishuLoggedIn } from "./feishu";
import { FeishuAgentPane } from "./feishu-agent";
import { VideoLogin, VideoSettings } from "./video";
import { loadingStatuses, statusError, statusFromPayload, STATUS_KINDS, type StatusView } from "./status";
import { AgentDebugDialog } from "./agent-debug";
import { ExecutionCenterPane } from './execution-trace';
import { ToolMonitorPane } from './tool-monitor';
import { EvaluationPane } from './evaluation-center';
import {AgentMonitor} from "./agent-monitor";
import {WorkspaceRuns} from "./workspace-runs";
import { WindowCloseButton } from "./window-chrome";
import {ArrowLeft, Activity, BookOpen, ChartColumn, CircleUserRound, CodeXml, Database, Layers, Link2, Paintbrush, Settings2, Wrench} from "lucide-react";
import "./settings-window.css";
import "./settings-dashboard.css";

const PersonalizationPane = lazy(() => import("./personalization").then(module => ({ default: module.PersonalizationPane })));

type SettingsSection = "assistant" | "account" | "personalization" | "connections" | "appearance" | "usage" | "tools" | "evaluation" | "network" | "monitor" | "about";

type NavItem = { id: SettingsSection; label: string; keywords: string };

// 搜索沿用分类的显示顺序，同时匹配名称和关键词。
const SETTINGS_NAV: { id: string; label: string; items: NavItem[] }[] = [
  { id: "workspace", label: "", items: [
    { id: "account", label: "账号与空间", keywords: "账号 账户 数据目录 空间" },
    { id: "assistant", label: "模型与人设", keywords: "模型 api base url key 人设 提示词 引导" },
    { id: "connections", label: "外部连接", keywords: "飞书 github 网络代理 搜索 视频 登录 连接" },
    { id: "tools", label: "工具", keywords: "工具 集合 加载 调用 失败 监控" },
    { id: "monitor", label: "运行监控", keywords: "失败 时间线 运行 任务" },
    { id: "evaluation", label: "调试与评测", keywords: "执行图 流程 时间线 评测 黄金集 调试 agent" },
    { id: "usage", label: "个人使用", keywords: "用量 费用 统计 token 成本" },
  ] },
  { id: "preferences", label: "其他设置", items: [
    { id: "personalization", label: "个人资料", keywords: "画像 个人资料 记忆 个性化" },
    { id: "appearance", label: "外观与通知", keywords: "主题 深色 浅色 背景 壁纸 外观 通知 会前提醒" },
    { id: "network", label: "模型网络", keywords: "代理 网络 模型" },
    { id: "about", label: "版本与诊断", keywords: "版本 更新 诊断 调试 关于" },
  ] },
];

const SECTION_META: Record<SettingsSection, { title: string; blurb: string }> = {
  assistant: { title: "模型与人设", blurb: "管理模型服务、系统提示词与会前提醒。" },
  account: { title: "账号与空间", blurb: "管理本机账号与数据目录。" },
  personalization: { title: "个人资料", blurb: "查看和修正 tebb 对你的了解。" },
  monitor: {title:'运行监控',blurb:'按任务查找执行记录和失败步骤。'},
  network: {title:'模型网络',blurb:'管理模型请求的连接与代理。'},
  connections: { title: "外部连接", blurb: "管理飞书、GitHub、搜索与视频来源的连接。" },
  appearance: { title: "外观与通知", blurb: "调整主题与工作台背景。" },
  usage: { title: "个人使用", blurb: "查看调用次数、费用估算与明细。" },
  tools: {title:'工具',blurb:'查看固定工具定义、加载记录、调用与失败。'},
  evaluation: {title:'调试与评测',blurb:'追踪真实执行过程，按原始证据核对任务结果。'},
  about: { title: "版本与诊断", blurb: "查看版本信息、检查更新与调用调试。" },
};

const navIcons={assistant:Settings2, account:CircleUserRound, personalization:BookOpen, connections:Link2, appearance:Paintbrush, usage:ChartColumn, tools:Wrench, evaluation:CodeXml, network:Layers, monitor:Activity, about:Database};
const serviceNames:Record<string,string>={feishu:'飞书',github:'GitHub',Bilibili:'哔哩哔哩',YouTube:'YouTube',search:'搜索服务'};
const serviceIcons:Record<string,string>={feishu:"feishu.ico",github:"github.svg",Bilibili:"Bilibili.ico",YouTube:"YouTube.png"};
const SECTIONS: SettingsSection[] = ["assistant", "account", "personalization", "connections", "appearance", "usage", "tools", "evaluation", "network", "monitor", "about"];

function initialSection(): SettingsSection {
  const value = new URLSearchParams(window.location.search).get("section");
  return SECTIONS.includes(value as SettingsSection) ? value as SettingsSection : "assistant";
}

// 跨窗口定位：主窗口入口（如 tebb-open-personalization）通过事件把设置窗口切到目标分类。
type SectionTarget = { section?: string; profile?: string; trace?:string; service?:string };

function focusMainWindow() {
  if (isTauri()) void invoke("show_main").catch(() => {});
  else window.opener?.focus?.();
}

export function SettingsApp({target,onOpenChat,onBack}:{target?:SectionTarget;onOpenChat?:()=>void;onBack?:()=>void}={}) {
  const debugKind = debugPane();
  const debug = !!debugKind;
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [section, setSection] = useState<SettingsSection>(() => (debugKind === "usage" ? "usage" : debugKind === "feishu" || debugKind === "video" ? "connections" : debugKind === "profile" ? "personalization" : initialSection()));
  const [profileTarget, setProfileTarget] = useState<{ id: string; nonce: number } | null>(() => {
    const id = new URLSearchParams(window.location.search).get("profile");
    return id ? { id, nonce: Date.now() } : null;
  });
  const [query, setQuery] = useState("");
  const [dark, setDark] = useState(() => { try { return accountStorage().getItem("tebb.theme") !== "light"; } catch { return true; } });
  const [storedBg] = useState(() => readStoredBackground());
  const [bgUrl, setBgUrl] = useState(storedBg.url);
  const [bgError, setBgError] = useState(storedBg.error);
  const [cropSrc, setCropSrc] = useState("");
  const [cropError, setCropError] = useState("");
  const [cropFrame, setCropFrame] = useState({ w: 0, h: 0 });
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const pageActive = usePageActive();
  const [showGuide, setShowGuide] = useState(false);
  const [guideModel, setGuideModel] = useState<ModelSetupState | null>(null);
  const [statuses, setStatuses] = useState<StatusView[]>([]);
  const [bootError, setBootError] = useState("");
  const [githubNotice,setGithubNotice]=useState('');
  const [githubPending,setGithubPending]=useState(false);
  const [confirmLogout,setConfirmLogout]=useState(false);
  const [feishuChecked,setFeishuChecked]=useState(0);
  const [videoStates,setVideoStates]=useState<Record<string,string>>({});
  const [lastStatus]=useState(()=>new Map<string,string>());
  const [activities,setActivities]=useState<{service:string;line:string;time:number}[]>([]);
  const [githubAccount,setGithubAccount]=useState('');
  const [checkedAt,setCheckedAt]=useState(0);
  const [checkVersion,recheck]=useState(0);
  const [service,setService]=useState(()=>new URLSearchParams(window.location.search).get('service') || (debugKind==='video'?'Bilibili':'feishu'));
  const [trace,setTrace]=useState(()=>new URLSearchParams(window.location.search).get('trace')||'');
  const lastRun=useRef("");
  const [monitorView,setMonitorView]=useState<'history'|'collaboration'|'channels'>('history');
  const [evalTab,setEvalTab]=useState('debug');
  function openModelCalls(){setEvalTab("debug");setSection("evaluation");}
  const releaseIntro = useReleaseIntro(!target && !!setupStatus && !setupStatus.show && !showGuide && !cropSrc && !debugKind);

  const models = useModelSettings({ info, debug });
  useEffect(()=>{if(target)window.dispatchEvent(new Event("tebb-models-changed"));},[models.modelItems]);
  useEffect(()=>{if(target)window.dispatchEvent(new CustomEvent("tebb-background",{detail:bgUrl}));},[bgUrl]);
  const feishuState = useFeishuConnection({ info, debug, active: section === "connections" });

  // 连接与网络：进入分类时读取连接状态；飞书卡片由连接状态同步。
  useEffect(() => {
    if (section !== "connections") return;
    if (debugKind) {
      setStatuses(STATUS_FIXTURE);
      return;
    }
    if (!info) {
      setStatuses(STATUS_KINDS.map((kind) => statusError(kind, "还没有连上本地后端。恢复：重启客户端。")));
      return;
    }
    setStatuses((cur) => (cur.length ? cur : loadingStatuses()));
    const methods: Record<string, string> = { github: "connection_status" };
    let current=true;
    for (const kind of STATUS_KINDS.filter(kind=>kind==="github")) {
      void rpc<{checked_at:number;ok:boolean;login?:string}>(info, methods[kind],{service:kind})
        .then((data) => {
          if (!current) return;
          if(data.ok!==true||!data.login)throw Error('尚未取得 GitHub 账号回执');
          setGithubAccount(data.login);setCheckedAt(data.checked_at);
          setStatuses((cur) => cur.map((card) => (card.kind === kind ? statusFromPayload(kind, data) : card)));
        })
        .catch((err: unknown) => {
          if(!current)return;
          setGithubAccount('');
          setStatuses((cur) => cur.map((card) => (card.kind === kind ? statusError(kind, String(err)) : card)));
        });
    }
    void rpc<{items:{platform:string;state:string}[]}>(info,'load_video_login').then(value=>{
      if(current)setVideoStates(Object.fromEntries(value.items.map(item=>[item.platform,item.state])));
    }).catch(()=>{});
    return ()=>{current=false};
  }, [section, service, info, debugKind, checkVersion]);

  useEffect(() => {
    if (feishuState.feishu) {
      if(!debugKind)setFeishuChecked(Date.now());
      setStatuses((cur) => cur.map((card) => (card.kind === "feishu" ? statusFromPayload("feishu", feishuState.feishu) : card)));
    }
  }, [feishuState.feishu]);

  // 启动：连接本地后端，读取引导状态；首次使用自动打开引导。
  useEffect(() => {
    if (debugKind) return;
    let gone = false;
    void (async () => {
      try {
        const backend = await backendInfo();
        if (gone) return;
        setInfo(backend);
        const setup = await rpc<SetupStatus>(backend, "load_onboarding");
        if (gone) return;
        setSetupStatus(setup);
        setShowGuide(setup.show);
      } catch (err) {
        if (!gone) setBootError(String(err));
      }
    })();
    return () => { gone = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(()=>{
    if(!target)return;
    if(SECTIONS.includes(target.section as SettingsSection))setSection(target.section as SettingsSection);
    if(target.service && target.section==='connections')setService(target.service);
    if(target.section==='monitor'){lastRun.current=target.trace||'';setTrace(target.trace||'');setMonitorView('history');}
    if(target.profile)setProfileTarget({id:target.profile,nonce:Date.now()});
  },[target]);


  // 主题：写本地存储，主窗口通过 storage 事件同步。
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
    try { accountStorage().setItem("tebb.theme", dark ? "dark" : "light"); } catch { /* theme stays active */ }
  }, [dark]);

  // 背景截取：按主窗口纵横比裁切，保证与主窗口所见一致。
  useEffect(() => {
    if (!cropSrc) return;
    let done = false;
    void (async () => {
      let w = 1180, h = 760;
      if (isTauri()) {
        try {
          const size = await invoke<{ width: number; height: number }>("main_window_inner_size");
          if (size.width > 0 && size.height > 0) { w = size.width; h = size.height; }
        } catch { /* 未取到时用默认比例 */ }
      }
      if (done) return;
      const availW = Math.max(240, window.innerWidth - 96);
      const availH = Math.max(180, window.innerHeight - 96);
      const scale = Math.min(availW / w, availH / h, 1);
      setCropFrame({ w: Math.round(w * scale), h: Math.round(h * scale) });
    })();
    return () => { done = true; };
  }, [cropSrc]);

  // 开发态调试桥：设置窗口拥有设置相关快照与注入。
  useEffect(() => {
    installDeskDebug({
      openSettings: (target?: string) => { if (SECTIONS.includes(target as SettingsSection)) setSection(target as SettingsSection); },
      seedFeishu: feishuState.rememberFeishu,
      seedStatus: (raw) => setStatuses(STATUS_KINDS.map((kind) => statusFromPayload(kind, raw[kind]))),
      setBackground: (url) => {
        const saved = storeBackground(url);
        if (saved.error) { setBgError(saved.error); return; }
        setBgUrl(saved.url); setBgError("");
      },
      clearBackground: () => { clearStoredBackground(); setBgUrl(""); setBgError(""); },
      openBackgroundCrop: (url) => { setCropError(""); setCropSrc(url); },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function githubAction(action:'login'|'logout'){
    if(!info||githubPending)return;
    setGithubPending(true);setConfirmLogout(false);
    try{
      const result=await rpc<{next_step:string}>(info,'github_account_dialog',{action});
      setGithubNotice(result.next_step);
    }catch(error){setGithubNotice(String(error));}
    finally{setGithubPending(false);}
  }

  async function pickBackground(file: File) {
    const read = await readBackgroundFile(file);
    if (read.error || !read.url) {
      setBgError(read.error || "这张图打不开。恢复：换一张 png、jpg 或 webp。");
      return;
    }
    setBgError("");
    setCropError("");
    setCropSrc(read.url);
  }

  function confirmCrop(url: string) {
    const saved = storeBackground(url);
    if (saved.error) {
      setCropError(saved.error);
      return;
    }
    setBgUrl(saved.url);
    setBgError("");
    setCropError("");
    setCropSrc("");
  }

  function openGuide(replay = false) {
    const load = async () => {
      if (!info) {
        setShowGuide(true);
        return;
      }
      try {
        const setup = await rpc<SetupStatus>(info, "load_onboarding");
        setSetupStatus(replay ? { ...setup, step: "model" } : setup);
        setShowGuide(true);
      } catch (err) {
        setBgError(String(err));
      }
    };
    void load();
  }

  const nav = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return SETTINGS_NAV;
    return SETTINGS_NAV
      .map((group) => ({
        ...group,
        items: group.items.filter((item) => item.label.toLowerCase().includes(needle) || item.keywords.includes(needle)),
      }))
      .filter((group) => group.items.length > 0);
  }, [query]);

  function serviceStatus(id:string){
    const known=statuses.find(s=>s.kind===id);
    if(!info&&!debug)return {text:'未检查',state:'unknown'};
    if(id==='feishu' && feishuState.feishu?.ok){
      if(feishuState.feishu.login_busy)return {text:'等待授权',state:'waiting'};
      if(feishuState.feishu.token_expired)return {text:'授权已过期',state:'expired'};
    }
    if(known)return {text:({ready:'已连接',off:'未连接',error:'检查失败',loading:'检查中'})[known.state],state:known.state};
    const video=videoStates[id];
    return {text:({saved:'已保存',expired:'需授权',missing:'未连接',error:'检查失败'} as Record<string,string>)[video]||(id==='search'?'配置':'未检查'),state:video==='saved'?'ready':video||'unknown'};
  }
  const connection=serviceStatus(service);
  const connectionLine=connection.text;
  const inspectedAt=service==='feishu'?feishuChecked:service==='github'?checkedAt*1000:0;
  const checkTime=(ms:number)=>new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(ms);
  useEffect(()=>{
    if(section!=='connections'||debug||!info||(service==='feishu'&&!feishuChecked)||(service==='github'&&!checkedAt)||['检查中','未检查','配置'].includes(connectionLine))return;
    const previous=lastStatus.get(service);
    lastStatus.set(service,connectionLine);
    if(previous===undefined||previous===connectionLine)return;
    setActivities(old=>old.find(row=>row.service===service)?.line===connectionLine?old:
      [{service,line:connectionLine,time:Date.now()},...old].slice(0,40));
  },[section,debug,info,service,connectionLine,feishuChecked,checkedAt]);
  const filtered = query.trim() !== "";
  const meta = SECTION_META[section];

  return (
    <div className="settings-window" data-settings-shell="1" data-embedded={!!target} data-settings-section={section}>
      <aside aria-label="设置导航" data-tauri-drag-region>
        {onBack&&<button className="workspace-back" aria-label="返回工作台" onClick={onBack}><ArrowLeft size={16} aria-hidden="true"/>返回工作台</button>}
        <div className="settings-brand" data-tauri-drag-region><i/>tebb</div><h2 className="settings-rail-title">设置</h2>
        <div className="settings-search" data-settings-search>
          <input
            type="search"
            value={query}
            placeholder="搜索设置项"
            aria-label="搜索设置分类"
            onChange={(ev) => setQuery(ev.target.value)}
          />
        </div>
        <nav aria-label="设置分类" data-tauri-drag-region data-settings-filtered={filtered ? nav.length : ""}>
          {nav.map((group) => (
            <div key={group.id} className="settings-nav-group">
              <p className="settings-nav-group-label">{group.label}</p>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="settings-nav-item"
                  data-settings-nav-item={item.id}
                  aria-current={section === item.id ? "page" : undefined}
                  onClick={() => {setShowGuide(false);setSection(item.id);}}
                >
                  {(() => {const Icon=navIcons[item.id];return <Icon size={17} aria-hidden="true"/>})()}{item.label}
                </button>
              ))}
            </div>
          ))}
          {filtered && nav.length === 0 ? (
            <p className="settings-nav-group-label" role="status">没有匹配的分类</p>
          ) : null}
        </nav>
      </aside>
      <main>
        <div className="settings-main-inner">
          <header className="settings-section-header" data-tauri-drag-region>
            <h1 data-tauri-drag-region>{meta.title}</h1>
            <p data-tauri-drag-region>{meta.blurb}</p>
          </header>
      {pageActive && showGuide && info && setupStatus ? (
        <SetupGuide
          info={info}
          status={setupStatus}
          modelState={guideModel}
          configured={!!models.modelItems.length}
          feishuConnected={feishuLoggedIn(feishuState.feishu)} modelBusy={models.settingsBusy || feishuState.feishuBusy}
          onClose={(completed) => {
            setShowGuide(false);
            if (completed) setSetupStatus(current => current ? { ...current, show: false } : current);
          }}
          onNavigate={(target) => {
            if (target === "settings") setSection("assistant");
            else if (target === "feishu") { setSection("connections"); void feishuState.ensureFeishu(); }
            else if(target==="collaboration") (onOpenChat || focusMainWindow)();
            else if (target==="terminal" && pageActive) window.dispatchEvent(new CustomEvent("desk-open-preview",{detail:{kind:"terminal"}}));
          }}
        />
      ) : null}

          {bootError ? <p role="alert" className="text-sm text-destructive">连不上本地助手：{bootError}。恢复：重启客户端后重试。</p> : null}


          {section === "account" ? <><AccountsPane info={info} debug={debug} /><MobilePairingPane info={info} /></> : null}
          {section === 'tools' ? <ToolMonitorPane info={info} onChat={async conversation=>{
            if (!info) return;
            await rpc(info,'collaboration_action',{action:{type:'select',id:conversation,conversation,request_id:crypto.randomUUID()}});
            if(isTauri()) await emitTo('main','open-collaboration');
            focusMainWindow();
          }} onConnections={()=>setSection('connections')} onTrace={id=>{lastRun.current=id;setTrace(id);setMonitorView('history');setSection('monitor')}}/> : null}
          {section === 'monitor' && <>
            <nav className="design-tabs monitor-views" aria-label="运行监控视图">
              {([['history','运行记录'],['collaboration','协作任务'],['channels','渠道任务与执行设置']] as const).map(([id,label])=>
                <button key={id} type="button" aria-pressed={monitorView===id} onClick={()=>setMonitorView(id)}>{label}</button>)}

            </nav>
            {monitorView==='history'&&<ExecutionCenterPane key={trace} info={info} initialTrace={lastRun.current||trace} onSelectRun={id=>{lastRun.current=id}} onInspectCalls={openModelCalls}/>}
            <PageStack active={monitorView==='history'?'':monitorView}>
              {monitorView==='collaboration'?<WorkspaceRuns info={info} onOpen={async conversation=>{if(info){await rpc(info,'collaboration_action',{action:{type:'select',id:conversation,conversation,request_id:crypto.randomUUID()}});if(isTauri())await emitTo('main','open-collaboration');focusMainWindow();}}}/>:<AgentMonitor info={info} debug={debug}/>}
            </PageStack>
          </>}
          {section === 'evaluation' && <><div className="design-tabs"><button className="desk-btn" aria-pressed={evalTab==='debug'} onClick={()=>setEvalTab('debug')}>模型调用</button><button className="desk-btn" aria-pressed={evalTab==='evaluation'} onClick={()=>setEvalTab('evaluation')}>评测批次</button></div>{evalTab==='debug'?<AgentDebugDialog inline info={info} debug={debug} onClose={()=>{}}/>:<EvaluationPane info={info}/>}</>}
          {section === "personalization" ? (
            <Suspense fallback={<p role="status"><LoadingText text="正在打开个人画像…"/></p>}>
              <PersonalizationPane info={info} debug={debug} target={profileTarget} onAccount={()=>setSection("account")} onInspect={openModelCalls} />
            </Suspense>
          ) : null}

          <div hidden={!["assistant", "appearance"].includes(section)}>
            <SettingsPane
              section={section === "appearance" ? "appearance" : "assistant"}
              onOpenGuide={(replay = false) => openGuide(replay)}
              model={models.modelForm}
              models={models.modelItems}
              editingId={models.editingModelId}
              modelError={models.settingsError}
              notice={models.settingsNotice}
              persona={models.personaForm?.persona || ""}
              personaError={models.personaError}
              personaNotice={models.personaNotice}
              busy={models.settingsBusy}
              keyEpoch={models.keyEpoch}
              dark={dark}
              photo={!!bgUrl}
              bgError={bgError}
              onToggleTheme={() => {setDark(!dark); window.dispatchEvent(new CustomEvent("tebb-theme",{detail:!dark}));}}
              onPickFile={(file) => void pickBackground(file)}
              onClearBackground={() => { clearStoredBackground(); setBgUrl(""); setBgError(""); }}
              onSave={(draft) => void models.saveSettings(draft)}
              onTest={models.testSettings}
              onSetupChange={setGuideModel}
              onEdit={models.editModel}
              onDelete={(id) => void models.deleteModel(id)}
              onSavePersona={(text) => void models.savePersona(text)}
            />
          </div>

          {section==='appearance' && <ReminderSettings info={info} debug={debug}/>}
          {section==='network'&&<ModelNetworkSettings info={info} debug={debug}/>}
          {section === 'connections' && <div>
            <div className="external-services"><nav aria-label="外部服务">
              {Object.entries(serviceNames).map(([id,name])=>{const icon=serviceIcons[id],status=serviceStatus(id);return <button key={id} aria-pressed={service===id} onClick={()=>setService(id)}>
                {icon&&<img className="service-icon" alt="" width="20" height="20" src={'/service-icons/'+icon}/>}<strong>{name}</strong><small data-state={status.state}>{status.text}</small></button>})}
            </nav><section className="service-detail"><h2>{serviceNames[service]}</h2><p className="service-state" data-state={connection.state}><span aria-hidden="true">{connection.state==='ready'?'✓':connection.state==='expired'||connection.state==='error'?'!':'−'}</span>{connectionLine}</p>
            <dl className="service-facts ui-facts"><div><dt>{service==='feishu'&&!feishuState.feishu?.connected&&!feishuState.feishu?.logged_in&&feishuState.feishu?.user_name?'本机账号':'当前账号'}</dt><dd>{service==='feishu'?feishuState.feishu?.user_name||'暂无账号信息':service==='github'?githubAccount||'暂无账号信息':'暂无账号信息'}</dd></div>
            <div><dt>关联工具</dt><dd>{{feishu:'日历、任务、文档',github:'仓库查询',Bilibili:'视频读取',YouTube:'视频读取',search:'联网搜索'}[service]}</dd></div>
            {(service==='feishu'||service==='github')&&<div><dt>最近检查</dt><dd>{inspectedAt?<time dateTime={new Date(inspectedAt).toISOString()}>{checkTime(inspectedAt)}</time>:'尚未检查'}</dd></div>}</dl>
            {service==='search'&&<SearchSettings info={info} debug={debug}/>}
            {service==='github'&&<><div className="execution-toolbar"><button className="desk-btn" disabled={!info||githubPending} onClick={()=>void githubAction('login')}>连接或切换账号</button><button className="desk-btn" disabled={!info||githubPending} onClick={()=>confirmLogout?void githubAction('logout'):setConfirmLogout(true)}>{confirmLogout?'确认断开本机 GitHub CLI 账号':'断开连接'}</button><button className="desk-btn" disabled={!info||githubPending} onClick={()=>recheck(n=>n+1)}>检查账号</button>{confirmLogout&&<button className="desk-btn" onClick={()=>setConfirmLogout(false)}>取消</button>}</div>{githubNotice&&<p role="status">{githubNotice}</p>}</>}
            {service==='feishu'&&<><div className="service-actions"><FeishuPane snap={feishuState.feishu} busy={feishuState.feishuBusy} debug={debug} onLogin={() => void feishuState.startFeishuLogin()} onLogout={() => void feishuState.logoutFeishu()} onCheck={()=>void feishuState.ensureFeishu()} checkDisabled={!info||debug} /></div>
            {feishuState.feishu?.logged_in&&<p>可用权限　{[['日历',feishuState.feishu.has_calendar],['任务',feishuState.feishu.has_task],['文档',feishuState.feishu.has_docs]].filter(([,ok])=>ok).map(([name])=>name).join('、')||'尚无已确认权限'}</p>}</>}
            {['Bilibili','YouTube'].includes(service)&&<div className="settings-card">
              <VideoLogin key={service} info={info} debug={debug} platformFilter={service} />
              <details><summary>视频读取配置</summary><VideoSettings info={info} debug={debug} /></details>
            </div>}
            {activities.some(a=>a.service===service)&&<section className="service-activity"><h3>本次活动</h3>{activities.filter(a=>a.service===service).map(a=><p key={a.time}><time>{checkTime(a.time)}</time>{a.line}</p>)}</section>}
            {service==='feishu'&&<details><summary>飞书机器人配置</summary><FeishuAgentPane info={info} debug={debug}/></details>}
            </section></div>
          </div>}

          <div hidden={section !== "usage"}>
            <PersonalUsagePane info={info} debug={debug} visible={section === "usage"} />
          </div>

          <div hidden={section !== "about"}>
            <ReleaseSettings info={info} onShowIntro={releaseIntro.show} />

          </div>
        </div>
      </main>


      {releaseIntro.open && !showGuide && !cropSrc ? (
        <ReleaseIntro daily={releaseIntro.daily} onDaily={releaseIntro.setDaily} onClose={releaseIntro.close} error={releaseIntro.preferenceError} />
      ) : null}

      {cropSrc ? (
        <div className="settings-crop-layer">
          <div className="settings-crop-frame" style={{ width: cropFrame.w || undefined, height: cropFrame.h || undefined }}>
            <BackgroundCrop
              src={cropSrc}
              error={cropError}
              onConfirm={confirmCrop}
              onCancel={() => { setCropSrc(""); setCropError(""); }}
              onBroken={() => { setCropSrc(""); setCropError(""); setBgError("这张图打不开。恢复：换一张 png、jpg 或 webp。"); }}
            />
          </div>
        </div>
      ) : null}
      {!target&&<WindowCloseButton />}
    </div>
  );
}
