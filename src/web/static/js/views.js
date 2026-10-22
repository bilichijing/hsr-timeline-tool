// 各 Tab 与侧栏的渲染逻辑
import { confirmDialog, esc, iconHtml, num, openModal, toast } from "./ui.js";
import { openPicker, openRelicEditor } from "./pickers.js";

const GOLD = "#d4a857";
const CHART_COLORS = ["#d4a857", "#4ec5f1", "#b57dee", "#5fc97e", "#e5544e", "#7d8cff", "#f4d36a", "#66d19e"];

const ACTION_COLORS = {
  normal: "#5fc97e",
  skill: "#4ec5f1",
  ultra: "#d4a857",
  follow_up: "#b57dee",
  technique: "#9ba3b4",
  memo_skill: "#7d8cff",
  monster: "#e5544e",
  enemy_attack: "#e5544e",
  aha_moment: "#d4a857",
  countdown: "#6eb4be",
};

const KIND_CLASS = {
  角色: "role", 怪物: "monster", 阿哈: "aha", 倒计时: "countdown", 敌方攻击: "enemy_attack",
};

// ── 小工具 ───────────────────────────────────────────────

function tableHtml(headers, rows, { empty = "暂无数据", extraClass = "" } = {}) {
  if (!rows.length) return `<div class="empty-state">${esc(empty)}</div>`;
  return `<div class="table-wrap ${extraClass}"><table class="grid">
    <thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody>
  </table></div>`;
}

function field(label, inner) {
  return `<label class="field"><span>${esc(label)}</span>${inner}</label>`;
}

function panelDisplay(key, value, percentKeys) {
  if (percentKeys.includes(key)) return `${(Number(value) * 100).toFixed(1)}%`;
  if (key === "spd") return Number(value).toFixed(1);
  return String(Math.round(Number(value)));
}

// ── 侧栏 ─────────────────────────────────────────────────

export function renderSidebar(state, meta) {
  const sim = state.sim;
  renderOrbs(state, meta, sim);
  renderSp(state, sim);
  renderEnemies(state, meta, sim);
  renderPreview(state, sim);

  const chip = document.getElementById("global-status");
  if (sim) {
    chip.textContent = `总AV ${sim.total_av}/${sim.max_av} · 伤害 ${num(sim.total_damage)} · SP ${sim.sp}`;
  } else {
    const count = state.rows.filter((r) => r.name).length;
    chip.textContent = `未开始 · 队伍 ${count} 人`;
  }
}

function renderOrbs(state, meta, sim) {
  const host = document.getElementById("orb-list");
  if (!sim) {
    const rows = state.rows.filter((r) => r.name);
    if (!rows.length) {
      host.innerHTML = `<div class="hint">尚未配置角色</div>`;
      return;
    }
    host.innerHTML = rows.map((r) => `
      <div class="orb">
        <div class="orb-avatar">${iconHtml(r.icon, r.name, r.name.slice(0, 1))}</div>
        <div>
          <div class="orb-name">${esc(r.name)}</div>
          <div class="orb-meta">${esc(r.path_zh || "")} · ${esc(r.element_zh || "")} · 星魂 ${r.rank}</div>
        </div>
        <div class="orb-energy">${esc(r.cells.hp)}</div>
      </div>`).join("");
    return;
  }
  host.innerHTML = sim.orbs.map((orb, index) => {
    const energyPct = orb.energy_max > 0 ? Math.min(100, (orb.energy / orb.energy_max) * 100) : 0;
    const charge = orb.charge
      ? (orb.charge.style === "text"
        ? `<span class="orb-charge">${Math.floor(orb.charge.value)}/${orb.charge.max}</span>`
        : `<span class="orb-charge">${"●".repeat(Math.max(0, Math.min(orb.charge.max, Math.round(orb.charge.value))))}</span>`)
      : "";
    const cls = ["orb", orb.active ? "active" : "", orb.pending ? "pending" : ""].filter(Boolean).join(" ");
    return `<div class="${cls}" data-orb="${index}" title="点击查看 Buff / 资源">
      <div class="orb-avatar">${iconHtml(orb.icon, orb.name, orb.name.slice(0, 1))}</div>
      <div>
        <div class="orb-name">${esc(orb.name)} ${charge}</div>
        <div class="orb-meta">HP ${num(orb.hp)} / ${num(orb.hp_max)}</div>
        <div class="energy-bar"><i style="width:${energyPct.toFixed(1)}%"></i></div>
      </div>
      <div class="orb-energy ${orb.full ? "full" : ""}">${Math.round(orb.energy)}</div>
    </div>`;
  }).join("");
}

