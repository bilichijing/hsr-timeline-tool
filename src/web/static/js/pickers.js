// 选择器（角色 / 光锥 / 遗器套装）与遗器配置对话框
import { api } from "./api.js";
import { esc, iconHtml, openModal, toast } from "./ui.js";

// ── 目录缓存 ─────────────────────────────────────────────

const catalog = { character: null, lightcone: null, relicset: null };
const loading = {};

async function loadCatalog(kind) {
  if (catalog[kind]) return catalog[kind];
  if (loading[kind]) return loading[kind];
  const loader = {
    character: api.characters,
    lightcone: api.lightcones,
    relicset: api.relicsets,
  }[kind];
  loading[kind] = loader()
    .then((items) => {
      catalog[kind] = items;
      delete loading[kind];
      return items;
    })
    .catch((err) => {
      delete loading[kind];
      throw err;
    });
  return loading[kind];
}

export function prefetchCatalogs() {
  loadCatalog("character").catch(() => {});
  loadCatalog("lightcone").catch(() => {});
  loadCatalog("relicset").catch(() => {});
}

// ── 通用选择器 ───────────────────────────────────────────

const KIND_TITLE = {
  character: "选择角色",
  lightcone: "选择光锥（含叠影等级）",
  relicset: "选择遗器套装",
};

/**
 * 打开选择器。
 * @returns {Promise<{id:string, rank?:number}|{clear:true}|null>}
 */
