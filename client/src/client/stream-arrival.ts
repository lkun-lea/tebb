export type StreamArrival = { offset: number; value: string; at: number };
export type StreamSnapshot = { text: string; active: boolean; arrivals: StreamArrival[]; tailOffset: number };
export const STREAM_DURATION = 90;
export const STREAM_STAGGER = 30;
export const STREAM_WINDOW = 8;
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
export function graphemes(text: string) { return segmenter.segment(text); }
export function initialStream(text: string, active: boolean): StreamSnapshot {
  let tailOffset = 0;
  for (const part of graphemes(text)) tailOffset = part.index;
  return { text, active, arrivals: [], tailOffset };
}

// Keep only the live visual tail. The complete response is always available to Markdown.
export function advanceStream(previous: StreamSnapshot, text: string, active: boolean, now: number): StreamSnapshot {
  if (!active || !text.startsWith(previous.text)) return initialStream(text, active);
  const added: StreamArrival[] = [];
  let tailOffset = previous.tailOffset;
  let extendedTail = false;
  for (const part of graphemes(text.slice(previous.tailOffset))) {
    tailOffset = previous.tailOffset + part.index;
    if (part.index === 0 && part.segment !== previous.text.slice(previous.tailOffset)) extendedTail = true;
    // A joining mark/surrogate/ZWJ may extend the prior glyph; do not split or replay it.
    if (tailOffset < previous.text.length) continue;
    if (/^\s+$/u.test(part.segment)) continue;
    added.push({ offset: tailOffset, value: part.segment, at: 0 });
    if (added.length > STREAM_WINDOW) added.shift();
  }
  const live = previous.arrivals.filter(item => item.at + STREAM_DURATION > now && !(extendedTail && item.offset === previous.tailOffset));
  const first = Math.max(now, (live.at(-1)?.at ?? now - STREAM_STAGGER) + STREAM_STAGGER);
  const overflow = live.length + added.length > STREAM_WINDOW || first + (added.length - 1) * STREAM_STAGGER > now + (STREAM_WINDOW - 1) * STREAM_STAGGER;
  const scheduled = added.map((item, index) => ({ ...item, at: (overflow ? now : first) + index * STREAM_STAGGER }));
  return { text, active, arrivals: [...(overflow ? [] : live), ...scheduled], tailOffset };
}