function renderSp(state, sim) {
  const host = document.getElementById("sp-indicator");
  const current = sim ? sim.sp : state.config.battle.initial_sp || 0;
  const diamonds = Array.from({ length: 5 }, (_, i) =>
    `<span class="sp-diamond ${i < current ? "on" : ""}"></span>`).join("");
  host.innerHTML = `${diamonds}<span class="sp-text ${current === 0 ? "zero" : ""}">${current} / 5</span>`;
}

function renderEnemies(state, meta, sim) {
  const host = document.getElementById("enemy-list");
  if (!sim) {
    const cfg = state.config.enemy;
    host.innerHTML = Array.from({ length: cfg.count || 1 }, (_, i) => `
      <div class="enemy-card">
        <div class="enemy-head"><span>敌人 ${i + 1}（木桩）</span><span class="mono">HP ${num(cfg.hp)}</span></div>
        <div class="enemy-meta">韧性 ${cfg.toughness} · 弱点 ${esc(cfg.weakness)} · Lv.${cfg.level}</div>
        <div class="tb-bar"><i style="width:100%"></i></div>
      </div>`).join("");
    return;
  }
  host.innerHTML = sim.enemies.map((enemy, index) => {
    const dead = enemy.hp <= 0;
    const tbPct = enemy.toughness_max > 0 ? (enemy.toughness / enemy.toughness_max) * 100 : 0;
    const hpPct = enemy.hp_max > 0 ? Math.max(0, (enemy.hp / enemy.hp_max) * 100) : 0;
    const debuffs = enemy.debuffs.length
      ? ` · <span class="chip gold" data-debuff="${index}">${enemy.debuffs.length} 个状态</span>` : "";
    return `<div class="enemy-card ${enemy.selected ? "selected" : ""} ${dead ? "dead" : ""}" data-enemy="${index}">
      <div class="enemy-head">
        <span>敌人 ${index + 1}${enemy.broken ? "（击破）" : ""}</span>
        <span class="mono">${num(enemy.hp)} / ${num(enemy.hp_max)}</span>
      </div>
      <div class="enemy-meta">韧性 ${enemy.toughness}/${enemy.toughness_max} · 弱点 ${esc(enemy.weaknesses.join(", ") || "无")}${debuffs}</div>
      <div class="hp-bar" style="margin-bottom:3px"><i style="width:${hpPct.toFixed(1)}%"></i></div>
      <div class="tb-bar ${enemy.broken ? "broken" : ""}"><i style="width:${tbPct.toFixed(1)}%"></i></div>
    </div>`;
  }).join("");
}

function renderPreview(state, sim) {
  const host = document.getElementById("preview-list");
  if (!sim) {
    host.innerHTML = `<div class="hint">开始交互模拟后显示未来 300 AV 内的行动顺序</div>`;
    return;
  }
  if (!sim.preview.length) {
    host.innerHTML = `<div class="hint">无后续行动（战斗结束或队列为空）</div>`;
    return;
  }
  host.innerHTML = sim.preview.map((item) => {
    const cls = KIND_CLASS[item.kind] || "role";
    return `<div class="preview-item ${cls}">
      <span>${esc(item.name)}</span>
      <span class="kind">${esc(item.kind)}</span>
      <span class="mono">+${item.delta_av.toFixed(1)}</span>
    </div>`;
  }).join("");
}

// ── Buff / debuff 弹窗 ───────────────────────────────────

export function openOrbBuffs(state, index) {
  const sim = state.sim;
  if (!sim || !sim.orbs[index]) return;
  const orb = sim.orbs[index];
  const rows = orb.buffs.map((b) => `<tr>
      <td>${esc(b.name)}</td>
      <td class="dim">${esc(b.stat)}</td>
      <td class="num">${esc(b.text)}</td>
      <td class="num">${b.stacks > 1 ? "×" + b.stacks : "-"}</td>
      <td class="num">${b.remaining === null ? "永久" : b.remaining}</td>
    </tr>`);
  openModal({
    title: `${orb.name} 的 Buff / 资源`,
    bodyHtml: tableHtml(["名称", "属性", "数值", "层数", "剩余回合"], rows, { empty: "当前没有 Buff" }),
    footHtml: `<span class="hint">能量 ${Math.round(orb.energy)}/${Math.round(orb.energy_max)} · HP ${num(orb.hp)}/${num(orb.hp_max)}</span>`,
  });
}

