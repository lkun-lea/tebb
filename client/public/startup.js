// 独立于 React 和主资源包，页面第一帧即可展示启动状态。
(() => {
  const panel = document.getElementById("startup");
  const status = document.getElementById("startup-status");
  const retry = document.getElementById("startup-retry");
  if (!panel || !status || !retry) return;
  let finished = false;
  let failed = false;
  let stage = status.textContent;
  let slow = false;
  const slowTimer = setTimeout(() => {
    slow = true;
    if (!finished && !failed) status.textContent = `${stage}\n首次启动可能需要多等一会儿。`;
  }, 12000);

  function fail(message) {
    if (finished || failed) return;
    failed = true;
    clearTimeout(slowTimer);
    panel.dataset.state = "error";
    panel.setAttribute("aria-live", "assertive");
    status.textContent = `启动未完成\n${message || "请重新加载；仍然失败时查看启动终端。"}`;
    retry.hidden = false;
  }
  function onError(event) {
    if (event.target?.tagName === "SCRIPT") {
      fail("界面资源未能加载，请检查启动终端后重新加载。");
    } else if (event.message) {
      fail(event.message);
    }
  }
  function onRejection(event) {
    fail(String(event.reason || "界面初始化失败。"));
  }
  window.addEventListener("error", onError, true);
  window.addEventListener("unhandledrejection", onRejection);
  retry.addEventListener("click", () => location.reload());
  window.addEventListener("desk-startup", (event) => {
    if (finished || failed) return;
    const detail = event.detail || {};
    if (detail.state === "error") {
      fail(detail.message);
    } else if (detail.state === "ready") {
      finished = true;
      clearTimeout(slowTimer);
      window.removeEventListener("error", onError, true);
      window.removeEventListener("unhandledrejection", onRejection);
      panel.dataset.state = "ready";
      panel.classList.add("startup-exit");
      // 仅为淡出后的 DOM 清理，不延迟客户端就绪。
      setTimeout(() => panel.remove(), 240);
    } else if (detail.message) {
      stage = detail.message;
      status.textContent = slow ? `${stage}\n首次启动可能需要多等一会儿。` : stage;
    }
  });
})();
