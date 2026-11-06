import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Check, Copy } from 'lucide-react';
import './copy-button.css';

const COPY_FEEDBACK_MS = 2500;
const CONFIRM_SPRING = { type: 'spring', stiffness: 380, damping: 18, mass: 1 } as const;
type Props = { text: string | (() => string | Promise<string>); label?: string; className?: string; disabled?: boolean; iconOnly?: boolean };

export function CopyButton({ text, label = '复制', className = '', disabled = false, iconOnly = false }: Props) {
  const [state, setState] = useState({ copied: false, pending: false, error: '', revision: 0 });
  const alive = useRef(false), request = useRef(0), timer = useRef<ReturnType<typeof setTimeout>>();
  const reduce = useReducedMotion();
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current++; clearTimeout(timer.current); }; }, []);
  async function copy() {
    if (disabled) return;
    const id = ++request.current;
    clearTimeout(timer.current);
    setState(previous => ({ ...previous, copied: false, pending: true }));
    try {
      const value = typeof text === 'function' ? await text() : text;
      if (!alive.current || request.current !== id) return;
      await navigator.clipboard.writeText(value);
      if (!alive.current || request.current !== id) return;
      setState({ copied: true, pending: false, error: '', revision: id });
      timer.current = setTimeout(() => { if (alive.current && request.current === id) setState(previous => ({ ...previous, copied: false })); }, COPY_FEEDBACK_MS);
    } catch (error) {
      if (alive.current && request.current === id) setState(previous => ({ ...previous, copied: false, pending: false, error: `复制失败：${String(error)}` }));
    }
  }
  return <span className="ui-copy-control">
    <button type="button" className={`ui-copy-button ${className}`} aria-label={label} title={label} disabled={disabled} aria-busy={state.pending || undefined} data-copied={state.copied || undefined} onClick={() => void copy()}>
      <span className="ui-copy-icon" aria-hidden="true"><Copy size={14} className={state.copied ? 'ui-copy-original is-hidden' : 'ui-copy-original'} />
        <motion.span key={state.revision} className="ui-copy-check" initial={{ scale: .7, opacity: 0 }} animate={{ scale: state.copied ? 1 : .9, opacity: state.copied ? 1 : 0 }} transition={reduce ? { duration: 0 } : state.copied ? CONFIRM_SPRING : { duration: .15 }}><Check size={14} /></motion.span>
      </span>{!iconOnly && <span>{label}</span>}
    </button>
    <span className="sr-only" role="status">{state.copied ? '已复制' : ''}</span>
    {state.error && <span className="ui-copy-error" role="alert">{state.error}</span>}
  </span>;
}