export function openEnemyDebuffs(state, index) {
  const sim = state.sim;
  if (!sim || !sim.enemies[index]) return;
  const enemy = sim.enemies[index];
  const rows = enemy.debuffs.map((d) => `<tr><td>${esc(d.name)}</td><td class="dim">${esc(d.desc)}</td></tr>`);
  openModal({
    title: `敌人 ${index + 1} 的状态`,
    bodyHtml: tableHtml(["名称", "说明"], rows, { empty: "当前没有负面状态" }),
  });
}

// ── 配置 Tab ─────────────────────────────────────────────

function teamRowHtml(row, meta) {
  const panels = meta.panel_keys.map((key) => `
    <td><input data-panel-row="${row.index}" data-key="${key}"
      value="${esc(panelDisplay(key, row.values[key], meta.percent_keys))}"></td>`).join("");
  const relicTip = (row.relics.items || []).map((it) => it.summary).join("\n");
  return `<tr data-row="${row.index}">
    <td class="dim">${row.index + 1}</td>
    <td>
      <div class="row" style="gap:4px;flex-wrap:nowrap">
        <input data-name-row="${row.index}" value="${esc(row.name)}" placeholder="选择角色…" style="width:92px">
        <button class="btn small" data-pick-char="${row.index}" title="打开角色选择器">选</button>
      </div>
    </td>
    <td class="equip-cell ${row.lightcone.id ? "" : "empty"}" data-pick-lc="${row.index}"
        title="${esc(row.lightcone.desc || "双击/点击选择光锥与叠影等级")}">${esc(row.lightcone.label)}</td>
    <td class="equip-cell ${row.relics.count ? "" : "empty"}" data-pick-relics="${row.index}"
        title="${esc(relicTip || "点击配置 6 部位遗器（套装 / 主词条 / 副词条）")}">${esc(row.relics.summary)}</td>
    <td><select data-rank-row="${row.index}">
      ${Array.from({ length: 7 }, (_, i) => `<option value="${i}" ${i === row.rank ? "selected" : ""}>${i} 魂</option>`).join("")}
    </select></td>
    ${panels}
  </tr>`;
}

function attacksHtml(state, meta) {
  const attacks = state.config.enemy_attacks || [];
  const names = state.rows.map((r) => r.name || `角色${r.index + 1}`);
  if (!attacks.length) {
    return `<div class="hint">尚未配置敌方攻击（木桩速度为 0，可用这里的调度模拟敌人出手）</div>`;
  }
  const rows = attacks.map((a, i) => {
    const targets = Array.from({ length: 4 }, (_, slot) => {
      const checked = (a.target_indices || []).map(Number).includes(slot);
      return `<label class="hint" style="margin-right:6px">
        <input type="checkbox" data-attack-target="${i}" data-slot="${slot}" ${checked ? "checked" : ""}>${esc(names[slot] || slot + 1)}
      </label>`;
    }).join("");
    return `<tr data-attack-row="${i}">
      <td><input type="number" min="0" step="10" data-attack-field="total_av" data-index="${i}" value="${Number(a.total_av) || 0}"></td>
      <td><select data-attack-field="source_enemy_index" data-index="${i}">
        ${Array.from({ length: 5 }, (_, k) => `<option value="${k}" ${Number(a.source_enemy_index) === k ? "selected" : ""}>敌人 ${k + 1}</option>`).join("")}
      </select></td>
      <td><input type="number" min="0" step="100" data-attack-field="attack" data-index="${i}" value="${Number(a.attack) || 0}"></td>
      <td>${targets}</td>
      <td><input type="number" min="0" step="5" data-attack-field="energy_recover" data-index="${i}" value="${Number(a.energy_recover) || 0}"></td>
      <td><button class="btn small danger" data-attack-del="${i}">删除</button></td>
    </tr>`;
  });
  return `<div class="table-wrap"><table class="grid">
    <thead><tr><th>总行动值</th><th>释放来源</th><th>攻击力</th><th>目标角色</th><th>恢复能量</th><th></th></tr></thead>
    <tbody>${rows.join("")}</tbody>
  </table></div>
  <div class="row" style="margin-top:8px"><button class="btn small" data-act="attack-add">+ 添加一行</button></div>`;
}

