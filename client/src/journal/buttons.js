/** 今日手记按钮。主操作、辅助操作和单选卡共用键盘、焦点和触摸行为。 */
globalThis.createJournalButton = function (parent, label, onClick, variant = 'secondary') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = variant === 'primary' ? 'jr-primary' : 'jr-button';
  button.dataset.variant = variant;
  button.textContent = label;
  button.onclick = onClick;
  parent.append(button);
  return button;
};
