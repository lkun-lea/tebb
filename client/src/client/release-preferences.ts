import {accountStorage} from './account-storage';
export const RELEASE_STORAGE_KEY = "desk-companion-release-preferences";
export type ReleasePreferences = { daily: boolean; seen: Record<string, string> };

export function localDay(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function readReleasePreferences(): ReleasePreferences {
  try {
    const saved = JSON.parse(accountStorage().getItem(RELEASE_STORAGE_KEY) || "{}");
    const seen: Record<string, string> = {};
    if (saved?.seen && typeof saved.seen === "object") for (const [version, day] of Object.entries(saved.seen)) {
      if (/^\d+\.\d+\.\d+$/.test(version) && typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day)) seen[version] = day;
    }
    return { daily: saved?.daily === true, seen };
  } catch { return { daily: false, seen: {} }; }
}

export function shouldShowRelease(prefs: ReleasePreferences, version: string, day = localDay()): boolean {
  return !prefs.daily || prefs.seen[version] !== day;
}

export function saveReleasePreferences(prefs: ReleasePreferences): string {
  try { accountStorage().setItem(RELEASE_STORAGE_KEY, JSON.stringify(prefs)); return ""; }
  catch { return "每日一次的偏好暂时无法保存，本次仍可正常使用。"; }
}
