// Unit mass, zero initial velocity: roots of x'' + 80x' + 1200x = 0 are -20/-60.
// Sample the same overdamped spring for libraries that accept a CSS easing only.
export const DRAG_SPRING = { type: 'spring' as const, stiffness: 1200, damping: 80, mass: 1 };
export const DRAG_SETTLE_MS = 500;
export function dragProgress(seconds: number) {
  return 1 - (3 * Math.exp(-20 * Math.max(0, seconds)) - Math.exp(-60 * Math.max(0, seconds))) / 2;
}
export const DRAG_EASING = `linear(${Array.from({length: 51}, (_, i) =>
  i === 50 ? '1' : dragProgress(i / 100).toFixed(6)).join(',')})`;
export const DRAG_DROP = { duration: DRAG_SETTLE_MS, easing: DRAG_EASING };
