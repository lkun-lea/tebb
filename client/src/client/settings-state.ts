import { useEffect, useRef, useState } from "react";
import { rpc, type BackendInfo } from "./api";
import {
  MODELS_FIXTURE,
  PERSONA_FIXTURE,
  type ModelEntry,
  type ModelList,
  type ModelPublic,
  type PersonaPublic,
} from "./settings";
import { FEISHU_LOGGED_OUT, FEISHU_WAITING } from "./debug";
import { feishuLoggedIn, feishuWaiting, type FeishuSnap } from "./feishu";

// 设置窗口持有的模型与人设状态：从 App.tsx 原样迁出，供独立设置窗口使用。
// 主窗口只保留对话所需的模型列表与切换（useModel），不再拥有编辑表单状态。
export function useModelSettings(props: {
  info: BackendInfo | null;
  debug: boolean;
}) {
  const { info, debug } = props;
  const [modelItems, setModelItems] = useState<ModelEntry[]>(() => (debug ? MODELS_FIXTURE.items : []));
  const [activeModelId, setActiveModelId] = useState(() => (debug ? MODELS_FIXTURE.active : ""));
  const [editingModelId, setEditingModelId] = useState(() => (debug ? MODELS_FIXTURE.active : ""));
  const [modelForm, setModelForm] = useState<ModelPublic | null>(() => {
    if (!debug) return null;
    const item = MODELS_FIXTURE.items.find((row) => row.id === MODELS_FIXTURE.active);
    return item ? { ok: true, base_url: item.base_url, model: item.model, has_key: item.has_key } : null;
  });
  const [personaForm, setPersonaForm] = useState<PersonaPublic | null>(debug ? PERSONA_FIXTURE : null);
  const [settingsError, setSettingsError] = useState("");
  const [settingsNotice, setSettingsNotice] = useState("");
  const [personaError, setPersonaError] = useState("");
  const [personaNotice, setPersonaNotice] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [keyEpoch, setKeyEpoch] = useState(0);

  function formFromEntry(item: ModelEntry): ModelPublic {
    return { ok: true, base_url: item.base_url, model: item.model, has_key: item.has_key };
  }

  function rememberModels(data: ModelList, editId = "") {
    setModelItems(data.items);
    setActiveModelId(data.active);
    const nextEdit = data.items.some((item) => item.id === editId) ? editId : data.active;
    setEditingModelId(nextEdit);
    const item = data.items.find((row) => row.id === nextEdit);
    setModelForm(item ? formFromEntry(item) : null);
    setKeyEpoch((n) => n + 1);
  }

  useEffect(() => {
    if (debug) {
      setPersonaForm(PERSONA_FIXTURE);
      setSettingsError("");
      setPersonaError("");
      return;
    }
    if (!info) {
      setSettingsError("还没有连上本地后端。恢复：重启客户端。");
      return;
    }
    let gone = false;
    void (async () => {
      try {
        const data = await rpc<ModelList>(info, "load_models");
        if (gone) return;
        if (!data.ok) throw new Error(data.error || "模型列表读取失败。");
        rememberModels(data);
        setSettingsError("");
      } catch (err) {
        if (!gone) setSettingsError(String(err));
      }
      try {
        const data = await rpc<PersonaPublic>(info, "load_persona");
        if (gone) return;
        if (!data.ok) throw new Error(data.error || "系统提示词读取失败。");
        setPersonaForm(data);
        setPersonaError("");
      } catch (err) {
        if (!gone) setPersonaError(String(err));
      }
    })();
    return () => {
      gone = true;
    };
  }, [info, debug]);

  function settingsPayload(draft: { base_url: string; model: string; api_key: string }) {
    const base_url = draft.base_url.trim();
    const model = draft.model.trim();
    const api_key = draft.api_key.trim();
    return { base_url, model, api_key };
  }

  function editModel(id: string) {
    const item = modelItems.find((row) => row.id === id);
    if (!item) return;
    setEditingModelId(id);
    setModelForm(formFromEntry(item));
    setKeyEpoch((n) => n + 1);
    setSettingsError("");
    setSettingsNotice("");
  }

  async function deleteModel(id: string) {
    if (modelItems.length <= 1) {
      setSettingsNotice("");
      setSettingsError("至少留一个模型。要换的话直接改这一条。");
      return;
    }
    if (debug) {
      const items = modelItems.filter((row) => row.id !== id);
      const active = activeModelId === id ? items[0].id : activeModelId;
      const edit = editingModelId === id ? active : editingModelId;
      const next = items.find((row) => row.id === edit) || items[0];
      setModelItems(items);
      setActiveModelId(active);
      setEditingModelId(next.id);
      setModelForm(formFromEntry(next));
      setKeyEpoch((n) => n + 1);
      setSettingsError("");
      setSettingsNotice("调试样本，未删除磁盘上的模型。");
      return;
    }
    if (!info) {
      setSettingsError("还没有连上本地后端。恢复：重启客户端。");
      return;
    }
    setSettingsBusy(true);
    setSettingsError("");
    setSettingsNotice("");
    try {
      const data = await rpc<ModelList>(info, "delete_model_entry", { model_id: id });
      if (!data.ok) throw new Error(data.error || "删除模型失败。");
      rememberModels(data, data.active);
      setSettingsNotice(data.message || "模型已删除。");
    } catch (err) {
      setSettingsError(String(err));
    } finally {
      setSettingsBusy(false);
    }
  }

  async function saveSettings(draft: { id: string; base_url: string; model: string; api_key: string }) {
    const { base_url, model, api_key } = settingsPayload(draft);
    const sourceId = draft.id || editingModelId;
    const editing = modelItems.find((row) => row.id === sourceId);
    if (!base_url) {
      setSettingsNotice("");
      setSettingsError("API 地址不能为空。");
      return;
    }
    if (!model) {
      setSettingsNotice("");
      setSettingsError("模型名不能为空。");
      return;
    }
    if (!api_key && !editing?.has_key) {
      setSettingsNotice("");
      setSettingsError("API Key 不能为空。要沿用已有 Key，先在列表里点一条。");
      return;
    }
    if (debug) {
      const id = draft.id || `local-${Date.now()}`;
      const nextItem = { id, base_url, model, has_key: true };
      const items = draft.id
        ? modelItems.map((row) => (row.id === draft.id ? nextItem : row))
        : [...modelItems, nextItem];
      const active = activeModelId || id;
      setModelItems(items);
      setActiveModelId(active);
      setEditingModelId(id);
      setModelForm({ ok: true, base_url, model, has_key: true });
      setSettingsError("");
      setSettingsNotice("调试样本，未写入模型。");
      setKeyEpoch((n) => n + 1);
      return;
    }
    if (!info) {
      setSettingsError("还没有连上本地后端。恢复：重启客户端。");
      return;
    }
    setSettingsBusy(true);
    setSettingsError("");
    setSettingsNotice("");
    try {
      const data = await rpc<ModelList>(info, "save_model_entry", {
        payload: { id: draft.id, base_url, model, api_key, copy_key_from: draft.id ? "" : sourceId },
      });
      if (!data.ok) throw new Error(data.error || "模型保存失败。");
      const created = data.items.find((row) => !modelItems.some((old) => old.id === row.id));
      rememberModels(data, draft.id || created?.id || data.active);
      setSettingsNotice(data.message || "模型已保存。");
    } catch (err) {
      setSettingsError(String(err));
    } finally {
      setSettingsBusy(false);
    }
  }

  async function savePersona(text: string) {
    const persona = text.trim();
    if (!persona) {
      setPersonaNotice("");
      setPersonaError("系统提示词不能为空。");
      return;
    }
    if (!personaForm) {
      setPersonaError("系统提示词还没读到。恢复：重新打开设置。");
      return;
    }
    if (debug) {
      setPersonaForm({ ...personaForm, persona });
      setPersonaError("");
      setPersonaNotice("调试样本，未写入人设。");
      return;
    }
    if (!info) {
      setPersonaError("还没有连上本地后端。恢复：重启客户端。");
      return;
    }
    setSettingsBusy(true);
    setPersonaError("");
    setPersonaNotice("");
    try {
      const data = await rpc<PersonaPublic>(info, "save_persona", {
        payload: {
          persona,
          max_steps: personaForm.max_steps,
          nudge_enabled: personaForm.nudge_enabled,
        },
      });
      if (!data.ok) throw new Error(data.error || "系统提示词保存失败。");
      setPersonaForm({ ...personaForm, persona });
      setPersonaNotice(data.message || "人设已保存。");
    } catch (err) {
      setPersonaError(String(err));
    } finally {
      setSettingsBusy(false);
    }
  }

  async function testSettings(draft: { base_url: string; model: string; api_key: string }): Promise<boolean> {
    const { base_url, model, api_key } = settingsPayload(draft);
    const editing = modelItems.find((row) => row.id === editingModelId);
    if (!base_url || !model || (!api_key && !editing?.has_key)) {
      setSettingsNotice("");
      setSettingsError("测试前先填 API 地址、模型名和 Key。");
      return false;
    }
    if (debug) {
      setSettingsError("");
      setSettingsNotice("调试样本，未测试连通。");
      return false;
    }
    if (!info) {
      setSettingsError("还没有连上本地后端。恢复：重启客户端。");
      return false;
    }
    setSettingsBusy(true);
    setSettingsError("");
    setSettingsNotice("");
    try {
      const data = await rpc<ModelPublic>(info, "test_model", {
        payload: { id: editingModelId, base_url, model, api_key },
      });
      if (!data.ok) throw new Error(data.error || "连通测试失败。");
      setSettingsNotice(data.message || "连通正常。");
      return true;
    } catch (err) {
      setSettingsError(String(err));
      return false;
    } finally {
      setSettingsBusy(false);
    }
  }

  return {
    modelItems, modelForm, editingModelId, keyEpoch,
    settingsError, settingsNotice, personaForm, personaError, personaNotice, settingsBusy,
    editModel, deleteModel, saveSettings, savePersona, testSettings,
  };
}

