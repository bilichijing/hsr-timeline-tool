// 通用 UI 辅助：转义、提示条、模态框、事件委托

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/** 数字格式化：去掉多余小数、加千分位 */
export function num(value, digits = 0) {
  const n = Number(value) || 0;
  const text = digits > 0 ? n.toFixed(digits) : String(Math.round(n));
  return text.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function pct(value, digits = 1) {
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

/** 图片图标（加载失败时隐藏，露出占位底色） */
export function iconHtml(url, alt = "", fallback = "?") {
  if (!url) return esc(fallback);
  return `<img src="${esc(url)}" alt="${esc(alt)}" loading="lazy"
    onerror="this.style.display='none';this.parentNode.textContent='${esc(fallback)}'">`;
}

// ── Toast ────────────────────────────────────────────────

export function toast(message, kind = "info", timeout = 3400) {
  if (!message) return;
  const root = document.getElementById("toast-root");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  root.appendChild(node);
  setTimeout(() => {
    node.style.transition = "opacity .2s";
    node.style.opacity = "0";
    setTimeout(() => node.remove(), 220);
  }, timeout);
}

// ── 模态框 ───────────────────────────────────────────────

/**
 * 打开模态对话框。
 * @returns {{dialog: HTMLDialogElement, body: HTMLElement, foot: HTMLElement, close: Function}}
 */
export function openModal({ title = "", bodyHtml = "", footHtml = "", width = "", onMount = null } = {}) {
  const dialog = document.createElement("dialog");
  dialog.className = "modal";
  if (width) dialog.style.width = width;
  dialog.innerHTML = `
    <div class="modal-head">
      <span class="modal-title">${esc(title)}</span>
      <span class="right"></span>
      <button class="btn small" data-close>关闭</button>
    </div>
    <div class="modal-body">${bodyHtml}</div>
    <div class="modal-foot">${footHtml}</div>
  `;
  document.getElementById("modal-root").appendChild(dialog);
  const body = dialog.querySelector(".modal-body");
  const foot = dialog.querySelector(".modal-foot");
  const close = (value) => {
    if (dialog.open) dialog.close();
    dialog.remove();
    return value;
  };
  dialog.querySelector("[data-close]").addEventListener("click", () => close(null));
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close(null);
  });
  dialog.addEventListener("click", (event) => {
    // 点击遮罩关闭
    if (event.target === dialog) close(null);
  });
  dialog.showModal();
  if (onMount) onMount({ dialog, body, foot, close });
  return { dialog, body, foot, close };
}

/** 二次确认 */
export function confirmDialog(message, { title = "确认", okText = "确定" } = {}) {
  return new Promise((resolve) => {
    const modal = openModal({
      title,
      bodyHtml: `<div style="padding:6px 2px">${esc(message)}</div>`,
      footHtml: `<span class="right"></span>
        <button class="btn" data-cancel>取消</button>
        <button class="btn primary" data-ok>${esc(okText)}</button>`,
    });
    modal.foot.querySelector("[data-ok]").addEventListener("click", () => {
      modal.close();
      resolve(true);
    });
    modal.foot.querySelector("[data-cancel]").addEventListener("click", () => {
      modal.close();
      resolve(false);
    });
    modal.dialog.addEventListener("close", () => resolve(false));
  });
}

/** 事件委托 */
export function on(root, eventName, selector, handler) {
  root.addEventListener(eventName, (event) => {
    const target = event.target.closest(selector);
    if (target && root.contains(target)) handler(event, target);
  });
}

export function isModalOpen() {
  return !!document.querySelector("dialog[open]");
}

export function debounce(fn, ms = 200) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
