/* ============ DOTA2 分锅器 前端逻辑 ============ */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = { payload: null, matchId: null, userId: null, loadingTimer: null };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, 2200);
  }

  function show(el) { el.hidden = false; }
  function hide(el) { el.hidden = true; }

  function setLoading(title, sub) {
    $("#loading-title").textContent = title;
    $("#loading-sub").textContent = sub;
    $("#submit-btn").disabled = true;
  }

  function finishLoading() {
    $("#submit-btn").disabled = false;
    clearInterval(state.loadingTimer);
    state.loadingTimer = null;
  }

  /* ---------------- 请求 ---------------- */
  async function analyze(matchId, userId, refresh) {
    state.matchId = matchId;
    state.userId = userId || null;

    hide($("#error"));
    hide($("#result"));
    show($("#loading"));
    setLoading("正在拉取对局数据…", "首次分析需要几秒；OpenDota 未解析的对局会自动提交解析请求");

    const stages = [
      [1400, "正在拉取对局数据…", "OpenDota 请求中…"],
      [4200, "正在计算分锅…", "按号位加权：送 / 经济 / 输出 / 参团 / 推塔 / 视野"],
      [9000, "正在生成判决书…", "快好了，大哥别催"],
    ];
    clearInterval(state.loadingTimer);
    let si = 0;
    state.loadingTimer = setInterval(() => {
      if (si < stages.length) {
        const [delay, t, s] = stages[si];
        si++;
        setTimeout(() => setLoading(t, s), delay);
      }
    }, 500);

    try {
      const qs = new URLSearchParams({ match_id: String(matchId) });
      if (userId) qs.set("user_id", String(userId));
      if (refresh) qs.set("refresh", "1");
      const res = await fetch("/api/analyze?" + qs.toString());
      let data;
      try {
        data = await res.json();
      } catch (e) {
        throw new Error("服务器返回异常（HTTP " + res.status + "）");
      }
      if (!res.ok || !data.ok) throw new Error(data.error || "请求失败（HTTP " + res.status + "）");

      state.payload = data;
      render(data);
      hide($("#loading"));
      show($("#result"));
      updateUrl();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      hide($("#loading"));
      $("#error-msg").textContent = e.message || String(e);
      show($("#error"));
    } finally {
      finishLoading();
    }
  }

  function updateUrl() {
    const qs = new URLSearchParams({ match_id: String(state.matchId) });
    if (state.userId) qs.set("user_id", String(state.userId));
    history.replaceState(null, "", "?" + qs.toString());
  }

  /* ---------------- 渲染 ---------------- */
  function render(p) {
    renderMatchBar(p);
    renderVerdict(p);
    renderBoard(p);
    renderTabs(p);
    renderActions(p);
  }

  function renderMatchBar(p) {
    const info = p.info;
    const lose = info.result.indexOf("获胜") === -1;
    const pills = [];
    pills.push('<span class="pill ' + (lose ? "lose" : "win") + '">' + esc(info.result) + "</span>");
    pills.push('<span class="pill strong">天辉 ' + esc(info.score) + " 夜魇</span>");
    pills.push('<span class="pill">' + esc(info.duration) + "</span>");
    pills.push('<span class="pill">' + esc(info.mode) + "</span>");
    pills.push('<span class="pill">对局 ' + esc(p.match_id) + "</span>");
    pills.push('<span class="pill">' + esc(info.start) + "</span>");
    if (!info.parsed) pills.push('<span class="pill lose">⚠ 未解析（聚合数据）</span>');
    let html = pills.join("");
    if (info.building) html += '<div class="building">' + esc(info.building) + "</div>";
    $("#match-bar").innerHTML = html;
  }

  function renderVerdict(p) {
    const v = p.verdict;
    const top = p.players[0] || {};
    const tags = (top.tags || []).map((t) => '<span class="tag">' + esc(t) + "</span>").join("");
    const me = v.is_me ? " <em>（你）</em>" : "";
    $("#verdict").innerHTML =
      '<div class="verdict-label">锅 王</div>' +
      '<div class="verdict-main">' +
        '<div class="v-name">' + esc(v.name) + me + "</div>" +
        '<div class="v-hero">' + esc(v.pos) + "号位 · " + esc(v.hero_cn) + "</div>" +
        '<div class="v-share">' + esc(v.share) + "%<small>的锅</small></div>" +
      "</div>" +
      '<div class="v-tags">' + tags + "</div>";
  }

  function barWidth(share, topShare) {
    const top = Math.max(topShare || 1, 1);
    return Math.min(100, (Number(share) / top) * 100);
  }

  function renderBoard(p) {
    const topShare = Math.max.apply(null, p.players.map((x) => Number(x.share) || 0));
    const rows = p.players.map((pl) => {
      const me = pl.is_me ? " me" : "";
      const first = pl.rank === 1 ? " first" : "";
      const meTag = pl.is_me ? " <em>（你）</em>" : "";
      const tags = (pl.tags || []).map((t) => "<span>" + esc(t) + "</span>").join("");
      return (
        '<div class="brow' + me + first + '">' +
          '<div class="b-rank">' + pl.rank + "</div>" +
          '<div class="b-main">' +
            '<div class="b-name">' + esc(pl.name) + meTag + "</div>" +
            '<div class="b-meta">' + esc(pl.hero_cn) + " · " + pl.pos + "号位 · " + esc(pl.kda) + "</div>" +
            '<div class="b-tags">' + tags + "</div>" +
          "</div>" +
          '<div class="b-bar"><i style="width:' + barWidth(pl.share, topShare).toFixed(1) + '%"></i></div>' +
          '<div class="b-pct">' + Number(pl.share).toFixed(1) + "%</div>" +
        "</div>"
      );
    }).join("");

    let crash = "";
    const c = p.crash;
    if (c) {
      const chips = [];
      chips.push("<span>前 10 分钟人头 " + c.early_my + " : " + c.early_opp + "</span>");
      if (c.max_lead > 0) chips.push("<span>最多领先 " + c.max_lead + "（第 " + c.max_lead_min + " 分钟）</span>");
      (c.marks || []).forEach((m) => chips.push("<span>第 " + m.minute + " 分钟落后破 " + m.label + "</span>"));
      crash = '<div class="crash">' +
        '<div class="crash-title">📉 崩盘时间线（我方视角）</div>' +
        '<div class="crash-line">' + chips.join("") + "</div>" +
        "</div>";
    }

    $("#board").innerHTML =
      '<div class="board-title">🍳 锅榜 <span>按号位加权 · 同英雄基准百分位</span></div>' +
      rows + crash;
  }

  function compClass(v) {
    if (v == null) return "comp";
    const n = Number(v);
    if (n >= 75) return "comp hot";
    if (n >= 50) return "comp warm";
    if (n < 25) return "comp good";
    return "comp";
  }

  function renderTabs(p) {
    const parsed = !!p.info.parsed;
    const tabs = [
      { id: "players", label: "逐人判决", ready: true },
      { id: "jungle", label: "野区把线", ready: parsed },
      { id: "deaths", label: "死亡时间线", ready: parsed },
      { id: "vision", label: "视野职责", ready: parsed },
      { id: "items", label: "装备时间线", ready: parsed },
      { id: "enemy", label: "对面为什么赢", ready: true },
      { id: "md", label: "完整判决书", ready: true },
    ];

    const nav = tabs.map((t, i) =>
      '<button class="tab-btn' + (i === 0 ? " active" : "") + '" data-tab="' + t.id + '"' +
      (t.ready ? "" : ' title="本局未被 OpenDota 解析"') + ">" + t.label + "</button>"
    ).join("");

    let panels = "";
    panels += '<div class="tab-panel active" id="panel-players">' + playersPanel(p) + "</div>";
    panels += '<div class="tab-panel" id="panel-jungle">' + (parsed ? junglePanel(p) : notParsedNote()) + "</div>";
    panels += '<div class="tab-panel" id="panel-deaths">' + (parsed ? deathsPanel(p) : notParsedNote()) + "</div>";
    panels += '<div class="tab-panel" id="panel-vision">' + (parsed ? visionPanel(p) : notParsedNote()) + "</div>";
    panels += '<div class="tab-panel" id="panel-items">' + (parsed ? itemsPanel(p) : notParsedNote()) + "</div>";
    panels += '<div class="tab-panel" id="panel-enemy">' + enemyPanel(p) + "</div>";
    panels += '<div class="tab-panel" id="panel-md"><div class="md-box" id="md-box">' +
      esc(p.report_md || "") + "</div></div>";

    let banner = "";
    if (!parsed) {
      banner = '<div class="crash-note" style="margin-bottom:14px;">⚠️ 本局 OpenDota 尚未解析，野区 / 死亡时间线 / 视野 / 装备等高级功能暂不可用。' +
        '已自动提交解析请求，通常 1~10 分钟后可点「重新分析」升级为精确版。</div>';
    }

    $("#tabs").innerHTML = '<div class="tabs-nav">' + nav + "</div>" + banner + panels;

    $$("#tabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$("#tabs .tab-btn").forEach((b) => b.classList.remove("active"));
        $$("#tabs .tab-panel").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        const panel = $("#panel-" + btn.dataset.tab);
        if (panel) panel.classList.add("active");
      });
    });
  }

  function notParsedNote() {
    return '<div class="crash-note">该模块需要 OpenDota 解析数据，本局暂未解析。</div>';
  }

  function playersPanel(p) {
    return p.players.map((pl) => {
      const me = pl.is_me ? " <em>（你）</em>" : "";
      const rankCls = pl.rank === 1 ? " first" : "";
      const tags = (pl.tags || []).map((t) => '<span class="tag">' + esc(t) + "</span>").join("");
      const comps = ["feed", "farm", "dmg", "assist", "obj", "vision"].map((k) => {
        const names = { feed: "送", farm: "经济", dmg: "输出", assist: "参团", obj: "推塔", vision: "视野" };
        const v = pl.comp ? pl.comp[k] : null;
        if (v == null) return "";
        return '<span class="' + compClass(v) + '">' + names[k] + " " + Math.round(v) + "</span>";
      }).join("");
      const verdict = (pl.verdict || []).map((line) => "<li>" + esc(line) + "</li>").join("");
      return (
        '<div class="pcard">' +
          '<div class="pcard-head">' +
            '<span class="pcard-rank' + rankCls + '">' + pl.rank + "</span>" +
            '<span class="pcard-name">' + esc(pl.name) + me + "</span>" +
            '<span class="pcard-meta">' + esc(pl.hero_cn) + " · " + pl.pos + "号位</span>" +
            '<span class="pcard-share">' + Number(pl.share).toFixed(1) + "%</span>" +
          "</div>" +
          '<div class="pcard-tags">' + tags + "</div>" +
          '<div class="stat-grid">' +
            '<div class="stat"><b>' + esc(pl.kda) + "</b><span>KDA</span></div>" +
            '<div class="stat"><b>' + pl.lh + "</b><span>正补</span></div>" +
            '<div class="stat"><b>' + pl.gpm + "</b><span>GPM</span></div>" +
            '<div class="stat"><b>' + pl.hero_damage + "</b><span>英雄伤害</span></div>" +
            '<div class="stat"><b>' + pl.tower_damage + "</b><span>建筑伤害</span></div>" +
            '<div class="stat"><b>' + Number(pl.tfp).toFixed(0) + "%</b><span>参团率</span></div>" +
          "</div>" +
          '<div class="comp-row">' + comps + "</div>" +
          '<ul class="verdict-list">' + verdict + "</ul>" +
        "</div>"
      );
    }).join("");
  }

  function junglePanel(p) {
    const rows = p.players.map((pl) => {
      if (!pl.extra) return "";
      const me = pl.is_me ? " me" : "";
      return "<tr class='" + me.trim() + "'>" +
        "<td>" + esc(pl.name) + (pl.is_me ? "（你）" : "") + "</td>" +
        '<td class="num">' + pl.extra.neutral_kills + "</td>" +
        '<td class="num">' + pl.extra.ancient_kills + "</td>" +
        '<td class="num">' + Number(pl.extra.tf_share).toFixed(1) + "%</td>" +
        '<td class="num">' + pl.extra.zero_farm + "</td>" +
        '<td class="num">' + pl.extra.tf_died + "</td>" +
        '<td class="num">' + Number(pl.tfp).toFixed(0) + "%</td>" +
        "</tr>";
    }).join("");
    let callout = "";
    if (p.suspect) {
      const s = p.suspect;
      callout = '<div class="crash-note" style="margin-bottom:12px;">🌲 <b>嫌疑人：' +
        esc(s.name) + (s.is_me ? "（你）" : "") + "（" + esc(s.hero_cn) + "，" + s.pos + "号位）</b> —— " +
        "野怪 " + s.neutral_kills + " 只（队内第 " + s.neutral_rank + "），参团率仅 " + s.part +
        "%，" + s.zero_farm + " 场团战 0 伤害且当时经济在涨。</div>";
    }
    return callout +
      '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      "<th>玩家</th><th>野怪击杀</th><th>远古</th><th>团战伤害占比</th><th>有效0伤团</th><th>团战阵亡</th><th>参团率</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function deathsPanel(p) {
    const rows = p.players.map((pl) => {
      if (!pl.extra) return "";
      return "<tr class='" + (pl.is_me ? "me" : "") + "'>" +
        "<td>" + esc(pl.name) + (pl.is_me ? "（你）" : "") + "</td>" +
        '<td class="num">' + pl.extra.early + "</td>" +
        '<td class="num">' + pl.extra.mid + "</td>" +
        '<td class="num">' + pl.extra.late + "</td>" +
        '<td class="num">' + pl.extra.fed + "</td>" +
        '<td class="num">' + pl.extra.tf_died + "</td>" +
        "</tr>";
    }).join("");
    return '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      "<th>玩家</th><th>前10分钟</th><th>10-25分钟</th><th>25分钟后</th><th>共送金</th><th>团战阵亡</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      '<div class="crash-note">送金 = 死亡时送给对面的金币总额；团战阵亡 = 在团战窗口内阵亡次数。</div>';
  }

  function visionPanel(p) {
    const rows = p.players.map((pl) => {
      const ex = pl.extra || {};
      return "<tr class='" + (pl.is_me ? "me" : "") + "'>" +
        "<td>" + esc(pl.name) + (pl.is_me ? "（你）" : "") + "</td>" +
        '<td class="num">' + (ex.obs == null ? "—" : ex.obs) + "</td>" +
        '<td class="num">' + (ex.sen == null ? "—" : ex.sen) + "</td>" +
        '<td class="num">' + (ex.buyback || 0) + "</td>" +
        '<td class="num">' + (ex.camps_stacked || 0) + "</td>" +
        "</tr>";
    }).join("");
    return '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      "<th>玩家</th><th>假眼</th><th>真眼</th><th>买活</th><th>堆野</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }

  function itemsPanel(p) {
    return p.players.map((pl) => {
      if (!pl.extra || !pl.extra.items || !pl.extra.items.length) return "";
      const list = pl.extra.items.map((it) => esc(it.name) + " " + fmtTime(it.time)).join(" / ");
      return '<div class="enemy-card" style="background:rgba(255,255,255,0.03);border-color:var(--card-border);">' +
        "<b>" + esc(pl.name) + (pl.is_me ? "（你）" : "") + "</b> <span>" + esc(pl.hero_cn) + "</span>" +
        '<span style="width:100%;color:#cfcfdc;">' + list + "</span></div>";
    }).join("") || notParsedNote();
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
  }

  function enemyPanel(p) {
    return p.enemy_top.map((e) =>
      '<div class="enemy-card"><b>' + esc(e.name) + "</b>" +
      "<span>" + esc(e.hero_cn) + "</span>" +
      "<span>KDA " + esc(e.kda) + "</span>" +
      "<span>" + e.gpm + " GPM</span>" +
      "<span>" + e.hero_damage + " 英雄伤害</span>" +
      "<span>" + e.lh + " 正补</span></div>"
    ).join("") || '<div class="crash-note">暂无数据</div>';
  }

  /* ---------------- 操作区 ---------------- */
  function renderActions(p) {
    const parsed = !!p.info.parsed;
    $("#actions").innerHTML =
      '<button class="btn-secondary" id="btn-card" type="button">🖼 分享卡片</button>' +
      '<button class="btn-secondary" id="btn-md" type="button">📄 下载判决书</button>' +
      '<button class="btn-secondary" id="btn-copy" type="button">🔗 复制链接</button>' +
      (parsed ? "" : '<button class="btn-secondary" id="btn-refresh" type="button">🔄 重新分析</button>') +
      '<span class="grow"></span>' +
      '<span class="tip">分锅是玄学，数据仅供友好互喷</span>';

    $("#btn-card").addEventListener("click", openCard);
    $("#btn-md").addEventListener("click", downloadReport);
    $("#btn-copy").addEventListener("click", copyLink);
    const rf = $("#btn-refresh");
    if (rf) rf.addEventListener("click", () => analyze(state.matchId, state.userId, true));
  }

  function apiQuery(extra) {
    const qs = new URLSearchParams({ match_id: String(state.matchId) });
    if (state.userId) qs.set("user_id", String(state.userId));
    if (extra) extra(qs);
    return qs.toString();
  }

  async function openCard() {
    const modal = $("#modal");
    show(modal);
    const img = $("#modal-img");
    const sp = $("#modal-spinner");
    img.hidden = true;
    sp.hidden = false;

    try {
      const res = await fetch("/api/card?" + apiQuery());
      if (!res.ok) throw new Error("生成卡片失败（HTTP " + res.status + "）");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      img.src = url;
      img.hidden = false;
      const dl = $("#modal-download");
      dl.href = url;
      dl.download = "dota-blame-" + state.matchId + ".png";
    } catch (e) {
      toast(e.message || "生成卡片失败");
      hide(modal);
    } finally {
      $("#modal-spinner").hidden = true;
    }
  }

  async function downloadReport() {
    try {
      const res = await fetch("/api/report?" + apiQuery());
      if (!res.ok) throw new Error("下载失败（HTTP " + res.status + "）");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "dota-blame-" + state.matchId + ".md";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
      toast("判决书已下载");
    } catch (e) {
      toast(e.message || "下载失败");
    }
  }

  async function copyLink() {
    const url = location.origin + location.pathname + "?" + apiQuery();
    try {
      await navigator.clipboard.writeText(url);
      toast("链接已复制，发到群里让他们也来看看");
    } catch (e) {
      toast(url);
    }
  }

  /* ---------------- 事件绑定 ---------------- */
  function submit(matchId, userId) {
    matchId = String(matchId || "").trim();
    if (!/^\d{6,}$/.test(matchId)) {
      toast("对局 ID 应该是一串数字");
      return;
    }
    if (userId) localStorage.setItem("dota_blame_user", String(userId));
    else localStorage.removeItem("dota_blame_user");
    analyze(matchId, userId || null, false);
  }

  $("#blame-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submit($("#match-id").value, $("#user-id").value.trim());
  });

  $$(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $("#match-id").value = chip.dataset.match || "";
      $("#user-id").value = chip.dataset.user || "";
      submit(chip.dataset.match, chip.dataset.user);
    });
  });

  $("#modal-close").addEventListener("click", () => hide($("#modal")));
  $("#modal").addEventListener("click", (e) => {
    if (e.target === $("#modal")) hide($("#modal"));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide($("#modal"));
  });

  /* ---------------- 初始化 ---------------- */
  (function init() {
    const saved = localStorage.getItem("dota_blame_user");
    if (saved) $("#user-id").value = saved;
    const qs = new URLSearchParams(location.search);
    const matchId = qs.get("match_id");
    const userId = qs.get("user_id");
    if (matchId) {
      $("#match-id").value = matchId;
      if (userId) $("#user-id").value = userId;
      analyze(matchId, userId || saved, false);
    }
  })();
})();
