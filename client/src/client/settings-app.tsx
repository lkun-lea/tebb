import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
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
import { ReminderSettings } from "./reminders";
import { PersonalUsagePane } from "./usage-center";
import { ReleaseIntro, ReleaseSettings, useReleaseIntro } from "./release";
import { ModelNetworkSettings } from "./model-network";
import { SearchSettings } from "./search-settings";
import { FeishuPane, feishuLoggedIn } from "./feishu";
import { FeishuAgentPane } from "./feishu-agent";
import { VideoLogin, VideoSettings } from "./video";
import { StatusGrid, loadingStatuses, statusError, statusFromPayload, STATUS_KINDS, type StatusView } from "./status";
import { AgentDebugDialog } from "./agent-debug";
import { readDeveloperMode } from "./companion-ui";
import { WindowCloseButton } from "./window-chrome";
import "./settings-window.css";

const PersonalizationPane = lazy(() => import("./personalization").then(module => ({ default: module.PersonalizationPane })));

type SettingsSection = "assistant" | "account" | "personalization" | "connections" | "appearance" | "usage" | "about";

type NavItem = { id: SettingsSection; label: string; keywords: string };

// 左侧导航：现有 7 个分类归入三个大分组，搜索按名称与关键词过滤。
const SETTINGS_NAV: { id: string; label: string; items: NavItem[] }[] = [
  {
    id: "general", label: "通用", items: [
      { id: "assistant", label: "模型与人设", keywords: "模型 api base url key 人设 提示词 提醒 引导" },
      { id: "appearance", label: "界面外观", keywords: "主题 深色 浅色 背景 壁纸 外观" },
    ],
  },
  {
    id: "data", label: "连接与数据", items: [
      { id: "connections", label: "连接与网络", keywords: "飞书 github 网络代理 搜索 视频 登录 连接" },
      { id: "usage", label: "个人使用", keywords: "用量 费用 统计 token 成本" },
    ],
  },
  {
    id: "account", label: "账号与关于", items: [
      { id: "account", label: "账号与空间", keywords: "账号 账户 数据目录 空间" },
      { id: "personalization", label: "个人资料", keywords: "画像 个人资料 记忆 个性化" },
      { id: "about", label: "版本与诊断", keywords: "版本 更新 诊断 调试 关于" },
    ],
  },
];

const SECTION_META: Record<SettingsSection, { title: string; blurb: string }> = {
  assistant: { title: "模型与人设", blurb: "管理模型服务、系统提示词与会前提醒。" },
  account: { title: "账号与空间", blurb: "管理本机账号与数据目录。" },
  personalization: { title: "个人资料", blurb: "查看和修正 tebb 对你的了解。" },
  connections: { title: "连接与网络", blurb: "管理飞书、GitHub、搜索与视频来源的连接。" },
  appearance: { title: "界面外观", blurb: "调整主题与工作台背景。" },
  usage: { title: "个人使用", blurb: "查看调用次数、费用估算与明细。" },
  about: { title: "版本与诊断", blurb: "查看版本信息、检查更新与调用调试。" },
};

const SECTIONS: SettingsSection[] = ["assistant", "account", "personalization", "connections", "appearance", "usage", "about"];

function initialSection(): SettingsSection {
  const value = new URLSearchParams(window.location.search).get("section");
  return SECTIONS.includes(value as SettingsSection) ? value as SettingsSection : "assistant";
}

// 跨窗口定位：主窗口入口（如 tebb-open-personalization）通过事件把设置窗口切到目标分类。
type SectionTarget = { section?: string; profile?: string };

function focusMainWindow() {
  if (isTauri()) void invoke("show_main").catch(() => {});
  else window.opener?.focus?.();
}