export function renderConfig(root, state, meta) {
  const cfg = state.config;
  const enemy = cfg.enemy;
  const battle = cfg.battle;
  const levels = cfg.skill_levels;
  const lim = meta.limits;

  root.innerHTML = `
    <div class="group">
      <h3>队伍配置 · 点击「选」选择角色，点击光锥 / 遗器列配置装备</h3>
      <div class="row" style="margin-bottom:10px">
        <button class="btn" data-act="import">导入 freesr-data.json</button>
        <input type="file" accept=".json,application/json" hidden data-file>
        <button class="btn danger" data-act="reset">重置队伍</button>
        <span class="hint">面板数值可直接编辑，失焦即生效（百分比按 % 输入）</span>
      </div>
      <div class="table-wrap">
        <table class="grid team-table">
          <thead><tr>
            <th>行</th><th>名称</th><th>光锥</th><th>遗器</th><th>星魂</th>
            ${meta.panel_keys.map((key) => `<th title="${esc(meta.panel_labels[key])}">${esc(meta.panel_labels[key])}</th>`).join("")}
          </tr></thead>
          <tbody>${state.rows.map((row) => teamRowHtml(row, meta)).join("")}</tbody>
        </table>
      </div>
    </div>

    <div class="grid2">
      <div class="group" data-config="enemy">
        <h3>敌方配置（木桩，共享全部参数）</h3>
        ${field("数量", `<input type="number" min="${lim.enemy_count[0]}" max="${lim.enemy_count[1]}" data-cfg="enemy" data-key="count" value="${enemy.count}">`)}
        ${field("韧性", `<input type="number" min="${lim.toughness[0]}" max="${lim.toughness[1]}" data-cfg="enemy" data-key="toughness" value="${enemy.toughness}">`)}
        ${field("生命值", `<input type="number" min="1" step="1000" data-cfg="enemy" data-key="hp" value="${enemy.hp}">`)}
        ${field("弱点", `<input type="text" data-cfg="enemy" data-key="weakness" value="${esc(enemy.weakness)}" placeholder="火, 冰">`)}
        ${field("等级", `<input type="number" min="${lim.enemy_level[0]}" max="${lim.enemy_level[1]}" data-cfg="enemy" data-key="level" value="${enemy.level}">`)}
        ${field("非弱点抗性", `<input type="number" min="0" max="100" data-cfg="enemy" data-key="non_weak_resist" value="${enemy.non_weak_resist}"> %`)}
      </div>

      <div class="group">
        <h3>战斗参数</h3>
        ${field("初始 SP", `<input type="number" min="${lim.initial_sp[0]}" max="${lim.initial_sp[1]}" data-cfg="battle" data-key="initial_sp" value="${battle.initial_sp}">`)}
        ${field("最大行动值", `<input type="number" min="${lim.max_av[0]}" max="${lim.max_av[1]}" step="50" data-cfg="battle" data-key="max_av" value="${battle.max_av}">`)}
        ${field("默认操作", `<select data-cfg="battle" data-key="action_mode">
          <option value="0" ${Number(battle.action_mode) === 0 ? "selected" : ""}>智能（终结技 &gt; 战技 &gt; 普攻）</option>
          <option value="1" ${Number(battle.action_mode) === 1 ? "selected" : ""}>全部普攻</option>
          <option value="2" ${Number(battle.action_mode) === 2 ? "selected" : ""}>全部战技（SP 够时）</option>
        </select>`)}
        <h3 style="margin-top:14px">全局技能等级</h3>
        <div class="row">
          ${field("普攻", `<input type="number" min="1" max="10" data-cfg="skill_levels" data-key="normal" value="${levels.normal}">`)}
          ${field("战技", `<input type="number" min="1" max="15" data-cfg="skill_levels" data-key="skill" value="${levels.skill}">`)}
          ${field("终结技", `<input type="number" min="1" max="15" data-cfg="skill_levels" data-key="ultra" value="${levels.ultra}">`)}
        </div>
        <div class="row" style="margin-top:6px">
          ${field("天赋", `<input type="number" min="1" max="15" data-cfg="skill_levels" data-key="talent" value="${levels.talent}">`)}
          ${field("忆灵技", `<input type="number" min="1" max="15" data-cfg="skill_levels" data-key="memo" value="${levels.memo}">`)}
          ${field("欢愉技", `<input type="number" min="1" max="15" data-cfg="skill_levels" data-key="elation" value="${levels.elation}">`)}
        </div>
      </div>
    </div>

    <div class="group" data-attacks>
      <h3>敌方攻击调度</h3>
      ${attacksHtml(state, meta)}
    </div>
  `;
}