// 飞书连接状态：设置窗口「连接与网络」分类与使用引导共用。
// active 表示连接分类当前可见；调试模式使用内存样本，不发真实请求。
export function useFeishuConnection(props: { info: BackendInfo | null; debug: boolean; active: boolean }) {
  const { info, debug, active } = props;
  const [feishu, setFeishu] = useState<FeishuSnap | null>(debug ? FEISHU_LOGGED_OUT : null);
  const [feishuBusy, setFeishuBusy] = useState(false);
  const feishuBusyRef = useRef(false);

  function rememberFeishu(snap: FeishuSnap) {
    setFeishu(snap);
  }

  async function pullFeishu(backend: BackendInfo) {
    const snap = await rpc<FeishuSnap>(backend, "load_feishu");
    rememberFeishu(snap);
  }

  async function ensureFeishu() {
    if (debug) {
      setFeishu((cur) => cur || FEISHU_LOGGED_OUT);
      return;
    }
    if (!info) {
      setFeishu({ ok: false, logged_in: false, error: "还没有连上本地后端。恢复：重启客户端。" });
      return;
    }
    try {
      await pullFeishu(info);
    } catch (err) {
      setFeishu({ ok: false, logged_in: false, error: String(err) });
    }
  }

  async function startFeishuLogin() {
    if (feishuBusyRef.current || feishuWaiting(feishu)) return;
    feishuBusyRef.current = true;
    setFeishuBusy(true);
    try {
      if (debug) {
        rememberFeishu(FEISHU_WAITING);
        return;
      }
      if (!info) {
        setFeishu({ ok: false, logged_in: false, error: "还没有连上本地后端。恢复：重启客户端。" });
        return;
      }
      await rpc(info, "feishu_login");
      await pullFeishu(info);
    } catch (err) {
      setFeishu({ ...(feishu || {}), ok: false, logged_in: false, login_busy: false, error: String(err) });
    } finally {
      feishuBusyRef.current = false;
      setFeishuBusy(false);
    }
  }

  async function logoutFeishu() {
    if (feishuBusyRef.current || !feishuLoggedIn(feishu)) return;
    feishuBusyRef.current = true;
    setFeishuBusy(true);
    try {
      if (debug) {
        rememberFeishu(FEISHU_LOGGED_OUT);
        return;
      }
      if (!info) {
        setFeishu({ ...(feishu || {}), ok: false, error: "还没有连上本地后端。恢复：重启客户端。" });
        return;
      }
      await rpc(info, "feishu_logout");
      await pullFeishu(info);
    } catch (err) {
      setFeishu({ ...(feishu || {}), ok: false, error: String(err) });
    } finally {
      feishuBusyRef.current = false;
      setFeishuBusy(false);
    }
  }

  useEffect(() => {
    if (!active || debug || !info) return;
    void pullFeishu(info).catch(err => setFeishu({ ok: false, logged_in: false, error: String(err) }));
  }, [active, debug, info]);

  useEffect(() => {
    if (!active || debug || !info || !feishuWaiting(feishu)) return;
    const timer = window.setInterval(() => {
      if (feishuBusyRef.current) return;
      void pullFeishu(info).catch((err: unknown) => {
        setFeishu({ ok: false, logged_in: false, error: String(err) });
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [active, debug, info, feishu]);

  return { feishu, feishuBusy, rememberFeishu, ensureFeishu, startFeishuLogin, logoutFeishu };
}