export async function openPicker({ kind, meta, currentId = "", currentRank = 1, title = "" }) {
  let items = [];
  try {
    items = await loadCatalog(kind);
  } catch (err) {
    return Promise.reject(err);
  }

  return new Promise((resolve) => {
    let settled = false;
    let selected = null;
    let rank = Number(currentRank) || 1;

    const finish = (value) => {
      if (settled) return;
      settled = true;
      modal.close();
      resolve(value);
    };

    const modal = openModal({
      title: title || KIND_TITLE[kind],
      bodyHtml: `
        <div class="picker-toolbar">
          <input type="text" data-search placeholder="搜索名称 / 英文名 / ID">
          ${kind === "relicset"
            ? `<select data-filter="type">
                 <option value="all">全部</option>
                 <option value="outer">遗器（4 件套）</option>
                 <option value="inner">位面饰品（2 件套）</option>
               </select>`
            : `<select data-filter="path"><option value="">全部命途</option>
                 ${Object.entries(meta.paths).map(([en, zh]) => `<option value="${esc(en)}">${esc(zh)}</option>`).join("")}
               </select>`}
          ${kind === "character"
            ? `<select data-filter="element"><option value="">全部属性</option>
                 ${Object.entries(meta.elements).map(([en, zh]) => `<option value="${esc(en)}">${esc(zh)}</option>`).join("")}
               </select>`
            : ""}
          ${kind === "lightcone"
            ? `<select data-filter="rarity"><option value="">全部星级</option>
                 <option value="5">5 星</option><option value="4">4 星</option><option value="3">3 星</option>
               </select>
               <select data-rank>${[1, 2, 3, 4, 5].map((r) => `<option value="${r}" ${r === rank ? "selected" : ""}>叠影 ${r}</option>`).join("")}</select>`
            : ""}
        </div>
        <div class="picker-grid" data-grid></div>
        <div class="hint" data-status style="margin-top:8px"></div>
      `,
      footHtml: `
        <span class="hint" data-picked></span>
        <span class="right"></span>
        ${kind === "character" ? "" : `<button class="btn danger" data-clear>${kind === "lightcone" ? "不装备" : "清空"}</button>`}
        <button class="btn" data-cancel>取消</button>
        <button class="btn primary" data-ok disabled>确认</button>
      `,
    });

    const grid = modal.body.querySelector("[data-grid]");
    const status = modal.body.querySelector("[data-status]");
    const search = modal.body.querySelector("[data-search]");
    const pathFilter = modal.body.querySelector('[data-filter="path"]');
    const elementFilter = modal.body.querySelector('[data-filter="element"]');
    const rarityFilter = modal.body.querySelector('[data-filter="rarity"]');
    const typeFilter = modal.body.querySelector('[data-filter="type"]');
    const rankSelect = modal.body.querySelector("[data-rank]");
    const pickedLabel = modal.foot.querySelector("[data-picked]");
    const okBtn = modal.foot.querySelector("[data-ok]");

    const itemHtml = (item) => {
      if (kind === "character") {
        const name = item.name_zh || item.name_en || item.id;
        return `<button class="picker-item" data-id="${esc(item.id)}"
            title="${esc(name)}｜${item.rarity}★｜${esc(item.path_zh)}｜${esc(item.element_zh)}">
            <span class="picker-icon">${iconHtml(item.icon, name, name.slice(0, 1))}</span>
            <span class="picker-name">${esc(name)}</span>
            <span class="picker-meta">${item.rarity}★ · ${esc(item.path_zh)} · ${esc(item.element_zh)}</span>
          </button>`;
      }
      if (kind === "lightcone") {
        const name = item.name_zh || item.name_en || item.id;
        return `<button class="picker-item" data-id="${esc(item.id)}"
            title="${esc(name)}｜${item.rarity}★｜${esc(item.path_zh)}｜基础攻击 ${item.atk}">
            <span class="picker-icon">${iconHtml(item.icon, name, "锥")}</span>
            <span class="picker-name">${esc(name)}</span>
            <span class="picker-meta">${item.rarity}★ · ${esc(item.path_zh)}</span>
          </button>`;
      }
      const name = item.name_zh || item.name_en || item.id;
      return `<button class="picker-item" data-id="${esc(item.id)}"
          title="${esc(name)}&#10;${esc(item.bonus_2pc)}&#10;${esc(item.bonus_4pc)}">
          <span class="picker-icon">${iconHtml(item.icon, name, "遗")}</span>
          <span class="picker-name">${esc(name)}</span>
          <span class="picker-meta">${item.inner ? "位面饰品" : "遗器"}</span>
        </button>`;
    };

    const applyFilter = () => {
      const keyword = (search.value || "").trim().toLowerCase();
      const path = pathFilter ? pathFilter.value : "";
      const element = elementFilter ? elementFilter.value : "";
      const rarity = rarityFilter ? rarityFilter.value : "";
      const type = typeFilter ? typeFilter.value : "all";
      const shown = items.filter((item) => {
        if (path && item.path !== path) return false;
        if (element && item.element !== element) return false;
        if (rarity && String(item.rarity) !== rarity) return false;
        if (type === "inner" && !item.inner) return false;
        if (type === "outer" && item.inner) return false;
        if (!keyword) return true;
        const name = `${item.name_zh || ""} ${item.name_en || ""} ${item.id}`.toLowerCase();
        return name.includes(keyword);
      });
      grid.innerHTML = shown.map(itemHtml).join("") ||
        `<div class="hint" style="grid-column:1/-1">没有匹配的条目</div>`;
      status.textContent = `显示 ${shown.length} / ${items.length}`;
      // 恢复选中态
      if (selected) {
        const node = grid.querySelector(`[data-id="${selected}"]`);
        if (node) node.classList.add("selected");
      }
    };

    const selectItem = (id) => {
      selected = id;
      grid.querySelectorAll(".picker-item").forEach((node) => {
        node.classList.toggle("selected", node.dataset.id === id);
      });
      okBtn.disabled = false;
      const item = items.find((it) => it.id === id);
      const name = item ? (item.name_zh || item.name_en || item.id) : id;
      pickedLabel.textContent = kind === "lightcone" ? `${name}（叠影 ${rank}）` : name;
    };

    grid.addEventListener("click", (event) => {
      const node = event.target.closest(".picker-item");
      if (node) selectItem(node.dataset.id);
    });
    grid.addEventListener("dblclick", (event) => {
      const node = event.target.closest(".picker-item");
      if (node) {
        selectItem(node.dataset.id);
        finish(kind === "lightcone"
          ? { id: selected, rank }
          : { id: selected });
      }
    });
    [search, pathFilter, elementFilter, rarityFilter, typeFilter]
      .filter(Boolean)
      .forEach((node) => node.addEventListener("input", applyFilter));
    if (rankSelect) {
      rankSelect.addEventListener("change", () => {
        rank = Number(rankSelect.value) || 1;
        if (selected) selectItem(selected);
      });
    }
    modal.foot.querySelector("[data-cancel]").addEventListener("click", () => finish(null));
    const clearBtn = modal.foot.querySelector("[data-clear]");
    if (clearBtn) clearBtn.addEventListener("click", () => finish({ clear: true }));
    okBtn.addEventListener("click", () => {
      if (!selected) return;
      finish(kind === "lightcone" ? { id: selected, rank } : { id: selected });
    });
    modal.dialog.addEventListener("close", () => {
      if (!settled) {
        settled = true;
        resolve(null);
      }
    });

    applyFilter();
    if (currentId) {
      selected = String(currentId);
      const node = grid.querySelector(`[data-id="${selected}"]`);
      if (node) {
        node.classList.add("selected");
        node.scrollIntoView({ block: "nearest" });
        okBtn.disabled = false;
        pickedLabel.textContent = "当前：" + (items.find((it) => it.id === selected)?.name_zh || selected);
      } else {
        selected = null;
      }
    }
  });
}

// ── 遗器配置对话框 ───────────────────────────────────────