// ── 交互模拟 Tab ─────────────────────────────────────────

export function renderInteractive(root, state, meta) {
  const sim = state.sim;
  if (!sim) {
    root.innerHTML = `<div class="empty-state">
      <div>尚未开始交互模拟</div>
      <div class="hint" style="margin-top:8px">「运行模拟」会一次性跑到最大行动值；「开始交互模拟」用于逐步推进并手动释放技能</div>
      <button class="btn primary" data-act="sim-start" style="margin-top:14px">开始交互模拟</button>
    </div>`;
    return;
  }
  const logRows = sim.logs.map((log) => `<tr data-log-index="${log.index}" class="${log.old ? "old" : ""}">
    <td class="dim">${log.turn}</td>
    <td class="num">${log.av.toFixed(1)}</td>
    <td class="num">${log.total_av.toFixed(1)}</td>
    <td>${esc(log.actor)}</td>
    <td>${esc(log.action)}</td>
    <td class="mono">${esc(log.damages)}</td>
    <td class="num">${num(log.total)}</td>
    <td class="dim">${esc(log.notes)}</td>
  </tr>`);
  const ultraButtons = sim.orbs.map((orb, index) => `
    <button class="btn small" data-act="sim-ultra" data-index="${index}" ${sim.can.ultra[index] ? "" : "disabled"}>
      终结技${index + 1} · ${esc(orb.name)}（${Math.round(orb.energy)}）
    </button>`).join("");

  root.innerHTML = `
    <div class="status-bar ${sim.ended ? "ended" : ""}">${sim.status}</div>
    <div class="group">
      <h3>操作 · 键盘：空格=推进　Q=普攻　E=战技　1~4=终结技</h3>
      <div class="ops">
        <button class="btn primary" data-act="sim-start">↻ 重新开始</button>
        <button class="btn" data-act="sim-advance" ${sim.can.advance ? "" : "disabled"}>推进（空格）</button>
        <button class="btn" data-act="sim-normal" ${sim.can.act ? "" : "disabled"}>普攻（Q）</button>
        <button class="btn" data-act="sim-skill" ${sim.can.act ? "" : "disabled"}>战技（E）</button>
        <button class="btn" data-act="sim-rewind" ${sim.can.rewind ? "" : "disabled"}>回溯选中回合</button>
      </div>
      <div class="ultra-row" style="margin-top:10px">${ultraButtons}</div>
      <div class="hint" style="margin-top:8px">回溯：先在下方日志中点选一回合，再点「回溯选中回合」。</div>
    </div>
    <div class="group">
      <h3>交互日志（${sim.logs.length} 条）</h3>
      ${tableHtml(
        ["回合", "AV", "总AV", "行动者", "操作", "伤害明细", "总伤害", "备注"],
        logRows, { empty: "还没有行动记录", extraClass: "log-scroll" },
      )}
    </div>
  `;
}

// ── 结果类 Tab ───────────────────────────────────────────

function noResultHtml(text = "尚无完整模拟结果") {
  return `<div class="empty-state">${esc(text)}
    <div class="hint" style="margin-top:8px">点击左侧「▶ 运行模拟」按当前配置一次性跑到最大行动值</div></div>`;
}