export function SettingsApp() {
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
  const [showGuide, setShowGuide] = useState(false);
  const [guideModel, setGuideModel] = useState<ModelSetupState | null>(null);
  const [statuses, setStatuses] = useState<StatusView[]>([]);
  const [bootError, setBootError] = useState("");
  const [developerMode] = useState(readDeveloperMode);
  const [agentDebugOpen, setAgentDebugOpen] = useState(false);
  const releaseIntro = useReleaseIntro(!!setupStatus && !setupStatus.show && !showGuide && !cropSrc && !debugKind);

  const models = useModelSettings({ info, debug });
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
    const methods: Record<string, string> = { feishu: "load_feishu", github: "load_github" };
    for (const kind of STATUS_KINDS) {
      void rpc<unknown>(info, methods[kind])
        .then((data) => {
          if (kind === "feishu") return; // 飞书卡片由 useFeishuConnection 持有
          setStatuses((cur) => cur.map((card) => (card.kind === kind ? statusFromPayload(kind, data) : card)));
        })
        .catch((err: unknown) => {
          setStatuses((cur) => cur.map((card) => (card.kind === kind ? statusError(kind, String(err)) : card)));
        });
    }
  }, [section, info, debugKind]);

  useEffect(() => {
    if (feishuState.feishu) {
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

  // 跨窗口定位事件：主窗口或其它窗口请求切到指定分类。
  useEffect(() => {
    if (!isTauri()) return;
    let dispose: (() => void) | undefined;
    void listen<SectionTarget>("settings-section", (event) => {
      const target = event.payload || {};
      if (SECTIONS.includes(target.section as SettingsSection)) setSection(target.section as SettingsSection);
      if (target.profile) setProfileTarget({ id: target.profile, nonce: Date.now() });
    }).then((unlisten) => { dispose = unlisten; });
    // 新开窗口时事件可能早于监听注册：向壳层取一次暂存目标。
    void invoke<SectionTarget>("take_settings_target").then((target) => {
      if (SECTIONS.includes(target?.section as SettingsSection) && !new URLSearchParams(window.location.search).get("section")) {
        setSection(target.section as SettingsSection);
      }
      if (target?.profile && !new URLSearchParams(window.location.search).get("profile")) {
        setProfileTarget({ id: target.profile, nonce: Date.now() });
      }
    }).catch(() => {});
    return () => dispose?.();
  }, []);

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

  const filtered = query.trim() !== "";
  const meta = SECTION_META[section];

  return (
    <div className="settings-window" data-settings-shell="1" data-settings-section={section}>
      <aside aria-label="设置导航" data-tauri-drag-region>
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
                  onClick={() => setSection(item.id)}
                >
                  {item.label}
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
          {bootError ? <p role="alert" className="text-sm text-destructive">连不上本地助手：{bootError}。恢复：重启客户端后重试。</p> : null}

          {section === "assistant" ? <ReminderSettings info={info} debug={debug} /> : null}
          {section === "account" ? <AccountsPane info={info} debug={debug} /> : null}
          {section === "personalization" ? (
            <Suspense fallback={<p role="status">正在打开个人画像…</p>}>
              <PersonalizationPane info={info} debug={debug} target={profileTarget} onInspect={() => setAgentDebugOpen(true)} />
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
              onToggleTheme={() => setDark((v) => !v)}
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

          <div hidden={section !== "connections"}>
            <ModelNetworkSettings info={info} debug={debug} />
            <SearchSettings info={info} debug={debug} />
            <StatusGrid cards={statuses} onOpenFeishu={() => { setSection("connections"); void feishuState.ensureFeishu(); }} />
            <FeishuPane snap={feishuState.feishu} busy={feishuState.feishuBusy} debug={debug} onLogin={() => void feishuState.startFeishuLogin()} onLogout={() => void feishuState.logoutFeishu()} />
            <FeishuAgentPane info={info} debug={debug} />
            <div className="settings-card">
              <h2>视频来源与登录</h2>
              <p>学习笔记在自动化工作流中编排；这里管理读取来源所需的连接。</p>
              <VideoLogin info={info} debug={debug} />
              <VideoSettings info={info} debug={debug} />
            </div>
          </div>

          <div hidden={section !== "usage"}>
            <PersonalUsagePane info={info} debug={debug} visible={section === "usage"} />
          </div>

          <div hidden={section !== "about"}>
            <ReleaseSettings info={info} onShowIntro={releaseIntro.show} />
            {developerMode ? (
              <div className="settings-card">
                <h2>调用调试</h2>
                <button type="button" className="desk-btn desk-btn-lg" onClick={() => setAgentDebugOpen(true)}>打开调用调试</button>
              </div>
            ) : null}
          </div>
        </div>
      </main>

      {showGuide && info && setupStatus ? (
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
            else focusMainWindow();
          }}
        />
      ) : null}

      {agentDebugOpen ? <AgentDebugDialog info={info} debug={debug} onClose={() => setAgentDebugOpen(false)} /> : null}
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
      <WindowCloseButton />
    </div>
  );
}
