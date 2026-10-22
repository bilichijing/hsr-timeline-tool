// 应用入口：状态管理、Tab 切换、全局事件与键盘操作
import { api } from "./api.js";
import { confirmDialog, isModalOpen, toast } from "./ui.js";
import { openPicker, openRelicEditor, prefetchCatalogs } from "./pickers.js";
import {
  openEnemyDebuffs,
  openOrbBuffs,
  renderConfig,
  renderDetails,
  renderInteractive,
  renderLogs,
  renderPie,
  renderSidebar,
  renderSummary,
  renderTimeline,
} from "./views.js";

const TABS = [
  ["config", "⚙ 配置"],
  ["interactive", "▶ 交互模拟"],
  ["logs", "☰ 行动日志"],
  ["timeline", "◔ AV 时间轴"],
  ["pie", "◔ 伤害占比"],
  ["details", "≡ 伤害明细"],
  ["summary", "✦ 汇总"],
];

const app = {
  meta: null,
  state: null,
  tab: "config",
  selectedLog: null,
  busy: false,
};

// ── 启动 ─────────────────────────────────────────────────

async function boot() {
  buildTabs();
  bindEvents();
  try {
    app.meta = await api.meta();
    app.state = await api.state();
  } catch (err) {
    toast(`初始化失败：${err.message}`, "error", 8000);
    return;
  }
  renderAll();
  prefetchCatalogs();
}

function buildTabs() {
  const host = document.getElementById("tabs");
  host.innerHTML = TABS.map(([key, label]) =>
    `<button class="tab" data-tab="${key}">${label}</button>`).join("");
}

// ── 渲染 ─────────────────────────────────────────────────

function renderAll() {
  if (!app.state) return;
  document.querySelectorAll(".tab").forEach((node) => {
    node.classList.toggle("active", node.dataset.tab === app.tab);
  });
  document.querySelectorAll(".panel").forEach((node) => {
    node.classList.toggle("active", node.dataset.tab === app.tab);
  });
  renderSidebar(app.state, app.meta);
  renderPanel(app.tab);
}

function renderPanel(tab) {
  const host = document.querySelector(`.panel[data-tab="${tab}"]`);
  if (!host) return;
  switch (tab) {
    case "config":
      renderConfig(host, app.state, app.meta);
      break;
    case "interactive":
      renderInteractive(host, app.state, app.meta);
      break;
    case "logs":
      renderLogs(host, app.state);
      break;
    case "timeline":
      renderTimeline(host, app.state);
      break;
    case "pie":
      renderPie(host, app.state);
      break;
    case "details":
      renderDetails(host, app.state);
      break;
    case "summary":
      renderSummary(host, app.state);
      break;
    default:
      host.innerHTML = "";
  }
}

function setTab(tab) {
  if (app.tab === tab) return;
  app.tab = tab;
  renderAll();
}

// ── 请求封装 ─────────────────────────────────────────────

async function post(path, body = {}, { silent = false } = {}) {
  if (app.busy) return null;
  app.busy = true;
  try {
    const res = await api.post(path, body);
    app.state = res.state;
    if (res.message && !silent) toast(res.message, "ok", 5000);
    renderAll();
    return res;
  } catch (err) {
    toast(err.message, "error", 6000);
    return null;
  } finally {
    app.busy = false;
  }
}

// ── 事件绑定 ─────────────────────────────────────────────

function bindEvents() {
  document.addEventListener("click", onClick);
  document.addEventListener("change", onChange);
  document.addEventListener("keydown", onKeyDown);
  document.getElementById("btn-run").addEventListener("click", async () => {
    await post("/api/sim/run");
    setTab("logs");
  });
}

