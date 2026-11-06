import { useEffect, useRef, useState, type RefObject, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { animate, type AnimationPlaybackControls } from 'framer-motion';
import { DRAG_SPRING } from './drag-motion';
import { useUiReducedMotion } from './use-ui-reduced-motion';

const MIN = 280;
export function previewMaxWidth(containerWidth: number) { return Math.min(680, Math.max(MIN, containerWidth - 386)); }
export function snapPreviewWidth(width: number, max: number) {
  return width - MIN <= 24 ? MIN : max - width <= 24 ? max : width;
}

// Owns only preview geometry; tab state, browser layout and persistence stay with SideWorkspace.
export function useWorkspaceResize(box: RefObject<HTMLDivElement>, visible: boolean) {
  const reduce = useUiReducedMotion();
  const reduced = useRef(reduce); reduced.current=reduce;
  const [width, renderWidth] = useState(440), [max, setMax] = useState(680);
  const value = useRef(width), animation = useRef<AnimationPlaybackControls>();
  const destination = useRef(width);
  const available = useRef(680);
  const drag = useRef<{ cancel: () => void; dispose: () => void }>();
  const write = (next: number) => { value.current = next; renderWidth(next); };
  function setWidth(next: number) {
    animation.current?.stop();
    const target = Math.min(previewMaxWidth(box.current?.getBoundingClientRect().width || 1066), Math.max(MIN, next));
    destination.current = target;
    if (reduced.current) write(target);
    else animation.current = animate(value.current, target, { ...DRAG_SPRING, onUpdate: write });
  }
  useEffect(() => {
    if (!visible) { drag.current?.cancel(); animation.current?.stop(); return; }
    const node = box.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const resize = () => {
      const limit = previewMaxWidth(node.getBoundingClientRect().width);
      setMax(limit);
      if (available.current !== limit) {
        drag.current?.cancel(); animation.current?.stop(); animation.current=undefined;
        available.current=limit; destination.current=Math.min(value.current,limit); write(destination.current);
      }
    };
    resize();
    const observer = new ResizeObserver(resize); observer.observe(node);
    return () => observer.disconnect();
  }, [visible, box]);
  useEffect(() => { if (reduce && animation.current) { animation.current.stop(); write(destination.current); } }, [reduce]);
  useEffect(() => () => { drag.current?.dispose(); animation.current?.stop(); }, []);

  function onPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || drag.current) return;
    event.preventDefault(); animation.current?.stop(); animation.current=undefined;
    const handle = event.currentTarget, pointer = event.pointerId, before = value.current;
    const origin = event.clientX;
    handle.focus({ preventScroll: true }); handle.setPointerCapture(pointer);
    const move = (e: PointerEvent) => {
      if (e.pointerId !== pointer || !box.current) return;
      const limit = previewMaxWidth(box.current.getBoundingClientRect().width);
      // Follow the delta, preserving the exact width even when grabbed off the handle centre.
      write(Math.min(limit, Math.max(MIN, before + origin - e.clientX)));
    };
    const dispose = () => {
      drag.current = undefined;
      handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', interrupted); handle.removeEventListener('lostpointercapture', interrupted);
      window.removeEventListener('keydown', key, true); window.removeEventListener('blur', cancel);
      if (handle.hasPointerCapture(pointer)) handle.releasePointerCapture(pointer);
    };
    const cancel = () => { dispose(); write(before); };
    const interrupted = (e: PointerEvent) => { if (e.pointerId === pointer) cancel(); };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== pointer) return;
      move(e); dispose();
      setWidth(snapPreviewWidth(value.current, previewMaxWidth(box.current!.getBoundingClientRect().width)));
    };
    const key = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault(); e.stopPropagation(); cancel();
    };
    drag.current = { cancel, dispose };
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', interrupted); handle.addEventListener('lostpointercapture', interrupted);
    window.addEventListener('keydown', key, true); window.addEventListener('blur', cancel);
  }
  function onKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (drag.current || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const limit = previewMaxWidth(box.current?.getBoundingClientRect().width || 1066);
    setWidth(event.key === 'Home' ? MIN : event.key === 'End' ? limit : value.current + (event.key === 'ArrowLeft' ? 20 : -20));
  }
  return { width, setWidth, handleProps: { onPointerDown, onKeyDown, role: 'separator', 'aria-orientation': 'vertical' as const,
    'aria-valuemin': MIN, 'aria-valuemax': max, 'aria-valuenow': Math.round(width), 'aria-valuetext': `侧栏宽度 ${Math.round(width)} 像素` } };
}
