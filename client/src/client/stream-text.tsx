import { useState } from 'react';
import { Markdown, loosenQuotedEmphasis } from './Markdown';
import { advanceStream, initialStream } from './stream-arrival';
import { CopyButton } from './copy-button';

// Preserve the prefix; animate only text newly received from actual model events.
export function StreamText({ text, active, externalLinks = false, copyable = false }: { text: string; active: boolean; externalLinks?: boolean; copyable?: boolean }) {
  const source = loosenQuotedEmphasis(text);
  const [snapshot, setSnapshot] = useState(() => initialStream(source, active));
  let current = snapshot;
  if (source !== snapshot.text || active !== snapshot.active) {
    current = advanceStream(snapshot, source, active, performance.now());
    setSnapshot(current);
  }
  return <div className={active ? 'tebb-stream-text' : undefined}><Markdown text={source} externalLinks={externalLinks} reveal={active ? current.arrivals : undefined} />{active && <i className="tebb-stream-cursor" aria-label="正在输出" />}{copyable && text && <CopyButton text={text} label="复制回复" className="tebb-reply-copy" />}</div>;
}