async function onClick(event) {
  const tabBtn = event.target.closest(".tab");
  if (tabBtn) {
    setTab(tabBtn.dataset.tab);
    return;
  }

  // 侧栏：能量球 / 敌人 / 状态
  const orb = event.target.closest("[data-orb]");
  if (orb) {
    openOrbBuffs(app.state, Number(orb.dataset.orb));
    return;
  }
  const debuff = event.target.closest("[data-debuff]");
  if (debuff) {
    event.stopPropagation();
    openEnemyDebuffs(app.state, Number(debuff.dataset.debuff));
    return;
  }
  const enemy = event.target.closest("[data-enemy]");
  if (enemy) {
    const sim = app.state.sim;
    const index = Number(enemy.dataset.enemy);
    if (sim && sim.enemies[index]) {
      await post("/api/sim/target", { unit_id: sim.enemies[index].unit_id });
    }
    return;
  }

  // 队伍：选择角色 / 光锥 / 遗器
  const pickChar = event.target.closest("[data-pick-char]");
  if (pickChar) {
    const row = Number(pickChar.dataset.pickChar);
    const current = app.state.rows[row];
    const picked = await openPicker({
      kind: "character", meta: app.meta, currentId: current?.char_id || "",
    }).catch((err) => {
      toast(`加载角色列表失败：${err.message}`, "error");
      return null;
    });
    if (!picked || picked.clear) return;
    toast("正在加载角色详情…");
    await post("/api/team/character", { row, char_id: picked.id }, { silent: true });
    return;
  }
  const pickLc = event.target.closest("[data-pick-lc]");
  if (pickLc) {
    const row = Number(pickLc.dataset.pickLc);
    const current = app.state.rows[row];
    if (!current) return;
    const picked = await openPicker({
      kind: "lightcone",
      meta: app.meta,
      currentId: current.lightcone.id,
      currentRank: current.lightcone.rank,
    }).catch((err) => {
      toast(`加载光锥列表失败：${err.message}`, "error");
      return null;
    });
    if (!picked) return;
    if (picked.clear) {
      await post("/api/team/lightcone", { row, clear: true });
    } else {
      await post("/api/team/lightcone", { row, lightcone_id: picked.id, rank: picked.rank || 1 });
    }
    return;
  }
  const pickRelics = event.target.closest("[data-pick-relics]");
  if (pickRelics) {
    const row = Number(pickRelics.dataset.pickRelics);
    const current = app.state.rows[row];
    if (!current) return;
    const edited = await openRelicEditor({
      meta: app.meta, rowView: current, rowName: current.name,
    }).catch((err) => {
      toast(`打开遗器配置失败：${err.message}`, "error");
      return null;
    });
    if (!edited) return;
    await post("/api/team/relics", { row, relics: edited.relics });
    return;
  }

  // 配置页按钮
  const act = event.target.closest("[data-act]");
  if (act) {
    await handleAction(act);
    return;
  }

  // 交互日志：选中一行（用于回溯）
  const logRow = event.target.closest("[data-log-index]");
  if (logRow) {
    app.selectedLog = Number(logRow.dataset.logIndex);
    document.querySelectorAll("[data-log-index]").forEach((node) => {
      node.classList.toggle("selected", Number(node.dataset.logIndex) === app.selectedLog);
    });
    return;
  }

  // 敌方攻击：删除一行
  const del = event.target.closest("[data-attack-del]");
  if (del) {
    const index = Number(del.dataset.attackDel);
    const attacks = [...(app.state.config.enemy_attacks || [])];
    attacks.splice(index, 1);
    await post("/api/config", { enemy_attacks: attacks });
  }
}

async function handleAction(node) {
  const act = node.dataset.act;
  switch (act) {
    case "import": {
      const input = document.querySelector("[data-file]");
      if (input) input.click();
      break;
    }
    case "reset": {
      const ok = await confirmDialog("确定重置为空白队伍？当前队伍配置会被清空。", { okText: "重置" });
      if (ok) await post("/api/reset");
      break;
    }
    case "sim-start":
      await post("/api/sim/start");
      setTab("interactive");
      break;
    case "sim-advance":
      await post("/api/sim/advance");
      break;
    case "sim-normal":
      await post("/api/sim/act", { skill_type: "normal" });
      break;
    case "sim-skill":
      await post("/api/sim/act", { skill_type: "skill" });
      break;
    case "sim-ultra":
      await post("/api/sim/ultra", { index: Number(node.dataset.index) });
      break;
    case "sim-rewind": {
      if (app.selectedLog === null || app.selectedLog === undefined) {
        toast("请先在日志中选中要回溯到的回合", "error");
        break;
      }
      await post("/api/sim/rewind", { index: app.selectedLog });
      app.selectedLog = null;
      break;
    }
    case "attack-add": {
      const attacks = [...(app.state.config.enemy_attacks || [])];
      attacks.push({
        total_av: 120,
        source_enemy_index: 0,
        attack: 1000,
        target_indices: [],
        energy_recover: 10,
      });
      await post("/api/config", { enemy_attacks: attacks });
      break;
    }
    default:
      break;
  }
}

