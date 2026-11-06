// A small native vector companion. No external model, Core or texture is needed.
export const PET_PALETTES = {
  paper: { name: '纸白', body: '#eee9dc', shade: '#d4caba', line: '#3e4443', accent: '#be9c60' },
  sage: { name: '鼠尾草', body: '#aebca8', shade: '#819980', line: '#303f39', accent: '#e5dfc4' },
  ink: { name: '墨黑', body: '#414a51', shade: '#2e353b', line: '#dedbcf', accent: '#b9c9ba' },
} as const;
export type BuiltinSkin = keyof typeof PET_PALETTES;
export function isBuiltinSkin(value: string): value is BuiltinSkin { return Object.hasOwn(PET_PALETTES, value); }

// The seven semantic motion groups the Live2D skins already declare. Mapping them onto eye
// shapes is a presentation-layer concern, so the state bus in main.ts stays untouched.
export const PET_MOODS = ['Idle', 'Busy', 'Fail', 'Talk', 'Done', 'Tap', 'Wish'] as const;
export type PetMood = (typeof PET_MOODS)[number];
export function isPetMood(value: string): value is PetMood { return (PET_MOODS as readonly string[]).includes(value); }

// Moods that play once and then settle back to Idle, in milliseconds.
const ONE_SHOT: Partial<Record<PetMood, number>> = { Done: 900, Tap: 700, Fail: 2600 };

// The whole expression bandwidth of tebb lives in two shapes. Everything below is pure geometry.
export function petEyes(mood: PetMood, line: string): string {
  switch (mood) {
    case 'Busy': // squinting, focused
      return '<rect x="20.5" y="30.2" width="8" height="2.6" rx="1.3"/><rect x="35.5" y="30.2" width="8" height="2.6" rx="1.3"/>';
    case 'Fail': // short slashes, inner ends raised, like a deflated brow
      return `<rect x="21.5" y="31.8" width="6" height="2.4" rx="1.2" transform="rotate(-14 24.5 33)"/>`
        + `<rect x="36.5" y="31.8" width="6" height="2.4" rx="1.2" transform="rotate(14 39.5 33)"/>`;
    case 'Talk': // slightly shorter, blinks on a speaking rhythm
      return '<rect x="22" y="27" width="5" height="9" rx="2.5"/><rect x="37" y="27" width="5" height="9" rx="2.5"/>';
    case 'Done': // closed, curving up
      return `<path d="M20.5 34.2Q24.5 28.6 28.5 34.2" fill="none" stroke="${line}" stroke-width="2.6" stroke-linecap="round"/>`
        + `<path d="M35.5 34.2Q39.5 28.6 43.5 34.2" fill="none" stroke="${line}" stroke-width="2.6" stroke-linecap="round"/>`;
    case 'Tap': // startled: round, wider apart
      return '<rect x="20.3" y="28.3" width="6.4" height="6.4" rx="3.2"/><rect x="37.3" y="28.3" width="6.4" height="6.4" rx="3.2"/>';
    case 'Wish': // asymmetric, a raised eyebrow without having eyebrows
      return '<rect x="22" y="26" width="5" height="11" rx="2.5"/><rect x="37" y="31" width="5" height="5" rx="2.5"/>';
    default:
      return '<rect x="22" y="26" width="5" height="11" rx="2.5"/><rect x="37" y="26" width="5" height="11" rx="2.5"/>';
  }
}

export function petSvg(skin: BuiltinSkin, mood: PetMood = 'Idle'): string {
  const p = PET_PALETTES[skin];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" aria-label="tebb 圆点 · ${p.name}" role="img">
    <circle class="pet-body" cx="32" cy="32" r="29.5" fill="${p.body}" stroke="${p.shade}" stroke-width="1.5"/>
    <g class="pet-eyes" fill="${p.line}">${petEyes(mood, p.line)}</g></svg>`;
}

export const PET_STYLE = `.builtin-pet svg{width:100%;height:100%;overflow:visible;pointer-events:none}
.builtin-pet .pet-body{transform-origin:32px 32px;animation:pet-breathe 3.6s ease-in-out infinite}
.builtin-pet .pet-eyes{transform-origin:32px 31px;animation:pet-blink 6.3s infinite}
.builtin-pet[data-active]{filter:drop-shadow(0 0 5px #aebca888)}
.builtin-pet[data-mood="Busy"] .pet-body{animation-duration:1.8s}
.builtin-pet[data-mood="Busy"] .pet-eyes{animation:pet-scan 2.4s ease-in-out infinite}
.builtin-pet[data-mood="Fail"] .pet-body{animation:none;transform:translateY(2px)}
.builtin-pet[data-mood="Talk"] .pet-eyes{animation:pet-blink .9s infinite}
.builtin-pet[data-mood="Done"] .pet-body{animation:pet-hop .9s ease}
.builtin-pet[data-mood="Tap"] .pet-body{animation:pet-startle .7s ease}
.builtin-pet[data-mood="Wish"] .pet-body{animation:pet-sway 2.6s ease-in-out infinite}
@keyframes pet-breathe{50%{transform:translateY(-3px) scale(1.025)}}
@keyframes pet-blink{0%,43%,47%,100%{transform:scaleY(1)}45%{transform:scaleY(.08)}}
@keyframes pet-scan{0%,100%{transform:translateX(-1.2px)}50%{transform:translateX(1.2px)}}
@keyframes pet-sway{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}}
@keyframes pet-hop{0%{transform:none}25%{transform:translateY(2px) scale(1.08,.9)}60%{transform:translateY(-9px) scale(.95,1.06)}100%{transform:none}}
@keyframes pet-startle{0%{transform:none}25%{transform:scale(1.09,.93)}60%{transform:scale(.97,1.05)}100%{transform:none}}
@media(prefers-reduced-motion:reduce){.builtin-pet .pet-body,.builtin-pet .pet-eyes{animation:none!important}}`;

export function mountBuiltinPet(canvas: HTMLCanvasElement, skin: BuiltinSkin, size = 48) {
  const palette = PET_PALETTES[skin];
  const host = document.createElement('div');
  host.className = 'builtin-pet'; host.innerHTML = petSvg(skin);
  host.style.cssText = `position:absolute;width:${size}px;height:${size}px;left:50%;bottom:20px;transform:translateX(-50%);user-select:none;`;
  const style = document.createElement('style');
  style.textContent = PET_STYLE;
  host.appendChild(style); canvas.parentElement!.appendChild(host); canvas.style.visibility = 'hidden';
  let timer: ReturnType<typeof setTimeout> | undefined;
  let mood: PetMood = 'Idle';
  const apply = (next: PetMood) => {
    clearTimeout(timer);
    mood = next; host.dataset.mood = next;
    const g = host.querySelector('.pet-eyes');
    if (g) { g.innerHTML = petEyes(next, palette.line); g.setAttribute('fill', palette.line); }
    const ms = ONE_SHOT[next];
    if (ms) timer = setTimeout(() => apply('Idle'), ms);
  };
  apply('Idle');
  return {
    bounds() { const r = host.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; },
    active(value: boolean) {
      host.toggleAttribute('data-active', value);
      if (value) { if (mood === 'Idle') apply('Busy'); }
      else if (mood === 'Busy') apply('Idle');
    },
    mood: apply,
    play(group: string) { apply(isPetMood(group) ? group : 'Tap'); },
    destroy() { clearTimeout(timer); host.remove(); canvas.style.visibility = ''; },
  };
}
