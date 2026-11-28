import type {LocalSource} from './local-sources';

type ActiveDraft = {
  id: string;
  title: string;
  owner: string;
  noteKeys: Set<string>;
  attach: (source: LocalSource) => void;
};

export function createNoteDraftPort() {
  let current: ActiveDraft | null = null;
  const listeners = new Set<() => void>();
  return {
    read: () => current,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    publish(next: ActiveDraft | null) {
      current = next;
      listeners.forEach(listener => listener());
    },
  };
}
export type NoteDraftPort = ReturnType<typeof createNoteDraftPort>;
