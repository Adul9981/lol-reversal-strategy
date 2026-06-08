"""
Step 8: 生成小局分析 HTML 结果页
输入: data/game_winner_markets/game_analysis_v3.json  (含精确游戏开始时间)
输出: output/matches_game_level.html
"""

import json, math
from pathlib import Path

BASE = Path(__file__).parent.parent
ANALYSIS_FILE = BASE / "data/game_winner_markets/game_analysis_v3.json"
BS_FILE       = BASE / "data/game_winner_markets/game_battle_state.json"
OUT_FILE = BASE / "output/matches_game_level.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LoL 小局反转分析 · Polymarket</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; font-size: 14px; }

.header { padding: 24px 32px 16px; border-bottom: 1px solid #1e2535; }
.header h1 { font-size: 20px; font-weight: 700; color: #f1f5f9; }
.header p  { color: #64748b; font-size: 13px; margin-top: 4px; }

.explain-box { margin: 16px 32px; padding: 14px 18px; background: #131a2e; border: 1px solid #1e3a5f; border-radius: 8px; font-size: 12px; color: #94a3b8; line-height: 1.8; }
.explain-box strong { color: #60a5fa; }
.explain-box .note { color: #475569; font-size: 11px; margin-top: 6px; }

.stats-bar { display: flex; gap: 28px; padding: 16px 32px; border-bottom: 1px solid #1e2535; flex-wrap: wrap; }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat-val { font-size: 22px; font-weight: 700; color: #f1f5f9; }
.stat-lbl { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }

.controls { display: flex; gap: 10px; padding: 14px 32px; border-bottom: 1px solid #1e2535; flex-wrap: wrap; align-items: center; }
.filter-btn { padding: 5px 14px; border-radius: 6px; border: 1px solid #2d3748; background: transparent; color: #94a3b8; cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s; }
.filter-btn:hover, .filter-btn.active { background: #1e40af; border-color: #3b82f6; color: #fff; }
.search-box { padding: 5px 12px; border-radius: 6px; border: 1px solid #2d3748; background: #1a2035; color: #e2e8f0; font-size: 13px; width: 200px; outline: none; }
.search-box::placeholder { color: #4a5568; }
.sep { color: #2d3748; }
label { font-size: 12px; color: #64748b; }
select.inline-sel { background:#1a2035; color:#e2e8f0; border:1px solid #2d3748; border-radius:4px; padding:3px 6px; font-size:12px; }

.page-info { font-size: 12px; color: #475569; padding: 6px 32px 4px; }

.table-wrap { overflow-x: auto; padding: 0 32px 40px; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
thead th {
  padding: 9px 12px; text-align: left; font-size: 11px; font-weight: 600;
  color: #64748b; text-transform: uppercase; letter-spacing: .06em;
  border-bottom: 2px solid #1e2535; white-space: nowrap; cursor: pointer; user-select: none;
}
thead th:hover { color: #94a3b8; }
tbody tr { border-bottom: 1px solid #1a2035; transition: background .1s; }
tbody tr:hover { background: #161d2e; }
tbody tr.hidden { display: none; }
tbody td { padding: 10px 12px; vertical-align: middle; }

/* Column: Date */
.td-date .d-date { font-size: 13px; font-weight: 500; color: #cbd5e1; }
.td-date .d-time { font-size: 11px; color: #475569; margin-top: 2px; }

/* Column: Match */
.td-match { min-width: 220px; }
.winner-name { font-size: 13px; font-weight: 700; color: #4ade80; }
.vs-sep { color: #2d3748; margin: 0 5px; font-size: 11px; }
.loser-name { font-size: 13px; color: #64748b; }
.match-tags { margin-top: 4px; display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }

.league-badge { display:inline-block; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:700; }
.lg-LCK { background:#1a2e1a; color:#4ade80; }
.lg-LPL { background:#2e1a1a; color:#f87171; }
.lg-LEC { background:#1a1f2e; color:#60a5fa; }
.lg-LCS { background:#2e261a; color:#fbbf24; }

.game-badge { display:inline-block; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; background:#1e2535; color:#94a3b8; }

.signal-badge { display:inline-flex; align-items:center; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; }
.sig-extreme { background:#430b0b; color:#ef4444; }
.sig-deep    { background:#431407; color:#fb923c; }
.sig-mid     { background:#312e81; color:#a78bfa; }
.sig-none    { background:#1e2535; color:#64748b; }

/* Column: Price Journey (赛前 → 最低 → 最终) */
.td-journey { min-width: 200px; }
.journey-row { display: flex; align-items: center; gap: 6px; }
.journey-label { font-size: 10px; color: #475569; text-align: center; margin-top: 2px; }
.j-box {
  display: flex; flex-direction: column; align-items: center;
  min-width: 44px;
}
.j-price {
  font-size: 16px; font-weight: 700; line-height: 1;
}
.j-arrow { color: #334155; font-size: 14px; padding-bottom: 14px; }

.p-open   { color: #94a3b8; }
.p-high   { color: #94a3b8; }
.p-30     { color: #eab308; }
.p-20     { color: #fb923c; }
.p-10     { color: #ef4444; }
.p-final  { color: #4ade80; }

/* Mini bar under price */
.mini-bar { width: 44px; height: 3px; background: #1e2535; border-radius: 2px; margin-top: 3px; }
.mini-fill { height: 100%; border-radius: 2px; }

/* Column: Timing */
.td-timing { white-space: nowrap; min-width: 120px; }
.t-main { font-size: 14px; font-weight: 700; color: #60a5fa; }
.t-range { font-size: 11px; color: #475569; margin-top: 2px; }
.t-dur   { font-size: 11px; color: #334155; margin-top: 1px; }

/* Column: Result */
.td-result { white-space: nowrap; text-align: center; }
.result-win { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; }
.result-check { font-size: 20px; }
.result-label { font-size: 11px; color: #4ade80; font-weight: 600; }
.result-price { font-size: 11px; color: #475569; }

/* Column: Volume */
.td-vol { font-size: 12px; color: #64748b; white-space: nowrap; }

/* ── Trading Guide ─────────────────────────────────── */
.trading-guide {
  position: sticky; top: 0; z-index: 200;
  background: #0d1117; border-bottom: 2px solid #1a3a2a;
}
.tg-bar {
  display: flex; align-items: center; gap: 14px;
  padding: 10px 32px; background: #0a1a10;
  border-bottom: 1px solid #1a3a2a;
}
.tg-title { font-size: 16px; font-weight: 800; color: #4ade80; letter-spacing: .02em; }
.tg-ver   { font-size: 12px; color: #94a3b8; padding: 2px 8px; background: #1e2535; border-radius: 4px; }
.tg-sub   { font-size: 13px; color: #94a3b8; margin-left: 4px; }
.tg-spacer { flex: 1; }
.tg-toggle {
  padding: 5px 16px; border-radius: 5px; border: 1px solid #4ade80;
  background: transparent; color: #4ade80; cursor: pointer; font-size: 13px; font-weight: 700;
  transition: all .15s;
}
.tg-toggle:hover { background: #0a2a1a; }

.tg-body {
  display: flex; gap: 0; padding: 14px 24px 16px;
  overflow-x: auto; align-items: stretch;
}

.tg-col {
  padding: 0 22px; min-width: 150px; flex-shrink: 0;
  border-right: 1px solid #2d3748;
}
.tg-col:first-child { padding-left: 8px; }
.tg-col:last-child  { border-right: none; }

.tg-col-head {
  font-size: 12px; font-weight: 700; color: #94a3b8;
  text-transform: uppercase; letter-spacing: .05em;
  margin-bottom: 10px; padding-bottom: 6px;
  border-bottom: 1px solid #2d3748;
}
.tg-col-head .step-num {
  display: inline-block; width: 18px; height: 18px; line-height: 18px;
  text-align: center; border-radius: 50%; font-size: 11px; font-weight: 800;
  background: #1e3a2e; color: #4ade80; margin-right: 6px;
}

.tg-row { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; font-size: 14px; }
.tg-row:last-child { margin-bottom: 0; }

/* League rows */
.tg-ok   { color: #4ade80; font-weight: 600; }
.tg-warn { color: #fbbf24; font-weight: 600; }
.tg-bad  { color: #f87171; font-weight: 600; }

/* Condition chip */
.tg-chip {
  font-size: 13px; font-weight: 700; color: #f1f5f9;
  background: #2d3748; padding: 3px 10px; border-radius: 5px;
}
.tg-chip.green  { background: #0f2a1c; color: #4ade80; border: 1px solid #1a4a2e; }
.tg-chip.yellow { background: #2a200a; color: #fbbf24; }
.tg-chip.purple { background: #1e1535; color: #c4b5fd; }

.tg-lbl { font-size: 13px; color: #94a3b8; min-width: 58px; flex-shrink: 0; }

/* Live value placeholder (future Livestats auto-fill) */
.tg-live {
  font-size: 11px; color: #475569; padding: 2px 7px;
  border: 1px dashed #2d3748; border-radius: 4px;
  font-style: italic; background: #0f1621;
}

/* Exit / hold section */
.tg-exit-row { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px; font-size: 13px; color: #cbd5e1; }
.tg-exit-icon { flex-shrink: 0; font-size: 15px; }
.tg-exit-val { font-weight: 800; color: #fbbf24; font-size: 14px; }
.tg-exit-note { color: #64748b; font-size: 12px; margin-top: 2px; }

/* Analysis Panels */
.analysis-panels { padding: 16px 32px; border-bottom: 1px solid #1e2535; display: flex; flex-direction: column; gap: 16px; }
.panel { background: #111827; border: 1px solid #1e2535; border-radius: 8px; overflow: hidden; }
.panel-row { display: flex; gap: 16px; }
.panel-half { flex: 1; min-width: 0; }
.panel-title { padding: 10px 16px; background: #0f1621; font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; border-bottom: 1px solid #1e2535; }
.panel-note { font-weight: 400; color: #475569; text-transform: none; letter-spacing: 0; }
.panel-body { padding: 12px 16px; }

.ev-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ev-table th { padding: 6px 10px; text-align: left; color: #475569; font-weight: 600; font-size: 11px; border-bottom: 1px solid #1e2535; white-space: nowrap; }
.ev-table td { padding: 7px 10px; border-bottom: 1px solid #0f1621; white-space: nowrap; }
.ev-table tr:last-child td { border-bottom: none; }
.ev-table tr:hover td { background: #161d2e; }
.ev-positive { color: #4ade80; font-weight: 700; }
.ev-negative { color: #f87171; }
.ev-near     { color: #fbbf24; }
.wr-badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; }
.wr-low  { background: #2e1a1a; color: #f87171; }
.wr-mid  { background: #2e261a; color: #fbbf24; }
.wr-ok   { background: #1a2e1a; color: #4ade80; }
.verdict { font-size: 11px; font-weight: 600; }

.ev-note { font-size: 11px; color: #475569; margin-top: 10px; line-height: 1.7; padding: 8px 10px; background: #0f1621; border-radius: 5px; }
.ev-note strong { color: #fbbf24; }

/* B-type strategy styles */
.b-warn-row td   { background: #1f0a0a !important; }
.b-best-row td   { background: #0a1f0a !important; }
.b-wr-row td     { background: #0a1020 !important; }
.b-verdict-best  { color: #4ade80; font-weight: 700; }
.b-verdict-wr    { color: #60a5fa; font-weight: 700; }
.b-verdict-risky { color: #fbbf24; font-weight: 600; }
.b-verdict-warn  { color: #f87171; font-weight: 700; }
.b-verdict-ok    { color: #94a3b8; }

/* Timing chart */
.bar-row { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12px; }
.bar-label { width: 80px; color: #64748b; text-align: right; flex-shrink: 0; }
.bar-track { flex: 1; background: #1e2535; border-radius: 3px; height: 18px; position: relative; }
.bar-fill  { height: 100%; border-radius: 3px; background: #3b82f6; display: flex; align-items: center; padding-left: 6px; transition: width .3s; }
.bar-count { font-size: 11px; font-weight: 700; color: #fff; white-space: nowrap; }
.bar-count-out { font-size: 11px; color: #475569; margin-left: 6px; }
</style>
</head>
<body>

<!-- ── Trading Guide (sticky top) ── -->
<div class="trading-guide" id="trading-guide">
  <div class="tg-bar">
    <span class="tg-title">⚡ 实战检查清单</span>
    <span class="tg-ver">v1.1</span>
    <span class="tg-sub">全部满足再下单 · 有疑虑宁可放弃</span>
    <span class="tg-spacer"></span>
    <button class="tg-toggle" id="tg-btn" onclick="toggleGuide()">收起 ▲</button>
  </div>

  <div class="tg-body" id="tg-body">

    <!-- ① 联赛 -->
    <div class="tg-col">
      <div class="tg-col-head"><span class="step-num">1</span>联赛筛选</div>
      <div class="tg-row tg-ok">🟢 <strong>LCK</strong>&nbsp;优先执行</div>
      <div class="tg-row tg-ok">🟢 <strong>LEC</strong>&nbsp;优先执行</div>
      <div class="tg-row tg-warn">⚠️ <strong>LPL</strong>&nbsp;主观判断</div>
      <div class="tg-row tg-bad">🔴 <strong>LCS</strong>&nbsp;基本跳过</div>
    </div>

    <!-- ② 赔率·时间 -->
    <div class="tg-col">
      <div class="tg-col-head"><span class="step-num">2</span>赔率 · 时间</div>
      <div class="tg-row">
        <span class="tg-lbl">当前赔率</span>
        <span class="tg-chip green">≤ 20%</span>
        <span style="font-size:10px;color:#475569">彩票目标≤10%</span>
      </div>
      <div class="tg-row">
        <span class="tg-lbl">游戏时间</span>
        <span class="tg-chip green">20–30 分钟</span>
      </div>
      <div style="font-size:12px;color:#64748b;margin-top:8px;line-height:1.8">
        &lt;10分 = 开局噪音 ❌<br>
        &gt;35分 = 窗口关闭 ❌
      </div>
    </div>

    <!-- ③ 战局核查 -->
    <div class="tg-col" style="min-width:180px">
      <div class="tg-col-head"><span class="step-num">3</span>战局核查 <span style="font-weight:400;color:#64748b;text-transform:none;letter-spacing:0">Livestats</span></div>
      <div class="tg-row">
        <span class="tg-lbl">金币差</span>
        <span class="tg-chip green">&gt; −3000</span>
        <span class="tg-live" data-field="gold_diff">实时</span>
      </div>
      <div class="tg-row">
        <span class="tg-lbl">对方龙数</span>
        <span class="tg-chip green">≤ 2 条</span>
        <span class="tg-live" data-field="opp_dragons">实时</span>
      </div>
      <div class="tg-row">
        <span class="tg-lbl">对方水晶</span>
        <span class="tg-chip green">= 0</span>
        <span class="tg-live" data-field="opp_inhibs">实时</span>
      </div>
      <div style="font-size:13px;color:#a78bfa;margin-top:8px;line-height:1.9">
        ⭐ 存活核心 ≥ 1<br>
        ⭐ 男爵即将刷新
      </div>
    </div>

    <!-- 💰 下注 -->
    <div class="tg-col" style="min-width:200px">
      <div class="tg-col-head">💰 下注金额
        <span style="font-weight:400;text-transform:none;letter-spacing:0;color:#64748b">
          总资金 $<input id="bankroll-input" type="number" value="500" min="1"
            style="width:64px;background:#1e2535;border:1px solid #4ade80;border-radius:4px;
                   color:#4ade80;font-size:13px;font-weight:700;padding:1px 6px;outline:none;">
        </span>
      </div>
      <div class="tg-row">
        <span class="tg-chip" style="min-width:52px;text-align:center">≤ 10%</span>
        <span style="color:#ef4444;font-weight:700;min-width:42px">彩票型</span>
        <span style="color:#94a3b8;font-size:12px">每次下注</span>
        <span id="sz-lottery" style="color:#fbbf24;font-weight:800;font-size:20px">$3.8</span>
      </div>
      <div class="tg-row">
        <span class="tg-chip" style="min-width:52px;text-align:center">11–20%</span>
        <span style="color:#fb923c;font-weight:700;min-width:42px">深度型</span>
        <span style="color:#94a3b8;font-size:12px">每次下注</span>
        <span id="sz-deep" style="color:#fbbf24;font-weight:800;font-size:20px">$8</span>
      </div>
      <div class="tg-row">
        <span class="tg-chip" style="min-width:52px;text-align:center">21–30%</span>
        <span style="color:#a78bfa;font-weight:700;min-width:42px">稳健型</span>
        <span style="color:#94a3b8;font-size:12px">每次下注</span>
        <span id="sz-stable" style="color:#fbbf24;font-weight:800;font-size:20px">$15</span>
      </div>
      <div style="font-size:12px;color:#475569;margin-top:6px">连输10次也撑得住</div>
    </div>

    <!-- 📤 止盈·持仓 -->
    <div class="tg-col" style="min-width:160px">
      <div class="tg-col-head">📤 止盈 · 持仓</div>
      <div class="tg-exit-row">
        <span class="tg-exit-icon">🎯</span>
        <div>
          <div>赔率涨至买入价 <span class="tg-exit-val">3–5×</span></div>
          <div class="tg-exit-note">→ 卖出一半，剩余持有到结算</div>
        </div>
      </div>
      <div class="tg-exit-row">
        <span class="tg-exit-icon">⏱</span>
        <div>
          <div>买入后最多等 <span class="tg-exit-val">30 分钟</span></div>
          <div class="tg-exit-note">→ P90 的局在此时间内结束</div>
        </div>
      </div>
      <div class="tg-exit-row">
        <span class="tg-exit-icon">🚫</span>
        <div>
          <div style="color:#475569">彩票型<span class="tg-exit-val" style="color:#475569"> 不止损</span></div>
          <div class="tg-exit-note">→ 买入即接受全亏，不加仓</div>
        </div>
      </div>
    </div>

    <!-- 🆕 B型策略 -->
    <div class="tg-col" style="min-width:190px;border-left:2px solid #7c3aed">
      <div class="tg-col-head" style="color:#a78bfa">🆕 B型速查 · 强队临时低估</div>
      <div class="tg-row" style="margin-bottom:4px">
        <span class="tg-lbl">赛前热门</span>
        <span class="tg-chip purple">&gt; 65%</span>
      </div>
      <div style="font-size:13px;color:#94a3b8;margin:6px 0 4px">局内跌至 → 操作：</div>
      <div style="font-size:13px;line-height:2.1">
        <span style="color:#4ade80;font-weight:700">40–60%</span>&nbsp; ⭐ 买入（EV +36~48%）<br>
        <span style="color:#fbbf24">60–70%</span>&nbsp;&nbsp; 🔹 小仓（EV +24%）<br>
        <span style="color:#f87171;font-weight:700">跌破 40%</span> ⛔ 停！换A型逻辑
      </div>
      <div style="font-size:11px;color:#475569;margin-top:6px;line-height:1.6">
        赛前&gt;75%时 40-50%区间 EV可达+67%<br>
        ⚠ 跌破40%=真在被打崩，胜率仅23%
      </div>
    </div>

  </div><!-- /tg-body -->
</div><!-- /trading-guide -->

<div class="header">
  <h1>LoL 小局反转分析 · Game N Winner 市场</h1>
  <p>数据来源：Polymarket CLOB · 2026年4-5月 · LCK / LPL / LEC / LCS · UTC时间</p>
</div>

<div class="explain-box">
  <strong>如何读这张表：</strong>
  每行代表一场小局（Game 1 / Game 2 / Game 3）。所有记录中<strong style="color:#4ade80">绿色队名</strong>为本局获胜方。<br>
  <strong>赛前赔率</strong>：游戏内第一个数据点时获胜方的市场赔率（胜率%）。<br>
  <strong>局内最低点</strong>：获胜方在本局进行中赔率跌到的谷底。<br>
  <strong>最终结果</strong>：市场结算价格（获胜方 → 1.00，即100%）。<br>
  <strong>最低点时间</strong>：最低赔率发生在游戏开始后约第几分钟（从价格历史推算）。<br>
  <div class="note">⚠️ 精度说明：Polymarket 价格历史 10分钟/点，游戏内仅 2–6 个数据点，时间精度约 ±10 分钟。</div>
</div>

<div class="stats-bar">
  <div class="stat"><span class="stat-val" id="s-total">—</span><span class="stat-lbl">总局数</span></div>
  <div class="stat"><span class="stat-val" id="s-below30" style="color:#a78bfa">—</span><span class="stat-lbl">最低点 &lt;30%</span></div>
  <div class="stat"><span class="stat-val" id="s-below20" style="color:#fb923c">—</span><span class="stat-lbl">最低点 &lt;20%</span></div>
  <div class="stat"><span class="stat-val" id="s-below10" style="color:#ef4444">—</span><span class="stat-lbl">最低点 &lt;10%</span></div>
  <div class="stat"><span class="stat-val" id="s-avg-min" style="color:#60a5fa">—</span><span class="stat-lbl">反转局触底游戏分钟</span></div>
</div>

<div class="analysis-panels">

  <!-- Timing Stats Panel -->
  <div class="panel" style="border-color:#1e3a5f">
    <div class="panel-title" style="background:#0a1628;color:#60a5fa">⏱ 触底时机分析（精确游戏时间，基于 LoL API）</div>
    <div class="panel-body">
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:16px">

        <div style="flex:1;min-width:220px">
          <div style="font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px">买入窗口（反转局触底时刻，n=<span id="ts-n">—</span>）</div>
          <div style="display:flex;gap:8px;align-items:flex-end;margin-bottom:6px">
            <div style="text-align:center">
              <div style="font-size:11px;color:#475569;margin-bottom:3px">P25</div>
              <div style="font-size:20px;font-weight:700;color:#94a3b8" id="ts-p25">—</div>
              <div style="font-size:10px;color:#334155">分钟</div>
            </div>
            <div style="color:#334155;padding-bottom:8px">─</div>
            <div style="text-align:center">
              <div style="font-size:11px;color:#60a5fa;margin-bottom:3px">中位数</div>
              <div style="font-size:28px;font-weight:800;color:#60a5fa" id="ts-p50">—</div>
              <div style="font-size:10px;color:#475569">分钟</div>
            </div>
            <div style="color:#334155;padding-bottom:8px">─</div>
            <div style="text-align:center">
              <div style="font-size:11px;color:#475569;margin-bottom:3px">P75</div>
              <div style="font-size:20px;font-weight:700;color:#94a3b8" id="ts-p75">—</div>
              <div style="font-size:10px;color:#334155">分钟</div>
            </div>
            <div style="color:#1e2535;padding-bottom:8px">│</div>
            <div style="text-align:center">
              <div style="font-size:11px;color:#475569;margin-bottom:3px">P90</div>
              <div style="font-size:18px;font-weight:600;color:#64748b" id="ts-p90">—</div>
              <div style="font-size:10px;color:#334155">分钟</div>
            </div>
          </div>
          <div style="font-size:11px;color:#4ade80;margin-top:4px">★ 核心观察窗口（IQR）：第 <span id="ts-iqr">—</span> 分钟</div>
          <div style="font-size:11px;color:#475569;margin-top:2px">游戏平均时长 <span id="ts-dur">—</span> 分钟 · 触底在游戏进行 <span id="ts-prog">—</span>% 时</div>
        </div>

        <div style="flex:1;min-width:180px">
          <div style="font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px">持仓时间（触底后还需等多久）</div>
          <div style="display:flex;gap:12px;flex-wrap:wrap">
            <div style="background:#0f1621;border-radius:6px;padding:10px 14px;flex:1;min-width:80px">
              <div style="font-size:11px;color:#475569">中位数</div>
              <div style="font-size:24px;font-weight:700;color:#fbbf24" id="ts-hold-p50">—</div>
              <div style="font-size:10px;color:#475569">分钟</div>
            </div>
            <div style="background:#0f1621;border-radius:6px;padding:10px 14px;flex:1;min-width:80px">
              <div style="font-size:11px;color:#475569">P75</div>
              <div style="font-size:24px;font-weight:700;color:#fb923c" id="ts-hold-p75">—</div>
              <div style="font-size:10px;color:#475569">分钟</div>
            </div>
            <div style="background:#131a2e;border:1px solid #ef4444;border-radius:6px;padding:10px 14px;flex:1;min-width:80px">
              <div style="font-size:11px;color:#ef4444">P90 上限</div>
              <div style="font-size:24px;font-weight:700;color:#ef4444" id="ts-hold-p90">—</div>
              <div style="font-size:10px;color:#475569">分钟</div>
            </div>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:8px">90% 的案例在买入后 P90 分钟内结束</div>
        </div>

        <div style="flex:1;min-width:200px">
          <div style="font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">触底时刻分布</div>
          <div id="timing-precise-chart"></div>
        </div>

      </div>
    </div>
  </div>

  <!-- Key Finding Box -->
  <div class="panel" style="border-color:#1a3a1a">
    <div class="panel-title" style="background:#0d1f0d;color:#4ade80">🔑 EV 核心发现</div>
    <div class="panel-body" style="display:flex;gap:20px;flex-wrap:wrap">
      <div style="flex:2;min-width:260px">
        <div style="font-size:13px;color:#94a3b8;line-height:1.9">
          <strong style="color:#f1f5f9">核心方法：</strong>区分「触底时刻」——早期触底（10–20分）多为一边倒的开局劣势，晚期触底（20–30分）才是真正的逆风局<br>
          <strong style="color:#4ade80">关键发现：</strong><strong style="color:#fbbf24">20–30分钟触底窗口</strong>是唯一正 EV 区间——买入 &lt;10% 时 EV = +0.25，&lt;20% 时近似盈亏平衡<br>
          <strong style="color:#ef4444">重要限制：</strong>纯价格信号样本量偏小（n=3–24），Wilson 置信区间下界仍为负。
          下一步需引入 <strong style="color:#60a5fa">LoL 战局数据（金币差 / 大龙 / 男爵）</strong> 进一步提升胜率
        </div>
      </div>
      <div style="flex:1;min-width:180px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start">
        <div style="background:#0a1f0a;border:1px solid #166534;border-radius:8px;padding:12px 16px;flex:1;min-width:130px">
          <div style="font-size:11px;color:#4ade80;font-weight:700">精确版 EV @10%<br>≥15分钟入场</div>
          <div style="font-size:26px;font-weight:800;color:#4ade80;margin:4px 0" id="key-ev-10">—</div>
          <div style="font-size:11px;color:#64748b" id="key-ev-10-n">—</div>
        </div>
        <div style="background:#0a1f0a;border:1px solid #166534;border-radius:8px;padding:12px 16px;flex:1;min-width:130px">
          <div style="font-size:11px;color:#4ade80;font-weight:700">精确版 EV @15%<br>≥15分钟入场</div>
          <div style="font-size:26px;font-weight:800;color:#4ade80;margin:4px 0" id="key-ev-15">—</div>
          <div style="font-size:11px;color:#64748b" id="key-ev-15-n">—</div>
        </div>
      </div>
    </div>
  </div>

  <!-- EV Panel: Two tables side by side -->
  <div class="panel-row">

    <div class="panel panel-half">
      <div class="panel-title" style="color:#f87171">❌ 原始 EV（未过滤时机）
        <span class="panel-note">— 包含末期碾压的无效信号</span>
      </div>
      <div class="panel-body">
        <table class="ev-table">
          <thead>
            <tr>
              <th>买入阈值</th><th>成功</th><th>失败</th><th>实际胜率</th><th>EV</th>
            </tr>
          </thead>
          <tbody id="ev-tbody-raw"></tbody>
        </table>
        <div class="ev-note">不区分「末期碾压」与「真正反转机会」，EV 均为负。</div>
      </div>
    </div>

    <div class="panel panel-half">
      <div class="panel-title" style="color:#4ade80">✅ 时机过滤后 EV（触底时刻 ≥20分钟）
        <span class="panel-note">— 排除早期雪球噪音</span>
      </div>
      <div class="panel-body">
        <table class="ev-table">
          <thead>
            <tr>
              <th>买入阈值</th><th>成功</th><th>失败</th><th>实际胜率</th><th>盈亏线</th><th>EV</th>
            </tr>
          </thead>
          <tbody id="ev-tbody-timed"></tbody>
        </table>
        <div class="ev-note">
          <strong>EV = 实际胜率 ÷ 阈值 − 1</strong>（假设精确在 T% 时买入）。正值代表盈利。<br>
          ⚠️ 样本量较小（各阈值 12–145 次），置信区间较宽，需持续积累数据验证。
        </div>
      </div>
    </div>

  </div>

  <!-- League + Timing side by side -->
  <div class="panel-row">

    <div class="panel panel-half">
      <div class="panel-title">联赛反转率对比
        <span class="panel-note"> — <span style="color:#f87171">⚠️ LPL 存在假赛疑虑，执行时请自行判断</span></span>
      </div>
      <div class="panel-body">
        <table class="ev-table">
          <thead>
            <tr>
              <th>联赛</th>
              <th title="本赛区统计到的全部 Game N 小局数量">总局数</th>
              <th title="弱势方（赔率曾跌破30%）最终赢下比赛的局数 ÷ 总局数" style="color:#a78bfa">逆转赢✓<br><small style="font-weight:400;font-size:10px">赔率曾&lt;30%</small></th>
              <th title="弱势方（赔率曾跌破20%）最终赢下比赛的局数 ÷ 总局数" style="color:#fb923c">逆转赢✓<br><small style="font-weight:400;font-size:10px">赔率曾&lt;20%</small></th>
              <th>均交易量</th>
            </tr>
          </thead>
          <tbody id="lg-tbody"></tbody>
        </table>
        <div class="ev-note" style="margin-top:10px">
          📌 <strong style="color:#e2e8f0">怎么读这张表：</strong>「逆转赢✓」= 某队赔率在比赛中跌到该阈值以下，但<em>最终赢下了比赛</em>的场数。例：LCK 82局里有 20 局，弱势方（赔率曾低于30%）最终翻盘赢下。<br style="margin-bottom:4px">
          🇰🇷 <strong style="color:#4ade80">LCK</strong>：翻盘率最高，数据最可信。&nbsp;
          ⚠️ <strong style="color:#f87171">LPL</strong>：存在选手操作异常疑虑，执行时请自行判断。
        </div>
      </div>
    </div>

    <div class="panel panel-half">
      <div class="panel-title">触底时间分布 <span class="panel-note">（距游戏结束多少分钟，反转局 n=56）</span></div>
      <div class="panel-body" id="timing-chart"></div>
    </div>

  </div>

  <!-- Timing Window × EV Table -->
  <div class="panel" style="border-color:#1a3a1a">
    <div class="panel-title" style="background:#0d1f0d;color:#4ade80">
      🎯 触底时间窗口 × EV 分析
      <span class="panel-note"> — 核心发现：<strong style="color:#fbbf24">20–30分钟触底窗口</strong>是唯一正EV区间</span>
    </div>
    <div class="panel-body">
      <div style="font-size:12px;color:#64748b;margin-bottom:10px;line-height:1.8">
        同样是赔率跌到 10%，<strong style="color:#e2e8f0">触底时刻不同，结果天壤之别</strong>。
        10–20分钟触底 → 多为早期雪球，对方很难翻；20–30分钟触底 → 大龙/男爵时间节点，一波团战就能逆转。
      </div>
      <table class="ev-table">
        <thead>
          <tr>
            <th>买入阈值</th>
            <th>触底时刻</th>
            <th>翻盘</th>
            <th>失败</th>
            <th>总计</th>
            <th>胜率</th>
            <th>EV</th>
            <th>Wilson下界</th>
          </tr>
        </thead>
        <tbody id="tw-ev-tbody"></tbody>
      </table>
      <div class="ev-note" style="margin-top:10px">
        <strong>⭐ 20–30分钟窗口</strong>：买入阈值 &lt;10% 时 EV = <strong style="color:#4ade80">+0.25</strong>（12% 胜率，需 10x 回报）。
        样本量偏小，但方向一致：<strong style="color:#fbbf24">越晚触底、越有翻盘价值</strong>。
        Wilson 下界为悲观估计（90% 置信），正值才算真正稳健。
      </div>
    </div>
  </div>

  <!-- Battle State Filter Panel -->
  <div class="panel" style="border-color:#1e3a2e">
    <div class="panel-title" style="background:#0d1f17;color:#34d399">
      ⚔️ 战局过滤 EV（20–30分窗口 · 触底时刻 Livestats 快照）
      <span class="panel-note"> — 核心：<strong style="color:#fbbf24">金币差 &lt; 3000</strong> 使胜率 23% → 35%</span>
    </div>
    <div class="panel-body">
      <div style="font-size:12px;color:#64748b;margin-bottom:12px;line-height:1.9">
        赔率触底时，同步查看 LoL Livestats 战局快照（金币差 / 对方龙数 / 存活核心），可以显著提高信号质量。<br>
        <strong style="color:#fbbf24">实操逻辑：</strong>落后不超过 3000 金 = 还在局里；对方龙 ≤ 2 = 还没堆成龙魂战力。两条加在一起，废局变好局。
      </div>
      <div id="bs-ev-container"></div>
      <div class="ev-note" style="margin-top:12px">
        <strong>EV = 胜率 ÷ 平均买入赔率 − 1</strong>（20-30min窗口内平均赔率≈10%，故基础EV≈+1.3）。<br>
        <strong>Wilson下界</strong>：悲观保守估计，正值代表即使考虑抽样误差仍具统计稳健性。<br>
        ⚠️ 战局过滤组样本 n=24–37，方向明确但需持续积累数据。数据来源：Script 12，game_battle_state.json（140 案例）
      </div>
    </div>
  </div>

  <!-- B-Type Strategy Panel -->
  <div class="panel" style="border-color:#3a1a5f">
    <div class="panel-title" style="background:#14102a;color:#a78bfa">
      🆕 B型策略分析 · 强队赛前热门 → 局内临时低估
      <span class="panel-note"> — 核心警告：<strong style="color:#f87171">跌破40% EV=-28%，不可买入</strong></span>
    </div>
    <div class="panel-body">
      <div style="font-size:12px;color:#64748b;margin-bottom:14px;line-height:2.0">
        <strong style="color:#e2e8f0">B型策略</strong>：一支赛前大热门（开盘赔率 &gt;65%）因局内早期事件被市场临时压低——此时市场可能过度恐慌，是买入机会。<br>
        <strong style="color:#fbbf24">最优 EV 区间（⭐）：跌至 50–60%</strong>，EV +35%，胜率 75%，样本最充分（55场）。<br>
        <strong style="color:#60a5fa">高胜率稳健区间（🛡）：跌至 70–80%</strong>，胜率 88%，但 EV 只有 +17%——更保守的选择。<br>
        <strong style="color:#f87171">危险区间（⛔）：跌破 40%</strong>，胜率骤降至 23%（EV=-28%）——市场没有过度反应，是真实崩盘，应切换为A型逻辑或跳过。
      </div>

      <div style="display:flex;gap:20px;flex-wrap:wrap">

        <!-- Table 1: pre-game >65% -->
        <div style="flex:1;min-width:280px">
          <div style="font-size:11px;color:#a78bfa;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">赛前热门 &gt;65% → 局内跌至（865场样本）</div>
          <table class="ev-table">
            <thead>
              <tr><th>局内最低跌至</th><th>场数</th><th>胜率</th><th>EV</th><th>操作建议</th></tr>
            </thead>
            <tbody id="btype-tbody-65"></tbody>
          </table>
        </div>

        <!-- Table 2: pre-game >75% -->
        <div style="flex:1;min-width:280px">
          <div style="font-size:11px;color:#a78bfa;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">赛前热门 &gt;75% → 局内跌至（更严格筛选）</div>
          <table class="ev-table">
            <thead>
              <tr><th>局内最低跌至</th><th>场数</th><th>胜率</th><th>EV</th><th>操作建议</th></tr>
            </thead>
            <tbody id="btype-tbody-75"></tbody>
          </table>
        </div>

      </div>

      <div class="ev-note" style="margin-top:14px">
        <strong style="color:#a78bfa">实盘验证（2026-05-30）：</strong><br>
        · KT vs DNS G1：KT 86% → 跌至 59%（⭐ EV+35%区间）→ $138 买入，KT 赢，+19%<br>
        · KT vs DNS G2：KT 87% → 跌至 72%（🛡 EV+17%区间）→ $17 买入，KT 赢，+37%<br>
        · T1 vs BFX G1：T1 → 跌至 70%（🛡 EV+17%区间）→ $70 买入；继续跌至 40%（⚡ EV+48%·高风险）→ $56 加仓；T1 险胜高地团战，$126 → $240，+$114（+90%）。⚠️ 40¢ 加仓已滑入高风险区，有运气成分。<br>
        <strong>样本基础</strong>：865场（series级）；各区间 13–82 场，方向明确，样本仍在积累中。
      </div>
    </div>
  </div>

  <!-- Lottery Games -->
  <div class="panel" style="border-color:#3a1a1a">
    <div class="panel-title" style="background:#1f0d0d;color:#ef4444">
      🎰 彩票局详情（触底 &lt;10%，触底时刻 ≥10分钟）
      <span class="panel-note"> — 全赛区共 5 局，全部翻盘成功</span>
    </div>
    <div class="panel-body">
      <div style="font-size:12px;color:#64748b;margin-bottom:10px;line-height:1.8">
        这 5 局是历史数据中最极端的翻盘案例：赔率跌到 5–9¢ 时，市场几乎认为它们必输，但最终全部赢下。
        注意持仓时间：触底后平均仅需等待 <strong style="color:#fbbf24">10–30 分钟</strong>即结束。
      </div>
      <table class="ev-table">
        <thead>
          <tr>
            <th>联赛</th>
            <th>对阵（绿色=最终赢家）</th>
            <th style="text-align:center">触底赔率</th>
            <th style="text-align:center">理论回报</th>
            <th style="text-align:center">触底时刻</th>
            <th style="text-align:center">局总时长</th>
            <th style="text-align:center">触底后等待</th>
            <th>日期</th>
          </tr>
        </thead>
        <tbody id="lottery-tbody"></tbody>
      </table>
      <div class="ev-note" style="margin-top:10px">
        ⚠️ 注意：这 5 局是「成功翻盘」的样本，同期还有 ~40 局在类似条件下<strong style="color:#f87171">未能翻盘（全额亏损）</strong>。
        彩票型策略需要资金管理：单注金额控制，预期多数亏损但靠少数大赢覆盖。
      </div>
    </div>
  </div>

</div>

<div class="controls">
  <button class="filter-btn active" data-filter="all">全部</button>
  <button class="filter-btn" data-filter="reversal30">最低点&lt;30%</button>
  <button class="filter-btn" data-filter="reversal20">最低点&lt;20%</button>
  <button class="filter-btn" data-filter="reversal10">最低点&lt;10%</button>
  <span class="sep">|</span>
  <button class="filter-btn" data-filter="LCK">LCK</button>
  <button class="filter-btn" data-filter="LPL">LPL</button>
  <button class="filter-btn" data-filter="LEC">LEC</button>
  <button class="filter-btn" data-filter="LCS">LCS</button>
  <span class="sep">|</span>
  <label>排序：<select class="inline-sel" id="sort-sel">
    <option value="date-desc">日期（最新）</option>
    <option value="min_p-asc">最低点（最低）</option>
    <option value="min_time-asc">触底时间（最早）</option>
    <option value="vol-desc">交易量（最高）</option>
  </select></label>
  <span class="sep">|</span>
  <input class="search-box" id="search-box" placeholder="搜索队名…" type="text">
</div>

<div class="page-info" id="page-info"></div>

<div class="table-wrap">
<table id="main-table">
<thead>
<tr>
  <th>日期 (UTC)</th>
  <th>对阵 · 联赛 · 局次</th>
  <th title="完整赔率走势：赛前 → 局内最低点 → 最终结算">赛前赔率 → 最低点 → 最终结果</th>
  <th title="最低赔率发生在游戏开始后约第几分钟（±10分精度）">最低点时间<br><small style='font-size:10px;color:#334155'>(游戏开始后，±10分)</small></th>
  <th>局时长</th>
  <th>交易量</th>
</tr>
</thead>
<tbody id="table-body">
</tbody>
</table>
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

function fmtVol(v) {
  if (v >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
  if (v >= 1e3) return '$' + Math.round(v/1e3) + 'K';
  return '$' + Math.round(v);
}

function priceColor(p) {
  if (p < 0.10) return '#ef4444';
  if (p < 0.20) return '#fb923c';
  if (p < 0.30) return '#eab308';
  return '#94a3b8';
}

function barColor(p) {
  if (p < 0.10) return '#ef4444';
  if (p < 0.20) return '#fb923c';
  if (p < 0.30) return '#eab308';
  if (p < 0.50) return '#64748b';
  return '#22c55e';
}

function signalBadge(p) {
  if (p < 0.10) return '<span class="signal-badge sig-extreme">极端 &lt;10%</span>';
  if (p < 0.20) return '<span class="signal-badge sig-deep">深度 &lt;20%</span>';
  if (p < 0.30) return '<span class="signal-badge sig-mid">触底 &lt;30%</span>';
  return '<span class="signal-badge sig-none">正常</span>';
}

function leagueBadge(lg) {
  return `<span class="league-badge lg-${lg}">${lg}</span>`;
}

function gameLabel(q) {
  const m = q.match(/Game (\\d+) Winner/i);
  return m ? `<span class="game-badge">Game ${m[1]}</span>` : '';
}

function miniBar(p) {
  const w = Math.max(2, Math.round(p * 44));
  const c = barColor(p);
  return `<div class="mini-bar"><div class="mini-fill" style="width:${w}px;background:${c}"></div></div>`;
}

function priceBox(p, colorClass, label) {
  const pct = Math.round(p * 100);
  return `<div class="j-box">
    <div class="j-price ${colorClass}">${pct}%</div>
    ${miniBar(p)}
    <div class="journey-label">${label}</div>
  </div>`;
}

function renderRow(r) {
  const openColor = r.game_open_p >= 0.50 ? 'p-open' : 'p-30';
  const minColor  = r.win_min_p < 0.10 ? 'p-10' : r.win_min_p < 0.20 ? 'p-20' : r.win_min_p < 0.30 ? 'p-30' : 'p-high';

  // Timing: game_min_of_bottom from game start
  const minTime = r.game_min_of_bottom != null ? r.game_min_of_bottom : null;
  const endTime = r.game_duration_mins != null ? r.game_duration_mins : null;
  let timingMain = minTime != null ? `~${minTime}分钟` : '—';
  let timingRange = '';
  if (minTime != null) {
    const lo = Math.max(0, minTime - 10);
    const hi = minTime + 10;
    timingRange = `范围：第 ${lo}–${hi} 分钟`;
  }
  let timingDur = endTime != null ? `局时长 ≈ ${endTime} 分` : '';

  const sortMinTime = minTime != null ? minTime : 999;

  return `<tr
    data-league="${r.league}"
    data-min="${r.win_min_p}"
    data-date="${r.game_date}"
    data-vol="${r.volume}"
    data-min-time="${sortMinTime}"
    data-teams="${(r.winner + ' ' + r.loser).toLowerCase()}">

    <td class="td-date">
      <div class="d-date">${r.game_date}</div>
      <div class="d-time">${r.game_time} UTC</div>
    </td>

    <td class="td-match">
      <div>
        <span class="winner-name">${r.winner}</span>
        <span class="vs-sep">vs</span>
        <span class="loser-name">${r.loser}</span>
      </div>
      <div class="match-tags">
        ${leagueBadge(r.league)}
        ${gameLabel(r.game_question)}
        ${signalBadge(r.win_min_p)}
      </div>
    </td>

    <td class="td-journey">
      <div class="journey-row">
        ${priceBox(r.game_open_p, openColor, '赛前')}
        <div class="j-arrow">→</div>
        ${priceBox(r.win_min_p, minColor, '最低点')}
        <div class="j-arrow">→</div>
        ${priceBox(1.0, 'p-final', '最终结算')}
      </div>
    </td>

    <td class="td-timing">
      <div class="t-main">${timingMain}</div>
      <div class="t-range">${timingRange}</div>
      <div class="t-dur">${timingDur}</div>
    </td>

    <td class="td-timing" style="color:#475569">
      ${endTime != null ? `<div class="t-main" style="color:#475569">${endTime} 分</div>` : '—'}
    </td>

    <td class="td-vol">${fmtVol(r.volume)}</td>
  </tr>`;
}

// State
let currentFilter = 'all';
let currentSort   = 'date-desc';
let searchQuery   = '';

function applyAll() {
  const rows = document.querySelectorAll('#table-body tr');
  let visible = 0;
  rows.forEach(row => {
    const league = row.dataset.league;
    const minP   = parseFloat(row.dataset.min);
    const teams  = row.dataset.teams;
    let show = true;
    if (currentFilter === 'reversal30' && minP >= 0.30) show = false;
    if (currentFilter === 'reversal20' && minP >= 0.20) show = false;
    if (currentFilter === 'reversal10' && minP >= 0.10) show = false;
    if (['LCK','LPL','LEC','LCS'].includes(currentFilter) && league !== currentFilter) show = false;
    if (searchQuery && !teams.includes(searchQuery.toLowerCase())) show = false;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  document.getElementById('page-info').textContent = `显示 ${visible} / ${rows.length} 场`;
}

function applySortDOM() {
  const tbody = document.getElementById('table-body');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    if (currentSort === 'date-desc')     return b.dataset.date.localeCompare(a.dataset.date);
    if (currentSort === 'min_p-asc')     return parseFloat(a.dataset.min) - parseFloat(b.dataset.min);
    if (currentSort === 'min_time-asc')  return parseFloat(a.dataset.minTime) - parseFloat(b.dataset.minTime);
    if (currentSort === 'vol-desc')      return parseFloat(b.dataset.vol) - parseFloat(a.dataset.vol);
    return 0;
  });
  rows.forEach(r => tbody.appendChild(r));
}

// Init
const tbody = document.getElementById('table-body');
tbody.innerHTML = DATA.map(renderRow).join('');

// Stats
const total = DATA.length;
const b30 = DATA.filter(r => r.win_min_p < 0.30).length;
const b20 = DATA.filter(r => r.win_min_p < 0.20).length;
const b10 = DATA.filter(r => r.win_min_p < 0.10).length;
const rev = DATA.filter(r => r.win_min_p < 0.30 && r.game_min_of_bottom != null);
const avgMin = rev.length > 0
  ? Math.round(rev.reduce((s, r) => s + r.game_min_of_bottom, 0) / rev.length)
  : 0;
document.getElementById('s-total').textContent = total;
document.getElementById('s-below30').textContent = `${b30} (${Math.round(b30/total*100)}%)`;
document.getElementById('s-below20').textContent = `${b20} (${Math.round(b20/total*100)}%)`;
document.getElementById('s-below10').textContent = `${b10} (${Math.round(b10/total*100)}%)`;
document.getElementById('s-avg-min').textContent = `~第 ${avgMin} 分钟`;

// Filter buttons
document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    applyAll();
  });
});
document.getElementById('sort-sel').addEventListener('change', e => {
  currentSort = e.target.value;
  applySortDOM();
  applyAll();
});
document.getElementById('search-box').addEventListener('input', e => {
  searchQuery = e.target.value;
  applyAll();
});

// ── Data ──────────────────────────────────────────────
const EV_RAW      = __EV_RAW_PLACEHOLDER__;
const EV_TIMED    = __EV_TIMED_PLACEHOLDER__;
const LG_STATS    = __LG_STATS_PLACEHOLDER__;
const TIMING_DIST = __TIMING_PLACEHOLDER__;
const TS          = __TIMING_STATS_PLACEHOLDER__;
const TW_EV       = __TW_EV_PLACEHOLDER__;
const LOTTERY     = __LOTTERY_PLACEHOLDER__;
const BS_EV       = __BS_EV_PLACEHOLDER__;
const B_TYPE      = __B_TYPE_PLACEHOLDER__;

// ── Timing Stats Panel ────────────────────────────────
if (TS && TS.n_reversal) {
  document.getElementById('ts-n').textContent     = TS.n_reversal;
  document.getElementById('ts-p25').textContent   = TS.entry_p25;
  document.getElementById('ts-p50').textContent   = TS.entry_p50;
  document.getElementById('ts-p75').textContent   = TS.entry_p75;
  document.getElementById('ts-p90').textContent   = TS.entry_p90;
  document.getElementById('ts-iqr').textContent   = `${TS.entry_p25}–${TS.entry_p75}`;
  document.getElementById('ts-dur').textContent   = TS.avg_duration;
  document.getElementById('ts-prog').textContent  = `${TS.prog_p25}–${TS.prog_p75}`;
  document.getElementById('ts-hold-p50').textContent = TS.hold_p50;
  document.getElementById('ts-hold-p75').textContent = TS.hold_p75;
  document.getElementById('ts-hold-p90').textContent = TS.hold_p90;

  // Precise timing mini-chart
  const maxC = Math.max(...TS.dist.map(d => d.count));
  document.getElementById('timing-precise-chart').innerHTML = TS.dist.map(d => {
    const pct = maxC > 0 ? Math.round(d.count / maxC * 100) : 0;
    const col = d.lo < 10 ? '#64748b' : d.lo < 25 ? '#3b82f6' : '#475569';
    return `<div class="bar-row" style="margin:3px 0">
      <div class="bar-label" style="font-size:11px;width:70px">${d.label}</div>
      <div class="bar-track" style="height:14px">
        <div class="bar-fill" style="width:${pct}%;background:${col};height:100%">
          ${d.count > 0 ? `<span style="font-size:10px;font-weight:700;color:#fff;padding-left:4px">${d.count}</span>` : ''}
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── EV Tables ─────────────────────────────────────────
function renderEVTable(tableId, rows, showBreakeven) {
  const tbody = document.getElementById(tableId);
  if (!tbody) return;
  tbody.innerHTML = rows.map(row => {
    const wrClass = row.win_rate_pct >= row.breakeven_wr ? 'wr-ok' : row.win_rate_pct >= row.breakeven_wr * 0.8 ? 'wr-mid' : 'wr-low';
    const evClass = row.ev > 0 ? 'ev-positive' : row.ev > -0.10 ? 'ev-near' : 'ev-negative';
    const beCol = showBreakeven ? `<td style="color:#475569">${row.breakeven_wr}%</td>` : '';
    const ciCol = showBreakeven && row.ev_ci_lo !== undefined
      ? `<td style="color:#475569;font-size:11px">${row.ev_ci_lo > 0 ? '+' : ''}${row.ev_ci_lo.toFixed(2)}</td>` : '';
    return `<tr>
      <td><strong style="color:#e2e8f0">${row.threshold_pct}%</strong></td>
      <td style="color:#4ade80">${row.success}</td>
      <td style="color:#f87171">${row.failure}</td>
      <td><span class="wr-badge ${wrClass}">${row.win_rate_pct}%</span></td>
      ${beCol}${ciCol}
      <td class="${evClass}">${row.ev > 0 ? '+' : ''}${row.ev.toFixed(2)}</td>
    </tr>`;
  }).join('');
}
renderEVTable('ev-tbody-raw',   EV_RAW,   false);
renderEVTable('ev-tbody-timed', EV_TIMED, true);

// Key EV cards
const ev10 = EV_TIMED.find(r => r.threshold_pct === 10);
const ev15 = EV_TIMED.find(r => r.threshold_pct === 15);
if (ev10) {
  document.getElementById('key-ev-10').textContent = (ev10.ev > 0 ? '+' : '') + ev10.ev.toFixed(2);
  document.getElementById('key-ev-10-n').textContent = `n=${ev10.total} 次`;
}
if (ev15) {
  document.getElementById('key-ev-15').textContent = (ev15.ev > 0 ? '+' : '') + ev15.ev.toFixed(2);
  document.getElementById('key-ev-15-n').textContent = `n=${ev15.total} 次`;
}

(function renderLeague() {
  const tbody = document.getElementById('lg-tbody');
  tbody.innerHTML = LG_STATS.map(row => {
    const lgClass = `lg-${row.league}`;
    return `<tr>
      <td><span class="league-badge ${lgClass}">${row.league}</span></td>
      <td style="color:#94a3b8">${row.total} 局</td>
      <td>
        <span style="color:#a78bfa;font-weight:700;font-size:15px">${row.rev30}</span>
        <span style="color:#94a3b8;font-size:12px"> 局赢了</span>
        <span style="color:#64748b;font-size:12px"> / ${row.total} =</span>
        <span style="color:#a78bfa;font-weight:700"> ${row.rev30_pct}%</span>
      </td>
      <td>
        <span style="color:#fb923c;font-weight:700;font-size:15px">${row.rev20}</span>
        <span style="color:#94a3b8;font-size:12px"> 局赢了</span>
        <span style="color:#64748b;font-size:12px"> / ${row.total} =</span>
        <span style="color:#fb923c;font-weight:700"> ${row.rev20_pct}%</span>
      </td>
      <td style="color:#64748b">${(row.avg_vol/1000).toFixed(0)}K</td>
    </tr>`;
  }).join('');
})();

(function renderTiming() {
  const container = document.getElementById('timing-chart');
  const maxCount = Math.max(...TIMING_DIST.map(r => r.count));
  container.innerHTML = TIMING_DIST.map(row => {
    const pct = maxCount > 0 ? Math.round(row.count / maxCount * 100) : 0;
    const barColor = row.lo <= 20 ? '#22c55e' : row.lo <= 40 ? '#3b82f6' : '#6366f1';
    return `<div class="bar-row">
      <div class="bar-label">${row.label}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${pct}%;background:${barColor}">
          ${row.count > 0 ? `<span class="bar-count">${row.count}</span>` : ''}
        </div>
        ${row.count === 0 ? '<span class="bar-count-out" style="position:absolute;left:6px;top:2px">0</span>' : ''}
      </div>
    </div>`;
  }).join('');
})();

// ── Timing Window EV Table ────────────────────────────
(function renderTWEV() {
  const el = document.getElementById('tw-ev-tbody');
  if (!el || !TW_EV.length) return;
  let lastThresh = null;
  el.innerHTML = TW_EV.map(row => {
    const isNew = row.threshold_pct !== lastThresh;
    lastThresh = row.threshold_pct;
    const evClass = row.ev > 0.1 ? 'ev-positive' : row.ev > -0.1 ? 'ev-near' : 'ev-negative';
    const isSweet = row.window === '20–30分' && row.ev > 0;
    const rowStyle = isSweet ? 'background:#0a1f0a' : '';
    const winLabel = row.window === '20–30分'
      ? `<strong style="color:#4ade80">${row.window}</strong>` : `<span style="color:#94a3b8">${row.window}</span>`;
    return `<tr style="${rowStyle}">
      ${isNew ? `<td rowspan="3" style="color:#e2e8f0;font-weight:700;font-size:13px;text-align:center;border-right:1px solid #1e2535">${row.threshold_pct}%</td>` : ''}
      <td>${winLabel}${isSweet ? ' ⭐' : ''}</td>
      <td style="color:#4ade80">${row.wins}</td>
      <td style="color:#f87171">${row.fails}</td>
      <td>${row.total}</td>
      <td><span style="font-weight:700;color:${row.win_rate_pct >= row.threshold_pct ? '#4ade80' : '#94a3b8'}">${row.win_rate_pct}%</span></td>
      <td class="${evClass}">${row.ev > 0 ? '+' : ''}${row.ev.toFixed(2)}</td>
      <td style="color:#475569;font-size:11px">${row.ev_ci_lo > 0 ? '+' : ''}${row.ev_ci_lo.toFixed(2)}</td>
    </tr>`;
  }).join('');
})();

// ── Lottery Games Table ───────────────────────────────
(function renderLottery() {
  const el = document.getElementById('lottery-tbody');
  if (!el) return;
  const lgClass = {'LCK':'lg-LCK','LPL':'lg-LPL','LEC':'lg-LEC','LCS':'lg-LCS'};
  const lgWarn  = {'LPL': ' <span style="font-size:10px;color:#f87171">⚠️假赛风险</span>'};
  el.innerHTML = LOTTERY.map(r => {
    const warn = lgWarn[r.league] || '';
    const roi  = r.min_p_pct > 0 ? Math.round(100 / r.min_p_pct) : '?';
    return `<tr>
      <td><span class="league-badge ${lgClass[r.league]}">${r.league}</span>${warn}</td>
      <td><strong style="color:#4ade80">${r.winner}</strong> <span style="color:#475569">vs</span> <span style="color:#64748b">${r.loser}</span></td>
      <td style="text-align:center"><strong style="color:#ef4444;font-size:15px">${r.min_p_pct}%</strong></td>
      <td style="text-align:center;color:#fbbf24;font-weight:700">${roi}x</td>
      <td style="text-align:center;color:#60a5fa">${r.bot_min} 分</td>
      <td style="text-align:center;color:#475569">${r.dur} 分</td>
      <td style="text-align:center;color:#94a3b8">${r.hold} 分</td>
      <td style="color:#475569">${r.date}</td>
    </tr>`;
  }).join('');
})();

// ── Battle State EV Panel ─────────────────────────────
(function renderBSEV() {
  const container = document.getElementById('bs-ev-container');
  if (!container || !BS_EV || !BS_EV.length) return;
  container.innerHTML = BS_EV.map(tier => {
    const maxEV = Math.max(...tier.rows.map(r => r.ev));
    return `<div style="margin-bottom:18px">
      <div style="font-size:11px;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;padding:4px 8px;background:#0f1621;border-radius:4px;display:inline-block">【${tier.tier}】</div>
      <table class="ev-table">
        <thead>
          <tr>
            <th>过滤条件</th><th style="text-align:center">n</th><th style="text-align:center">翻盘</th>
            <th style="text-align:center">胜率</th><th style="text-align:center">EV</th><th style="text-align:center">Wilson下界</th>
          </tr>
        </thead>
        <tbody>
          ${tier.rows.map((r, i) => {
            const isBase = i === 0;
            const isBest = r.ev === maxEV && !isBase;
            const evClass = r.ev > 2.0 ? 'ev-positive' : r.ev > 1.0 ? 'ev-near' : 'ev-negative';
            const rowStyle = isBest ? 'background:#0a1f0a' : isBase ? 'background:#0f1621' : '';
            const wrColor = r.win_rate_pct >= 33 ? '#4ade80' : r.win_rate_pct >= 27 ? '#fbbf24' : '#94a3b8';
            const wloColor = r.wilson_lo > 1.0 ? '#4ade80' : r.wilson_lo > 0 ? '#fbbf24' : '#f87171';
            return `<tr style="${rowStyle}">
              <td style="color:${isBase ? '#64748b' : '#e2e8f0'}">${r.label}${isBest ? ' ⭐' : ''}</td>
              <td style="color:#475569;text-align:center">${r.n}</td>
              <td style="color:#4ade80;text-align:center">${r.wins}</td>
              <td style="text-align:center"><span style="font-weight:700;color:${wrColor}">${r.win_rate_pct}%</span></td>
              <td style="text-align:center" class="${evClass}">${r.ev > 0 ? '+' : ''}${r.ev.toFixed(2)}</td>
              <td style="text-align:center;font-size:11px;color:${wloColor}">${r.wilson_lo > 0 ? '+' : ''}${r.wilson_lo.toFixed(2)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>`;
  }).join('');
})();

// ── Bankroll calculator ───────────────────────────────
function updateSizing() {
  const b = parseFloat(document.getElementById('bankroll-input').value) || 500;
  const fmt = (pct) => {
    const v = b * pct;
    return '$' + (v < 10 ? v.toFixed(1) : Math.round(v));
  };
  document.getElementById('sz-lottery').textContent = fmt(0.0075); // 0.75%
  document.getElementById('sz-deep').textContent    = fmt(0.015);  // 1.5%
  document.getElementById('sz-stable').textContent  = fmt(0.03);   // 3%
}
document.getElementById('bankroll-input').addEventListener('input', updateSizing);
updateSizing();

// ── Trading Guide toggle ─────────────────────────────
function toggleGuide() {
  const body = document.getElementById('tg-body');
  const btn  = document.getElementById('tg-btn');
  if (body.style.display === 'none') {
    body.style.display = '';
    btn.textContent = '收起 ▲';
  } else {
    body.style.display = 'none';
    btn.textContent = '展开 ▼';
  }
}

// ── B-Type Strategy Tables ────────────────────────────
(function renderBType() {
  function renderBTypeTable(tbodyId, rows) {
    const el = document.getElementById(tbodyId);
    if (!el || !rows) return;
    el.innerHTML = rows.map(r => {
      const isWarn = r.verdict === 'warn';
      const isBest = r.verdict === 'best_ev';
      const isBestWr = r.verdict === 'best_wr';
      const isRisky = r.verdict === 'risky';
      const rowCls = isWarn ? 'b-warn-row' : isBest ? 'b-best-row' : isBestWr ? 'b-wr-row' : '';
      const evClass = r.ev > 30 ? 'ev-positive' : r.ev > 0 ? 'ev-near' : 'ev-negative';
      const evSign  = r.ev >= 0 ? '+' : '';
      const isRisky = r.verdict === 'risky';
      const isBestWr = r.verdict === 'best_wr';
      const verdictHtml = isWarn
        ? '<span class="b-verdict-warn">⛔ 勿买</span>'
        : isBest
          ? '<span class="b-verdict-best">⭐ 最优EV</span>'
          : isBestWr
            ? '<span class="b-verdict-wr">🛡 稳健</span>'
            : isRisky
              ? '<span class="b-verdict-risky">⚡ 高EV·有风险</span>'
              : '<span class="b-verdict-ok">🔹 可以</span>';
      return `<tr class="${rowCls}">
        <td style="color:${isWarn ? '#f87171' : isBest ? '#4ade80' : '#e2e8f0'};font-weight:${isBest||isWarn?700:400}">${r.bucket}</td>
        <td style="color:#64748b">${r.total}</td>
        <td><span class="wr-badge ${r.win_rate >= 75 ? 'wr-ok' : r.win_rate >= 60 ? 'wr-mid' : 'wr-low'}">${r.win_rate}%</span></td>
        <td class="${evClass}">${evSign}${r.ev}%</td>
        <td>${verdictHtml}</td>
      </tr>`;
    }).join('');
  }
  if (B_TYPE) {
    renderBTypeTable('btype-tbody-65', B_TYPE.thresh65);
    renderBTypeTable('btype-tbody-75', B_TYPE.thresh75);
  }
})();

applySortDOM();
applyAll();
</script>
</body>
</html>"""


def _percentile(lst, p):
    if not lst: return 0
    lst = sorted(lst)
    return lst[int(len(lst) * p)]


def _wilson_ci(wins, total, z=1.645):
    """One-sided 95% Wilson confidence interval lower bound."""
    if total == 0: return 0
    p = wins / total
    return (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) / (1 + z*z/total)


def _ev_rows(data, thresholds, min_game_min=None):
    """EV rows using precise game minute as forward-looking filter."""
    rows = []
    for T in thresholds:
        if min_game_min is None:
            wins   = [r for r in data if r.get("win_min_p", 1) <= T]
            losses = [r for r in data if r.get("loser_min_p", 1) <= T]
        else:
            wins   = [r for r in data if r.get("win_min_p", 1) <= T
                      and r.get("accurate_game_min_of_bottom", 0) >= min_game_min]
            losses = [r for r in data if r.get("loser_min_p", 1) <= T
                      and r.get("accurate_loser_min_game_min", 0) >= min_game_min]
        total    = len(wins) + len(losses)
        if total == 0:
            continue
        win_rate = len(wins) / total
        ev       = win_rate / T - 1
        ev_ci_lo = _wilson_ci(len(wins), total) / T - 1
        rows.append({
            "threshold_pct": round(T * 100),
            "success":       len(wins),
            "failure":       len(losses),
            "total":         total,
            "win_rate_pct":  round(win_rate * 100, 1),
            "ev":            round(ev, 3),
            "ev_ci_lo":      round(ev_ci_lo, 3),
            "breakeven_wr":  round(T * 100, 0),
        })
    return rows


def compute_ev_raw(data):
    return _ev_rows(data, [0.10, 0.15, 0.20, 0.25, 0.30, 0.40])


def compute_ev_precise(data, min_game_min=15):
    """EV using accurate_game_min_of_bottom >= min_game_min (forward-looking)."""
    precise = [r for r in data if "accurate_game_min_of_bottom" in r]
    return _ev_rows(precise, [0.10, 0.15, 0.20, 0.25, 0.30, 0.40], min_game_min=min_game_min)


def compute_timing_stats(data):
    """Compute buy window & hold time percentiles from reversal games with precise timing."""
    rev = [r for r in data
           if r.get("win_min_p", 1) < 0.30 and "accurate_game_min_of_bottom" in r]
    if not rev:
        return {}

    entry = sorted(r["accurate_game_min_of_bottom"] for r in rev)
    hold  = sorted(r["accurate_mins_before_end"] for r in rev)
    prog  = sorted(r["accurate_game_min_of_bottom"] / r["accurate_game_duration_mins"] * 100
                   for r in rev if r.get("accurate_game_duration_mins", 0) > 0)
    n = len(entry)

    return {
        "n_reversal":     n,
        "entry_mean":     round(sum(entry)/n, 1),
        "entry_p25":      round(_percentile(entry, 0.25), 1),
        "entry_p50":      round(_percentile(entry, 0.50), 1),
        "entry_p75":      round(_percentile(entry, 0.75), 1),
        "entry_p90":      round(_percentile(entry, 0.90), 1),
        "hold_p50":       round(_percentile(hold, 0.50), 1),
        "hold_p75":       round(_percentile(hold, 0.75), 1),
        "hold_p90":       round(_percentile(hold, 0.90), 1),
        "prog_p25":       round(_percentile(prog, 0.25), 0),
        "prog_p50":       round(_percentile(prog, 0.50), 0),
        "prog_p75":       round(_percentile(prog, 0.75), 0),
        "avg_duration":   round(sum(r["accurate_game_duration_mins"] for r in rev) / n, 1),
        "dist": [
            {"label": f"{lo}–{hi if hi<999 else '40+'}分", "count":
             sum(1 for m in entry if lo <= m < hi), "lo": lo}
            for lo, hi in [(0,5),(5,10),(10,15),(15,20),(20,25),(25,30),(30,40),(40,999)]
        ],
    }


def compute_league_stats(data):
    leagues = ["LCK", "LPL", "LEC", "LCS"]
    rows = []
    for lg in leagues:
        sub = [r for r in data if r["league"] == lg]
        if not sub:
            continue
        rev30 = sum(1 for r in sub if r["win_min_p"] < 0.30)
        rev20 = sum(1 for r in sub if r["win_min_p"] < 0.20)
        avg_vol = sum(r["volume"] for r in sub) / len(sub)
        rows.append({
            "league": lg,
            "total": len(sub),
            "rev30": rev30,
            "rev30_pct": round(rev30 / len(sub) * 100, 1),
            "rev20": rev20,
            "rev20_pct": round(rev20 / len(sub) * 100, 1),
            "avg_vol": round(avg_vol),
        })
    return rows


def compute_timing_dist(data):
    reversal = [r for r in data if r["win_min_p"] < 0.30]
    buckets = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 60), (60, 999)]
    rows = []
    for lo, hi in buckets:
        cnt = sum(1 for r in reversal if lo <= r["mins_before_end"] < hi)
        label = f"{lo}–{hi if hi < 999 else '60+'} 分前"
        rows.append({"label": label, "count": cnt, "lo": lo, "hi": hi})
    return rows


def compute_timing_window_ev(data):
    """EV by (threshold × timing window) — the key 20-30min sweet-spot finding."""
    precise = [r for r in data
               if "accurate_game_min_of_bottom" in r and "accurate_loser_min_game_min" in r]
    thresholds = [0.10, 0.15, 0.20]
    windows = [("10–20分", 10, 20), ("15–25分", 15, 25), ("20–30分", 20, 30)]
    rows = []
    for T in thresholds:
        for label, t_lo, t_hi in windows:
            wins  = [r for r in precise
                     if r.get("win_min_p", 1) < T
                     and t_lo <= r.get("accurate_game_min_of_bottom", 0) < t_hi]
            fails = [r for r in precise
                     if r.get("loser_min_p", 1) < T
                     and t_lo <= r.get("accurate_loser_min_game_min", 0) < t_hi]
            total = len(wins) + len(fails)
            if total == 0:
                continue
            wr     = len(wins) / total
            ev     = wr / T - 1
            ev_ci  = _wilson_ci(len(wins), total) / T - 1
            rows.append({
                "threshold_pct": round(T * 100),
                "window":        label,
                "wins":          len(wins),
                "fails":         len(fails),
                "total":         total,
                "win_rate_pct":  round(wr * 100, 1),
                "ev":            round(ev, 3),
                "ev_ci_lo":      round(ev_ci, 3),
            })
    return rows


def compute_battle_state_ev(bs_data):
    """EV matrix for battle state filters, 20-30min window. Source: game_battle_state.json"""
    if not bs_data:
        return []

    rev   = [r for r in bs_data if r["case_type"] == "reversal"]
    norev = [r for r in bs_data if r["case_type"] == "no_reversal"]
    w20 = [r for r in rev   if 20 <= r.get("game_min", 0) <= 30]
    n20 = [r for r in norev if 20 <= r.get("game_min", 0) <= 30]

    combos = [
        ("全部（无过滤）",               lambda r: True),
        ("金币差 > -3000",               lambda r: r["gold_diff"] > -3000),
        ("金币差 > -4000",               lambda r: r["gold_diff"] > -4000),
        ("对方龙 ≤ 2",                   lambda r: r["opponent_dragons"] <= 2),
        ("有存活核心",                   lambda r: r["alive_cores"] >= 1),
        ("金差>-3000 + 龙≤2",            lambda r: r["gold_diff"] > -3000 and r["opponent_dragons"] <= 2),
        ("金差>-3000 + 龙≤2 + 有核心",  lambda r: r["gold_diff"] > -3000 and r["opponent_dragons"] <= 2 and r["alive_cores"] >= 1),
        ("金差>-4000 + 有核心",          lambda r: r["gold_diff"] > -4000 and r["alive_cores"] >= 1),
    ]

    results = []
    tiers = [("全赔率", lambda r: True), ("赔率 ≤ 15%", lambda r: r.get("cheap_odds", 1) <= 0.15)]
    for tier_label, tier_fn in tiers:
        wp = [r for r in w20 if tier_fn(r)]
        np_ = [r for r in n20 if tier_fn(r)]
        # 使用整个 tier 内的基准平均赔率（与 Script 12 方法一致），不按子集分别计算
        base_pool = wp + np_
        base_price = (sum(r.get("cheap_odds", 0.10) for r in base_pool) / len(base_pool)
                      if base_pool else 0.10)
        rows = []
        for label, fn in combos:
            wr_list = [r for r in wp  if fn(r)]
            nr_list = [r for r in np_ if fn(r)]
            total = len(wr_list) + len(nr_list)
            if total < 5:
                continue
            wr_rate = len(wr_list) / total
            ev_val  = wr_rate / base_price - 1 if base_price > 0 else 0
            wlo     = _wilson_ci(len(wr_list), total) / base_price - 1
            rows.append({
                "label":        label,
                "n":            total,
                "wins":         len(wr_list),
                "win_rate_pct": round(wr_rate * 100, 1),
                "ev":           round(ev_val, 2),
                "wilson_lo":    round(wlo, 2),
            })
        if rows:
            results.append({"tier": tier_label, "rows": rows})
    return results


def compute_b_type_stats():
    """
    B-type strategy: pre-game strong favorite (>65% or >75%) dips in-game.
    Reads raw game_price_history files. Computed 2026-05-30.
    """
    import glob as _glob
    files = _glob.glob(str(BASE / "data/game_price_history/*.json"))
    results = []
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
        except Exception:
            continue
        hist = d.get("history", [])
        if len(hist) < 10:
            continue
        lp = d.get("last_price_0")
        if lp not in (0.0, 1.0):
            continue
        team0_won = (lp == 1.0)
        prices = [h["p"] for h in hist]
        n = len(prices)
        pre_end  = max(3, int(n * 0.20))
        ig_end   = max(pre_end + 3, int(n * 0.90))
        ingame   = prices[pre_end:ig_end]
        if len(ingame) < 5:
            continue
        results.append({
            "open_p0":      sum(prices[:pre_end]) / pre_end,
            "min_ingame_p0": min(ingame),
            "max_ingame_p0": max(ingame),
            "team0_won":     team0_won,
        })

    BUCKET_ORDER = ["跌至>80%", "跌至70-80%", "跌至60-70%",
                    "跌至50-60%", "跌至40-50%", "跌至<40%"]
    COST_MAP     = {"跌至>80%":0.87, "跌至70-80%":0.75, "跌至60-70%":0.65,
                    "跌至50-60%":0.55, "跌至40-50%":0.45, "跌至<40%":0.32}

    def _analyze(thresh):
        bk = {b: {"wins": 0, "total": 0} for b in BUCKET_ORDER}
        for r in results:
            op = r["open_p0"]
            if op >= thresh:
                fav_min, won = r["min_ingame_p0"], r["team0_won"]
            elif (1 - op) >= thresh:
                fav_min, won = 1 - r["max_ingame_p0"], not r["team0_won"]
            else:
                continue
            if   fav_min >= 0.80: b = "跌至>80%"
            elif fav_min >= 0.70: b = "跌至70-80%"
            elif fav_min >= 0.60: b = "跌至60-70%"
            elif fav_min >= 0.50: b = "跌至50-60%"
            elif fav_min >= 0.40: b = "跌至40-50%"
            else:                 b = "跌至<40%"
            bk[b]["wins"]  += int(won)
            bk[b]["total"] += 1
        rows = []
        for b in BUCKET_ORDER:
            w, t = bk[b]["wins"], bk[b]["total"]
            if t == 0:
                continue
            rate = w / t
            cost = COST_MAP[b]
            ev   = (rate - cost) / cost * 100
            # verdict: 'best_ev'=最优EV, 'best_wr'=高胜率稳健, 'ok'=可以, 'risky'=高EV但波动, 'warn'=危险
            if b == "跌至50-60%" and ev > 25:
                verdict = "best_ev"   # 最优EV区间
            elif b == "跌至70-80%" and ev > 10:
                verdict = "best_wr"   # 高胜率稳健区间
            elif b == "跌至40-50%" and ev > 15:
                verdict = "risky"     # 高EV但胜率偏低
            elif b == "跌至<40%" or ev < 0:
                verdict = "warn"
            else:
                verdict = "ok"
            rows.append({
                "bucket":   b,
                "total":    t,
                "wins":     w,
                "win_rate": round(rate * 100, 1),
                "ev":       round(ev, 1),
                "verdict":  verdict,
            })
        return rows

    return {"thresh65": _analyze(0.65), "thresh75": _analyze(0.75)}


def compute_lottery_games(data):
    """Top reversal cases where winner was priced < 10% — the 'lottery ticket' plays."""
    precise = [r for r in data if "accurate_game_min_of_bottom" in r]
    lottery = [r for r in precise
               if r.get("win_min_p", 1) < 0.10
               and r.get("accurate_game_min_of_bottom", 0) >= 10]
    lottery.sort(key=lambda x: x["win_min_p"])
    return [{
        "league":   r["league"],
        "winner":   r["winner"],
        "loser":    r["loser"],
        "min_p_pct": round(r["win_min_p"] * 100, 1),
        "bot_min":  round(r.get("accurate_game_min_of_bottom", 0), 0),
        "dur":      round(r.get("accurate_game_duration_mins", 0), 0),
        "hold":     round(r.get("accurate_mins_before_end", 0), 0),
        "date":     r.get("game_date", ""),
        "vol":      r.get("volume", 0),
        "open_p_pct": round(r.get("game_open_p", 0) * 100, 1),
    } for r in lottery]


def main():
    data         = json.loads(ANALYSIS_FILE.read_text())
    bs_data      = json.loads(BS_FILE.read_text()) if BS_FILE.exists() else []
    ev_raw       = compute_ev_raw(data)
    ev_precise   = compute_ev_precise(data, min_game_min=20)
    lg_stats     = compute_league_stats(data)
    timing_dist  = compute_timing_dist(data)
    timing_stats = compute_timing_stats(data)
    tw_ev        = compute_timing_window_ev(data)
    lottery      = compute_lottery_games(data)
    bs_ev        = compute_battle_state_ev(bs_data)
    b_type       = compute_b_type_stats()

    html = TEMPLATE
    html = html.replace("__DATA_PLACEHOLDER__",         json.dumps(data,         ensure_ascii=False))
    html = html.replace("__EV_RAW_PLACEHOLDER__",       json.dumps(ev_raw,       ensure_ascii=False))
    html = html.replace("__EV_TIMED_PLACEHOLDER__",     json.dumps(ev_precise,   ensure_ascii=False))
    html = html.replace("__LG_STATS_PLACEHOLDER__",     json.dumps(lg_stats,     ensure_ascii=False))
    html = html.replace("__TIMING_PLACEHOLDER__",       json.dumps(timing_dist,  ensure_ascii=False))
    html = html.replace("__TIMING_STATS_PLACEHOLDER__", json.dumps(timing_stats, ensure_ascii=False))
    html = html.replace("__TW_EV_PLACEHOLDER__",        json.dumps(tw_ev,        ensure_ascii=False))
    html = html.replace("__LOTTERY_PLACEHOLDER__",      json.dumps(lottery,      ensure_ascii=False))
    html = html.replace("__BS_EV_PLACEHOLDER__",        json.dumps(bs_ev,        ensure_ascii=False))
    html = html.replace("__B_TYPE_PLACEHOLDER__",       json.dumps(b_type,       ensure_ascii=False))

    OUT_FILE.write_text(html, encoding="utf-8")
    print(f"Written: {OUT_FILE}  ({len(data)} records)")
    print()
    print("EV (precise timing ≥20 game min):")
    for r in ev_precise:
        sign = "+" if r["ev"] > 0 else ""
        flag = " ★" if r["ev"] > 0 else ""
        print(f"  @{r['threshold_pct']:2d}%: WR={r['win_rate_pct']}% EV={sign}{r['ev']:.2f} (n={r['total']}){flag}")
    print()
    ts = timing_stats
    if ts:
        print(f"Buy window (IQR): {ts['entry_p25']}–{ts['entry_p75']} min  (median {ts['entry_p50']} min)")
        print(f"Hold time P90: {ts['hold_p90']} min")


if __name__ == "__main__":
    main()