async function onChange(event) {
  const target = event.target;

  // 文件导入
  if (target.matches("[data-file]")) {
    const file = target.files && target.files[0];
    target.value = "";
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await post("/api/import/freesr", { data });
    } catch (err) {
      toast(`读取 freesr 文件失败：${err.message}`, "error", 6000);
    }
    return;
  }

  // 队伍：名称 / 星魂 / 面板
  if (target.matches("[data-name-row]")) {
    await post("/api/team/name", {
      row: Number(target.dataset.nameRow), name: target.value,
    }, { silent: true });
    return;
  }
  if (target.matches("[data-rank-row]")) {
    await post("/api/team/rank", {
      row: Number(target.dataset.rankRow), rank: Number(target.value),
    }, { silent: true });
    return;
  }
  if (target.matches("[data-panel-row]")) {
    const key = target.dataset.key;
    const raw = String(target.value).trim();
    let value = Number(raw.replace("%", ""));
    if (!Number.isFinite(value)) {
      toast("请输入数字", "error");
      renderAll();
      return;
    }
    // 百分比列按百分数输入（显示即为 xx.x%）
    if (app.meta.percent_keys.includes(key)) value /= 100;
    await post("/api/team/panel", {
      row: Number(target.dataset.panelRow), values: { [key]: value },
    }, { silent: true });
    return;
  }

  // 配置项
  const cfg = target.closest("[data-cfg]");
  if (cfg) {
    const section = cfg.dataset.cfg;
    const key = cfg.dataset.key;
    const patch = {};
    document.querySelectorAll(`[data-cfg="${section}"]`).forEach((node) => {
      const raw = node.value;
      patch[node.dataset.key] = node.type === "number" ? Number(raw) : raw;
    });
    patch[key] = cfg.type === "number" ? Number(cfg.value) : cfg.value;
    await post("/api/config", { [section]: patch }, { silent: true });
    return;
  }

  // 敌方攻击表
  if (target.closest("[data-attacks]")) {
    await post("/api/config", { enemy_attacks: collectAttacks() }, { silent: true });
  }
}

function collectAttacks() {
  return [...document.querySelectorAll("[data-attack-row]")].map((row) => {
    const value = (field) => {
      const node = row.querySelector(`[data-attack-field="${field}"]`);
      return node ? Number(node.value || 0) : 0;
    };
    const targets = [...row.querySelectorAll("[data-attack-target]")]
      .filter((node) => node.checked)
      .map((node) => Number(node.dataset.slot));
    return {
      total_av: value("total_av"),
      source_enemy_index: value("source_enemy_index"),
      attack: value("attack"),
      target_indices: targets,
      energy_recover: value("energy_recover"),
    };
  });
}

// ── 键盘 ─────────────────────────────────────────────────

async function onKeyDown(event) {
  if (isModalOpen()) return;
  const tag = (event.target.tagName || "").toLowerCase();
  if (["input", "select", "textarea"].includes(tag)) return;
  if (app.tab !== "interactive" || !app.state?.sim) return;

  const sim = app.state.sim;
  if (event.code === "Space" || event.code === "Enter") {
    event.preventDefault();
    await post("/api/sim/advance");
    return;
  }
  if (event.key === "q" || event.key === "Q") {
    await post("/api/sim/act", { skill_type: "normal" });
    return;
  }
  if (event.key === "e" || event.key === "E") {
    await post("/api/sim/act", { skill_type: "skill" });
    return;
  }
  if (["1", "2", "3", "4"].includes(event.key)) {
    const index = Number(event.key) - 1;
    if (index < sim.orbs.length) await post("/api/sim/ultra", { index });
  }
}

boot();