const EMPTY_SLOT = () => ({ setId: "", setName: "", mainId: 0, subs: [] });

/**
 * 打开 6 部位遗器配置。
 * @returns {Promise<{relics: object[]}|null>}
 */
export function openRelicEditor({ meta, rowView, rowName = "" }) {
  // 初始化槽位状态
  const slots = {};
  for (const slot of meta.slots) slots[slot.id] = EMPTY_SLOT();
  for (const item of rowView.relics.items || []) {
    const slot = Number(item.slot);
    if (!slots[slot]) continue;
    slots[slot] = {
      setId: String(item.set_id || ""),
      setName: item.set_name || "",
      mainId: Number(item.main_affix_id) || 0,
      subs: (item.subs || []).map((s) => ({ id: Number(s.id), count: Number(s.count), step: Number(s.step) })),
    };
  }
  let activeSlot = meta.slots[0].id;

  const slotRow = (slot) => {
    const state = slots[slot.id];
    const mainOptions = meta.main_affixes[String(slot.id)] || [];
    if (!state.mainId && mainOptions.length) state.mainId = mainOptions[0].id;
    return `<tr data-slot-row="${slot.id}" class="${slot.id === activeSlot ? "selected" : ""}">
      <td>${esc(slot.name)}</td>
      <td><button class="btn small" data-choose-set="${slot.id}">${esc(state.setName || (state.setId ? `套装 ${state.setId}` : "选择…"))}</button></td>
      <td>
        <select data-main="${slot.id}" ${state.setId ? "" : "disabled"}>
          ${mainOptions.map((opt) => `<option value="${opt.id}" ${opt.id === state.mainId ? "selected" : ""}>${esc(opt.label)}</option>`).join("")}
        </select>
      </td>
    </tr>`;
  };

  const subValue = (subId, count, step) => {
    const table = meta.sub_affix_table[String(subId)];
    if (!table || !count) return "—";
    const [t1, t2] = table.tiers;
    const value = t1 * count + (t2 - t1) * step;
    return table.percent ? `+${value.toFixed(2)}%` : `+${value.toFixed(2)}`;
  };

  const subEditor = () => {
    const state = slots[activeSlot];
    const rows = [];
    for (let i = 0; i < meta.max_sub_affixes; i += 1) {
      const sub = state.subs[i] || { id: 0, count: 0, step: 0 };
      rows.push(`<div class="sub-editor">
        <select data-sub-id="${i}">
          <option value="0">（无）</option>
          ${meta.sub_affixes.map((s) => `<option value="${s.id}" ${Number(sub.id) === s.id ? "selected" : ""}>${esc(s.label)}</option>`).join("")}
        </select>
        <input type="number" min="0" max="6" step="1" data-sub-count="${i}" value="${Number(sub.count) || 0}" title="强化次数 count">
        <input type="number" min="0" max="10" step="1" data-sub-step="${i}" value="${Number(sub.step) || 0}" title="强化档位 step">
        <span class="mono dim" data-sub-value="${i}">${subValue(sub.id, sub.count, sub.step)}</span>
      </div>`);
    }
    return `<div class="hint" style="margin-bottom:6px">当前部位：<b>${esc(
      (meta.slots.find((s) => s.id === activeSlot) || {}).name || "",
    )}</b>（点表格左侧行切换）</div>
      <div class="sub-editor head"><span>词条</span><span>次数</span><span>档位</span><span>数值</span></div>
      ${rows.join("")}
      <div class="hint" style="margin-top:8px">最终值 = 最低档 × 次数 + (第二档 − 最低档) × 档位<br>与 freesr-data.json 的 count / step 语义一致</div>`;
  };

  const summary = () => {
    const counts = {};
    const names = {};
    Object.values(slots).forEach((state) => {
      if (!state.setId) return;
      counts[state.setId] = (counts[state.setId] || 0) + 1;
      names[state.setId] = state.setName || state.setId;
    });
    const keys = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    if (!keys.length) return "未配置任何部位（面板只含角色基础 + 行迹加成）";
    return `已配置 ${Object.values(slots).filter((s) => s.setId).length}/6 部位：` +
      keys.map((k) => `${names[k]}×${counts[k]}`).join(" · ");
  };

  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      modal.close();
      resolve(value);
    };

    const modal = openModal({
      title: `遗器配置${rowName ? " — " + rowName : ""}`,
      bodyHtml: `
        <div class="relic-layout">
          <div>
            <div class="table-wrap">
              <table class="grid">
                <thead><tr><th>部位</th><th>套装</th><th>主词条</th></tr></thead>
                <tbody data-slot-body>${meta.slots.map(slotRow).join("")}</tbody>
              </table>
            </div>
            <div class="hint" data-summary style="margin-top:8px">${esc(summary())}</div>
          </div>
          <div data-sub-editor>${subEditor()}</div>
        </div>
      `,
      footHtml: `
        <span class="right"></span>
        <button class="btn danger" data-clear-slot>清空本部位</button>
        <button class="btn danger" data-clear-all>清空全部</button>
        <button class="btn" data-cancel>取消</button>
        <button class="btn primary" data-ok>确定</button>
      `,
    });

    const slotBody = modal.body.querySelector("[data-slot-body]");
    const subHost = modal.body.querySelector("[data-sub-editor]");
    const summaryNode = modal.body.querySelector("[data-summary]");

    const rerenderTable = () => {
      slotBody.innerHTML = meta.slots.map(slotRow).join("");
    };
    const rerenderSub = () => {
      subHost.innerHTML = subEditor();
    };
    const refreshSummary = () => {
      summaryNode.textContent = summary();
    };

    slotBody.addEventListener("click", async (event) => {
      const chooseBtn = event.target.closest("[data-choose-set]");
      if (chooseBtn) {
        const slotId = Number(chooseBtn.dataset.chooseSet);
        const state = slots[slotId];
        try {
          const picked = await openPicker({
            kind: "relicset", meta, currentId: state.setId,
            title: `选择遗器套装 — ${(meta.slots.find((s) => s.id === slotId) || {}).name || ""}`,
          });
          if (picked === null) return;
          if (picked.clear) {
            slots[slotId] = { ...EMPTY_SLOT() };
          } else {
            const item = catalog.relicset.find((it) => it.id === picked.id);
            state.setId = String(picked.id);
            state.setName = item ? (item.name_zh || item.name_en || picked.id) : String(picked.id);
            const options = meta.main_affixes[String(slotId)] || [];
            if (!options.some((opt) => opt.id === state.mainId)) {
              state.mainId = options.length ? options[0].id : 0;
            }
          }
          rerenderTable();
          rerenderSub();
          refreshSummary();
        } catch (err) {
          toast(`加载遗器套装失败：${err.message}`, "error");
        }
        return;
      }
      const row = event.target.closest("[data-slot-row]");
      if (row) {
        activeSlot = Number(row.dataset.slotRow);
        rerenderTable();
        rerenderSub();
      }
    });

    slotBody.addEventListener("change", (event) => {
      const mainSelect = event.target.closest("[data-main]");
      if (mainSelect) {
        slots[Number(mainSelect.dataset.main)].mainId = Number(mainSelect.value);
      }
    });

    subHost.addEventListener("change", (event) => {
      const state = slots[activeSlot];
      const host = subHost;
      const subs = [];
      for (let i = 0; i < meta.max_sub_affixes; i += 1) {
        const idNode = host.querySelector(`[data-sub-id="${i}"]`);
        const countNode = host.querySelector(`[data-sub-count="${i}"]`);
        const stepNode = host.querySelector(`[data-sub-step="${i}"]`);
        const id = Number(idNode?.value || 0);
        const count = Math.max(0, Math.min(6, Number(countNode?.value || 0)));
        const step = Math.max(0, Math.min(10, Number(stepNode?.value || 0)));
        if (id && count > 0) subs.push({ id, count, step });
        const valueNode = host.querySelector(`[data-sub-value="${i}"]`);
        if (valueNode) valueNode.textContent = subValue(id, count, step);
      }
      state.subs = subs;
      void event;
    });

    modal.foot.querySelector("[data-clear-slot]").addEventListener("click", () => {
      slots[activeSlot] = EMPTY_SLOT();
      rerenderTable();
      rerenderSub();
      refreshSummary();
    });
    modal.foot.querySelector("[data-clear-all]").addEventListener("click", () => {
      meta.slots.forEach((slot) => { slots[slot.id] = EMPTY_SLOT(); });
      rerenderTable();
      rerenderSub();
      refreshSummary();
    });
    modal.foot.querySelector("[data-cancel]").addEventListener("click", () => finish(null));
    modal.foot.querySelector("[data-ok]").addEventListener("click", () => {
      const relics = [];
      meta.slots.forEach((slot) => {
        const state = slots[slot.id];
        if (!state.setId) return;
        relics.push({
          relic_id: Number(state.setId) * 10000 + slot.id,
          relic_set_id: Number(state.setId),
          level: 15,
          main_affix_id: Number(state.mainId) || 0,
          sub_affixes: (state.subs || []).map((sub) => ({
            sub_affix_id: Number(sub.id), count: Number(sub.count), step: Number(sub.step),
          })),
        });
      });
      finish({ relics });
    });
    modal.dialog.addEventListener("close", () => {
      if (!settled) {
        settled = true;
        resolve(null);
      }
    });
  });
}
