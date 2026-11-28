const image = document.querySelector("#demo");
const play = document.querySelector("#play");
const next = document.querySelector("#next");
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const frames = ["找到笔记卡", "展开正文", "草稿收到笔记引用"];
let frame = 0;
let timer;
function advance() {
  frame = (frame + 1) % frames.length;
  const url = "assets/notes-" + (frame + 1) + ".webp";
  image.src = url;
  image.alt = frames[frame];
  document.querySelector("#zoom").href = url;
  document.querySelector("#step").textContent = frames[frame];
}
function pause() {
  clearInterval(timer);
  timer = null;
  play.textContent = "播放演示";
}
play.hidden = motion.matches;
next.hidden = false;
next.onclick = () => { pause(); advance(); };
play.onclick = () => {
  if (timer) return pause();
  advance();
  timer = setInterval(advance, 2600);
  play.textContent = "暂停";
};
motion.onchange = () => { pause(); play.hidden = motion.matches; };
document.addEventListener("visibilitychange", () => { if (document.hidden) pause(); });