export function renderLogs(root, state) {
  const result = state.result;
  if (!result) {
    root.innerHTML = noResultHtml();
    return;
  }
  const rows = result.logs.map((log) => `<tr>
    <td class="dim">${log.turn}</td>
    <td class="num">${log.av.toFixed(1)}</td>
    <td class="num">${log.total_av.toFixed(1)}</td>
    <td>${esc(log.actor)}</td>
    <td>${esc(log.action)}</td>
    <td class="mono">${esc(log.damages)}</td>
    <td class="num">${num(log.total)}</td>
    <td class="dim">${esc(log.notes)}</td>
  </tr>`);
  root.innerHTML = tableHtml(
    ["回合", "AV", "总AV", "行动者", "操作", "伤害明细", "总伤害", "备注"],
    rows, { extraClass: "log-scroll" },
  );
}

export function renderTimeline(root, state) {
  const result = state.result;
  if (!result || !result.lanes.length) {
    root.innerHTML = noResultHtml("暂无时间轴数据");
    return;
  }
  root.innerHTML = `
    <div class="hint" style="margin-bottom:8px">滚轮缩放横轴（0.5x ~ 8x）、按住拖动平移、悬停查看行动详情</div>
    <div class="gantt-wrap" data-gantt>
      <canvas class="gantt-canvas"></canvas>
      <div class="gantt-tip"></div>
    </div>
  `;
  mountGantt(root.querySelector("[data-gantt]"), result);
}

export function renderPie(root, state) {
  const result = state.result;
  if (!result || !result.pie.length) {
    root.innerHTML = noResultHtml("暂无伤害占比数据");
    return;
  }
  const rankRows = result.ranks.map((item, index) => `<tr>
    <td class="dim">${index + 1}</td>
    <td>${esc(item.name)}</td>
    <td class="dim">${esc(item.path_zh)} · ${esc(item.element_zh)}</td>
    <td class="num">${num(item.damage)}</td>
    <td class="num">${item.share.toFixed(1)}%</td>
  </tr>`);
  root.innerHTML = `
    <div class="group">
      <h3>伤害占比</h3>
      <div class="pie-layout">
        <div>${pieSvg(result.pie)}</div>
        <div>${tableHtml(["#", "角色", "命途 · 属性", "总伤害", "占比"], rankRows)}</div>
      </div>
    </div>
  `;
}

export function renderDetails(root, state) {
  const result = state.result;
  if (!result) {
    root.innerHTML = noResultHtml();
    return;
  }
  const rows = result.logs.map((log) => `<tr>
    <td class="dim">${log.turn}</td>
    <td class="num">${log.total_av.toFixed(1)}</td>
    <td>${esc(log.actor)}</td>
    <td>${esc(log.action)}</td>
    <td>${esc(log.target)}</td>
    <td class="num">${esc(log.segments)}</td>
    <td class="dim">${esc(log.types)}</td>
    <td class="num">${num(log.total)}</td>
    <td class="dim">${esc(log.notes)}</td>
  </tr>`);
  root.innerHTML = tableHtml(
    ["回合", "总AV", "行动者", "操作", "目标", "段数", "伤害类型", "总伤害", "备注"],
    rows, { extraClass: "detail-scroll" },
  );
}

export function renderSummary(root, state) {
  const result = state.result;
  if (!result) {
    root.innerHTML = noResultHtml();
    return;
  }
  const cards = [
    ["总回合数", result.cards.turns, ""],
    ["总行动值", result.cards.total_av, "cyan"],
    ["总伤害", num(result.cards.total_damage), ""],
    ["平均每回合", num(result.cards.avg_per_turn), "purple"],
    ["阿哈时刻", result.cards.aha_count, ""],
    ["最终 SP", result.cards.final_sp, "green"],
  ].map(([title, value, cls]) => `
    <div class="card ${cls}">
      <div class="card-title">${esc(title)}</div>
      <div class="card-value">${esc(value)}</div>
    </div>`).join("");

  const charRows = result.char_summary.map((c) => `<tr>
    <td>${esc(c.name)}</td><td class="dim">${esc(c.path_zh)}</td><td class="dim">${esc(c.element_zh)}</td>
    <td class="num">${num(c.atk)}</td><td class="num">${c.spd}</td>
    <td class="num">${esc(c.crit)}</td><td class="num">${esc(c.energy)}</td>
  </tr>`);
  const enemyRows = result.enemy_summary.map((e) => `<tr>
    <td>${esc(e.name)}</td><td class="num">${esc(e.toughness)}</td><td>${esc(e.broken)}</td>
    <td class="dim">${esc(e.weaknesses || "无")}</td><td class="num">${e.level}</td>
  </tr>`);

  root.innerHTML = `
    <div class="cards">${cards}</div>
    <div class="group" style="margin-top:12px">
      <h3>结束原因：<span class="mono">${esc(result.end_reason)}</span></h3>
    </div>
    <div class="grid2">
      <div class="group"><h3>角色汇总</h3>
        ${tableHtml(["角色", "命途", "属性", "攻击力", "速度", "暴击率 / 暴伤", "能量"], charRows)}
      </div>
      <div class="group"><h3>敌方汇总</h3>
        ${tableHtml(["名称", "韧性", "击破", "弱点", "等级"], enemyRows)}
      </div>
    </div>
  `;
}

