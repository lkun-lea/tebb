import { useEffect, useState } from 'react';
import { useReducedMotion } from 'framer-motion';

export function useUiReducedMotion() {
  const system = useReducedMotion();
  const read = () => typeof document !== 'undefined' && document.documentElement?.dataset.reduceMotion === 'true';
  const [manual, setManual] = useState(read);
  useEffect(() => {
    if (typeof MutationObserver === 'undefined' || !document.documentElement) return;
    const observer = new MutationObserver(() => setManual(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-motion'] });
    setManual(read());
    return () => observer.disconnect();
  }, []);
  return !!system || manual;
}