// ── 甘特图 ───────────────────────────────────────────────

function mountGantt(host, result) {
  const canvas = host.querySelector("canvas");
  const tip = host.querySelector(".gantt-tip");
  const ctx = canvas.getContext("2d");
  const lanes = result.lanes;
  const maxAv = result.max_av || 300;
  const LEFT = 108;
  const RIGHT = 24;
  const TOP = 26;
  const LANE_H = 46;
  const LANE_GAP = 8;

  let scale = 1;
  let offset = 0;
  let dragging = false;
  let dragStartX = 0;
  let dragStartOffset = 0;

  const laneY = (index) => TOP + index * (LANE_H + LANE_GAP);
  const height = () => TOP + lanes.length * (LANE_H + LANE_GAP) + 20;

  function plotWidth() {
    return Math.max(120, canvas.clientWidth - LEFT - RIGHT);
  }

  function avToX(av) {
    return LEFT + (av / maxAv) * plotWidth() * scale - offset;
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height() * dpr));
    canvas.style.height = `${height()}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function draw() {
    const width = canvas.clientWidth;
    const h = height();
    ctx.clearRect(0, 0, width, h);
    ctx.fillStyle = "#0e1320";
    ctx.fillRect(0, 0, width, h);

    // 纵轴：单位名
    ctx.font = "12px 'Microsoft YaHei UI', sans-serif";
    ctx.textBaseline = "middle";
    lanes.forEach((lane, index) => {
      const y = laneY(index);
      ctx.fillStyle = index % 2 === 0 ? "rgba(30,38,64,.55)" : "rgba(22,28,44,.55)";
      ctx.fillRect(LEFT, y - LANE_H / 2, width - LEFT - RIGHT, LANE_H);
      ctx.fillStyle = "#9ba3b4";
      ctx.textAlign = "right";
      ctx.fillText(lane.name, LEFT - 10, y);
    });

    // 横轴：刻度
    const step = maxAv <= 120 ? 10 : maxAv <= 300 ? 25 : maxAv <= 600 ? 50 : 100;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let av = 0; av <= maxAv; av += step) {
      const x = avToX(av);
      if (x < LEFT - 1 || x > width - RIGHT + 1) continue;
      ctx.strokeStyle = "rgba(42,52,80,.9)";
      ctx.beginPath();
      ctx.moveTo(x, TOP - 12);
      ctx.lineTo(x, h - 8);
      ctx.stroke();
      ctx.fillStyle = "#5c6478";
      ctx.fillText(String(av), x, 6);
    }

    // 行动点
    lanes.forEach((lane, index) => {
      const y = laneY(index);
      lane.actions.forEach((action) => {
        const x = avToX(action.total_av);
        if (x < LEFT - 20 || x > width - RIGHT + 20) return;
        const color = ACTION_COLORS[action.type] || GOLD;
        ctx.beginPath();
        ctx.arc(x, y, 7, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        if (action.broken) {
          ctx.strokeStyle = "#e5544e";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, 11, 0, Math.PI * 2);
          ctx.stroke();
          ctx.lineWidth = 1;
        }
        if (action.damage > 0) {
          ctx.fillStyle = "rgba(228,231,237,.55)";
          ctx.font = "10px Consolas, monospace";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillText(Math.round(action.damage), x, y + 9);
        }
      });
    });
  }

  function hitTest(mouseX, mouseY) {
    for (let index = 0; index < lanes.length; index += 1) {
      const y = laneY(index);
      if (Math.abs(mouseY - y) > 14) continue;
      for (const action of lanes[index].actions) {
        const x = avToX(action.total_av);
        if (Math.abs(mouseX - x) <= 9) {
          return { lane: lanes[index], action };
        }
      }
    }
    return null;
  }

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const avAtMouse = ((mouseX + offset - LEFT) / (plotWidth() * scale)) * maxAv;
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    scale = Math.max(0.5, Math.min(8, scale * factor));
    offset = LEFT + (avAtMouse / maxAv) * plotWidth() * scale - mouseX;
    draw();
  }, { passive: false });

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    dragStartX = event.clientX;
    dragStartOffset = offset;
    canvas.classList.add("dragging");
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    if (dragging) {
      offset = dragStartOffset - (event.clientX - dragStartX);
      const minOffset = -plotWidth() * scale * 0.2;
      const maxOffset = plotWidth() * scale * 1.05;
      offset = Math.max(minOffset, Math.min(maxOffset, offset));
      draw();
      return;
    }
    const found = hitTest(event.clientX - rect.left, event.clientY - rect.top);
    if (found) {
      tip.style.display = "block";
      tip.style.left = `${event.clientX - rect.left + 12}px`;
      tip.style.top = `${event.clientY - rect.top + 12}px`;
      tip.textContent = `${found.lane.name} · ${found.action.label}\n总行动值 ${found.action.total_av.toFixed(1)}`
        + (found.action.damage > 0 ? `\n伤害 ${Math.round(found.action.damage)}` : "")
        + (found.action.note ? `\n${found.action.note}` : "");
    } else {
      tip.style.display = "none";
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    dragging = false;
    canvas.classList.remove("dragging");
    try { canvas.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
  });
  canvas.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  // 只保留最新一次挂载的 resize 监听，避免反复切换 Tab 累积
  if (window.__ganttResize) window.removeEventListener("resize", window.__ganttResize);
  window.__ganttResize = resize;
  window.addEventListener("resize", resize);
  resize();
}

// ── 饼图 ─────────────────────────────────────────────────

function pieSvg(pie) {
  const total = pie.reduce((sum, item) => sum + item.damage, 0) || 1;
  const R = 96;
  const r = 56;
  const cx = 110;
  const cy = 110;
  let angle = -Math.PI / 2;
  const paths = [];
  pie.forEach((item, index) => {
    const share = item.damage / total;
    const delta = share * Math.PI * 2;
    const a0 = angle;
    const a1 = angle + delta;
    angle = a1;
    const large = delta > Math.PI ? 1 : 0;
    const x0 = cx + R * Math.cos(a0);
    const y0 = cy + R * Math.sin(a0);
    const x1 = cx + R * Math.cos(a1);
    const y1 = cy + R * Math.sin(a1);
    const xi1 = cx + r * Math.cos(a1);
    const yi1 = cy + r * Math.sin(a1);
    const xi0 = cx + r * Math.cos(a0);
    const yi0 = cy + r * Math.sin(a0);
    const color = CHART_COLORS[index % CHART_COLORS.length];
    paths.push(`<path d="M ${x0.toFixed(2)} ${y0.toFixed(2)}
        A ${R} ${R} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}
        L ${xi1.toFixed(2)} ${yi1.toFixed(2)}
        A ${r} ${r} 0 ${large} 0 ${xi0.toFixed(2)} ${yi0.toFixed(2)} Z"
      fill="${color}" stroke="#0e1320" stroke-width="1.5">
      <title>${esc(item.name)}：${num(item.damage)}（${item.share.toFixed(1)}%）</title>
    </path>`);
  });
  const legend = pie.map((item, index) => `
    <div><i class="pie-dot" style="background:${CHART_COLORS[index % CHART_COLORS.length]}"></i>
      <span>${esc(item.name)}</span>
      <span class="mono right">${num(item.damage)} · ${item.share.toFixed(1)}%</span>
    </div>`).join("");
  return `<svg class="pie-svg" viewBox="0 0 220 220" role="img" aria-label="伤害占比">
      ${paths.join("")}
      <text x="110" y="105" text-anchor="middle" fill="#e4e7ed" font-size="14" font-weight="700">
        ${num(total)}
      </text>
      <text x="110" y="124" text-anchor="middle" fill="#9ba3b4" font-size="11">总伤害</text>
    </svg>
    <div class="pie-legend" style="margin-top:8px">${legend}</div>`;
}
