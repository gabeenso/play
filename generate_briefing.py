#!/usr/bin/env python3
"""
Gabe's Weekly Intelligence Briefing — Generator
- Fetches FRED data server-side, writes market_data.json (no CORS issues)
- Generates index.html with editorial content + JS that reads market_data.json
- JS also fetches Twelve Data (SPX/Gold/AUD) + CoinGecko + F&G directly in browser
"""

import requests
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

HEADERS      = {"User-Agent": "Mozilla/5.0 (compatible; IntelBriefing/1.0)"}
FRED_API_KEY = os.environ.get("FRED_API_KEY", "6d18d219c04d01ecd8c5dd1a9dcf43f7")
TWELVE_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "9de622129104418cb717994ac9d7d70e")


# ─── FRED FETCHERS (server-side only) ─────────────────────────

def fred_fetch(sid, limit=2, multiplier=1.0):
    """Fetch latest N observations from FRED. Returns list of (date, value) tuples."""
    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={sid}&api_key={FRED_API_KEY}"
            f"&file_type=json&sort_order=desc&limit={limit}"
        )
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        obs = [o for o in r.json()["observations"] if o["value"] != "."]
        return [(o["date"], round(float(o["value"]) * multiplier, 4)) for o in obs]
    except Exception as e:
        print(f"[WARN] FRED {sid} failed: {e}")
        return []


def fetch_sp500_ma():
    """S&P 500 50d/200d MA from FRED SP500 series."""
    try:
        obs = fred_fetch("SP500", limit=210)
        closes = [v for _, v in reversed(obs)]
        if len(closes) < 200:
            print(f"[WARN] SP500 MA: only {len(closes)} observations")
            return {"ma50": None, "ma200": None, "death_cross": None}
        ma50  = round(sum(closes[-50:])  / 50,  0)
        ma200 = round(sum(closes[-200:]) / 200, 0)
        return {"ma50": ma50, "ma200": ma200, "death_cross": bool(ma50 < ma200)}
    except Exception as e:
        print(f"[WARN] SP500 MA failed: {e}")
        return {"ma50": None, "ma200": None, "death_cross": None}


def fetch_market_data():
    """Fetch all FRED-based market data. Returns dict for market_data.json."""
    data = {}

    for key, sid, mult in [
        ("vix",  "VIXCLS",      1.0),
        ("oil",  "DCOILWTICO",  1.0),
        ("tnx",  "DGS10",       1.0),
        ("hy",   "BAMLH0A0HYM2", 100.0),
        ("ig",   "BAMLC0A4CBBB", 100.0),
    ]:
        obs = fred_fetch(sid, limit=2, multiplier=mult)
        if len(obs) >= 2:
            date, latest = obs[0]
            _,    prev   = obs[1]
            data[key] = {
                "price":      round(latest, 4),
                "prev":       round(prev, 4),
                "change_pct": round((latest - prev) / prev * 100, 2) if key not in ("hy", "ig") else None,
                "change_bps": round(latest - prev, 1) if key in ("hy", "ig") else None,
                "date":       date,
            }
        else:
            data[key] = {}

    data["sp_ma"] = fetch_sp500_ma()

    now_utc = datetime.now(timezone.utc)
    data["updated_utc"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return data


# ─── STATIC CONTENT ───────────────────────────────────────────

def load_static_content():
    path = Path(__file__).parent / "static_content.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ─── HTML GENERATOR ───────────────────────────────────────────

def generate_html(static, build_str, briefing_date):
    master_verdict = static.get("master_verdict", "CAUTION")
    verdict_color  = {"DANGER": "#ff4444", "CAUTION": "#f59e0b", "CLEAR": "#22c55e", "WAIT": "#6366f1"}.get(master_verdict, "#f59e0b")
    mv_bg = {"DANGER": "linear-gradient(135deg,#1a0a0a,#2a1010)", "CAUTION": "linear-gradient(135deg,#1a1400,#2a2000)", "CLEAR": "linear-gradient(135deg,#0a1a0a,#102a10)"}.get(master_verdict, "linear-gradient(135deg,#0d0f14,#141720)")
    vc_rgb = ",".join(str(int(verdict_color.lstrip("#")[i:i+2], 16)) for i in (0, 2, 4))

    # Checklist
    checklist_html = ""
    for item in static.get("checklist", []):
        state = item.get("state", "open")
        cls  = {"done": "done", "partial": "partial", "open": "open"}.get(state, "open")
        icon = {"done": "✓", "partial": "◐", "open": "☐"}.get(state, "☐")
        checklist_html += f'<div class="check-item {cls}"><span class="check-icon">{icon}</span>{item.get("text","")}</div>'

    # Crypto rows (signals static, prices via JS)
    sym_styles  = {"BTC": "#f7931a", "ETH": "#627eea", "XRP": "#00aae4", "SOL": "#9945ff"}
    sym_signals = static.get("crypto_signals", {})
    crypto_rows = ""
    for sym in ["BTC", "ETH", "XRP", "SOL"]:
        color = sym_styles.get(sym, "#fff")
        sig   = sym_signals.get(sym, "—")
        crypto_rows += f"""
            <tr id="crypto-row-{sym}">
              <td><span style="font-weight:700;color:{color};font-size:15px">{sym}</span></td>
              <td class="crypto-price">—</td>
              <td class="crypto-24h">—</td>
              <td class="crypto-7d">—</td>
              <td style="color:#8892a4;font-size:12px">{sig}</td>
            </tr>"""

    # Editorial sections
    verdict_colors = {"DANGER": "#ff4444", "CAUTION": "#f59e0b", "CLEAR": "#22c55e", "WAIT": "#a5b4fc", "ACCELERATING": "#22c55e", "FEAR": "#ff4444"}
    sections_html = ""
    for section in static.get("sections", []):
        verdict = section.get("verdict", "CAUTION")
        v_color = verdict_colors.get(verdict, "#f59e0b")
        items_html = ""
        for item in section.get("items", []):
            status    = item.get("status", "caution")
            dot_color = {"danger": "#ff4444", "caution": "#f59e0b", "clear": "#22c55e"}.get(status, "#f59e0b")
            di = {"up": "▲", "down": "▼", "flat": "="}.get(item.get("delta", "flat"), "=")
            dc = {"up": "#22c55e", "down": "#ff4444", "flat": "#94a3b8"}.get(item.get("delta", "flat"), "#94a3b8")
            items_html += f"""
            <div class="edit-card {status}">
              <div class="glow-dot" style="background:{dot_color};box-shadow:0 0 8px {dot_color}"></div>
              <div class="card-label">{item.get('label','')}</div>
              <div class="card-value" style="color:{dot_color}">{item.get('value','')}</div>
              <div class="card-sub"><span style="color:{dc};font-weight:700">{di}</span> {item.get('sub','')}</div>
              <div class="card-note">{item.get('note','')}</div>
            </div>"""
        sections_html += f"""
      <div class="section-header">
        <span class="section-num">{section.get('num','')}</span>
        <h2>{section.get('title','')}</h2>
        <span class="verdict-inline" style="background:rgba(0,0,0,0.3);color:{v_color};border:1px solid {v_color}">{verdict}</span>
        <span style="font-size:11px;color:#8892a4;margin-left:auto">Weekly editorial · Updated {briefing_date}</span>
      </div>
      <div class="cards-grid">{items_html}</div>
      <div class="action-bar"><strong>Action:</strong> {section.get('action','')}</div>"""

    # Summary table
    summary_rows_html = ""
    for r in static.get("summary_rows", []):
        vc = verdict_colors.get(r["status"], "#f59e0b")
        summary_rows_html += (
            f'<tr><td><strong>{r["section"]}</strong></td>'
            f'<td><span class="verdict-inline" style="background:rgba(0,0,0,.3);color:{vc};border:1px solid {vc}">{r["status"]}</span></td>'
            f'<td>{r["key"]}</td><td>{r["direction"]}</td><td>{r["action"]}</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Intel Briefing · {build_str}</title>
<style>
  :root{{--bg:#0d0f14;--card:#141720;--card2:#1a1f2e;--border:#252a3a;--text:#e2e8f0;--muted:#8892a4;--danger:#ff4444;--danger-glow:rgba(255,68,68,.25);--caution:#f59e0b;--caution-glow:rgba(245,158,11,.25);--clear:#22c55e;--clear-glow:rgba(34,197,94,.25);--accent:#6366f1}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.5}}
  .container{{max-width:1280px;margin:0 auto;padding:24px 16px}}
  .master-banner{{background:{mv_bg};border:2px solid {verdict_color};border-radius:12px;padding:20px 28px;margin-bottom:24px;box-shadow:0 0 30px rgba({vc_rgb},.3);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}}
  .master-banner h1{{font-size:22px;font-weight:700}}
  .verdict-badge{{font-size:28px;font-weight:900;letter-spacing:3px;color:{verdict_color};text-shadow:0 0 20px {verdict_color}}}
  .meta{{color:var(--muted);font-size:12px;margin-top:4px}}
  .live-badge{{display:inline-block;background:rgba(34,197,94,.15);color:#22c55e;border:1px solid #22c55e;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;letter-spacing:1px;animation:pulse 2s infinite}}
  .checklist-section{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:24px}}
  .checklist-section h2{{font-size:13px;text-transform:uppercase;letter-spacing:2px;color:var(--muted);margin-bottom:14px}}
  .checklist-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px}}
  .check-item{{display:flex;align-items:center;gap:10px;background:var(--card2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:13px}}
  .check-icon{{font-size:16px;flex-shrink:0}}
  .check-item.done{{border-color:rgba(34,197,94,.3);background:rgba(34,197,94,.05)}}
  .check-item.partial{{border-color:rgba(245,158,11,.3);background:rgba(245,158,11,.05)}}
  .check-item.open{{border-color:rgba(255,68,68,.3);background:rgba(255,68,68,.05)}}
  .live-section{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:24px}}
  .live-section-header{{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
  .live-section-header h2{{font-size:16px;font-weight:700;text-transform:uppercase;letter-spacing:1px}}
  .live-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
  .live-card{{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:14px}}
  .live-card-label{{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px}}
  .live-card-value{{font-size:22px;font-weight:700;margin-bottom:4px}}
  .live-card-sub{{font-size:12px;color:var(--muted)}}
  .section-header{{display:flex;align-items:center;gap:12px;margin:28px 0 14px;flex-wrap:wrap}}
  .section-header h2{{font-size:16px;font-weight:700;text-transform:uppercase;letter-spacing:1px}}
  .section-num{{color:var(--muted);font-size:12px}}
  .cards-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-bottom:14px}}
  .edit-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;position:relative}}
  .edit-card.danger{{border-color:rgba(255,68,68,.5);box-shadow:0 0 12px var(--danger-glow)}}
  .edit-card.caution{{border-color:rgba(245,158,11,.4);box-shadow:0 0 12px var(--caution-glow)}}
  .edit-card.clear{{border-color:rgba(34,197,94,.4);box-shadow:0 0 12px var(--clear-glow)}}
  .glow-dot{{width:10px;height:10px;border-radius:50%;position:absolute;top:14px;right:14px;animation:pulse 2s infinite}}
  .card-label{{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px}}
  .card-value{{font-size:20px;font-weight:700;margin-bottom:4px}}
  .card-sub{{font-size:12px;color:var(--muted)}}
  .card-note{{font-size:12px;margin-top:8px;color:var(--text)}}
  .verdict-inline{{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase}}
  .action-bar{{background:linear-gradient(90deg,var(--card2),var(--card));border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:8px;padding:12px 18px;font-size:13px;margin-bottom:8px}}
  .action-bar strong{{color:var(--accent)}}
  .crypto-table-wrap{{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:14px}}
  table{{width:100%;border-collapse:collapse}}
  thead{{background:var(--card2)}}
  th{{padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);border-bottom:1px solid var(--border)}}
  td{{padding:12px 14px;border-bottom:1px solid rgba(37,42,58,.5);font-size:13px}}
  tr:last-child td{{border-bottom:none}}
  tr:hover td{{background:rgba(255,255,255,.02)}}
  .summary-table{{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin:24px 0}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
  @media(max-width:600px){{.master-banner{{flex-direction:column}}.live-grid{{grid-template-columns:repeat(2,1fr)}}.cards-grid{{grid-template-columns:1fr}}}}
  footer{{text-align:center;color:var(--muted);font-size:11px;padding:24px 0 12px}}
  hr{{border:none;border-top:1px solid var(--border);margin:8px 0}}
  .spinner{{display:none;width:10px;height:10px;border:2px solid #22c55e;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite;vertical-align:middle;margin-left:6px}}
  @keyframes spin{{to{{transform:rotate(360deg)}}}}
  .stale-badge{{display:inline-block;background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid #f59e0b;border-radius:4px;padding:2px 6px;font-size:10px;margin-left:4px}}
</style>
</head>
<body>
<div class="container">

  <!-- MASTER BANNER -->
  <div class="master-banner">
    <div>
      <h1>⚡ Weekly Intelligence Briefing</h1>
      <div class="meta">Gabe Enslin · Prices refreshed: <span id="last-updated">loading...</span><span class="spinner" id="refresh-spinner"></span> &nbsp;<span class="live-badge">● LIVE</span></div>
      <div class="meta" style="margin-top:4px">Editorial commentary: updated {briefing_date}</div>
    </div>
    <div style="text-align:right">
      <div class="verdict-badge">⚠ {master_verdict}</div>
      <div class="meta">{static.get("master_summary","")}</div>
    </div>
  </div>

  <!-- TRIGGER CHECKLIST -->
  <div class="checklist-section">
    <h2>🎯 Re-Entry Trigger Checklist</h2>
    <div class="checklist-grid">{checklist_html}</div>
  </div>

  <!-- LIVE MARKET DATA -->
  <div class="live-section">
    <div class="live-section-header">
      <span style="color:#8892a4;font-size:12px">00</span>
      <h2>Live Market Snapshot</h2>
      <span class="live-badge">● REFRESHES EVERY 5 MIN</span>
    </div>
    <div class="live-grid">
      <div class="live-card">
        <div class="live-card-label">S&amp;P 500</div>
        <div class="live-card-value" id="spx-val">—</div>
        <div class="live-card-sub" id="spx-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">VIX (Fear Index) <span class="stale-badge">daily</span></div>
        <div class="live-card-value" id="vix-val">—</div>
        <div class="live-card-sub" id="vix-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Death Cross (50d/200d) <span class="stale-badge">daily</span></div>
        <div class="live-card-value" style="font-size:14px" id="dc-label">—</div>
        <div class="live-card-sub" id="dc-sub">—</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">HY Credit Spreads <span class="stale-badge">daily</span></div>
        <div class="live-card-value" id="hy-val">—</div>
        <div class="live-card-sub" id="hy-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">IG Credit Spreads <span class="stale-badge">daily</span></div>
        <div class="live-card-value" id="ig-val">—</div>
        <div class="live-card-sub" id="ig-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Fear &amp; Greed Index</div>
        <div class="live-card-value" id="fg-val">—</div>
        <div class="live-card-sub" id="fg-sub"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Oil (WTI) <span class="stale-badge">daily</span></div>
        <div class="live-card-value" id="oil-val">—</div>
        <div class="live-card-sub" id="oil-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Gold</div>
        <div class="live-card-value" id="gold-val">—</div>
        <div class="live-card-sub" id="gold-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">AUD/USD</div>
        <div class="live-card-value" id="aud-val">—</div>
        <div class="live-card-sub" id="aud-delta"></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">US 10Y Yield <span class="stale-badge">daily</span></div>
        <div class="live-card-value" id="tnx-val">—</div>
        <div class="live-card-sub" id="tnx-delta"></div>
      </div>
    </div>
  </div>

  <!-- LIVE CRYPTO -->
  <div class="section-header">
    <span class="section-num">CRYPTO</span>
    <h2>Crypto</h2>
    <span class="live-badge" style="font-size:11px;background:rgba(34,197,94,.15);color:#22c55e;border:1px solid #22c55e;border-radius:4px;padding:2px 8px;font-weight:700">● LIVE PRICES</span>
    <span style="font-size:11px;color:#8892a4;margin-left:auto" id="fg-header"></span>
  </div>
  <div class="crypto-table-wrap">
    <table>
      <thead><tr><th>Symbol</th><th>Price (USD)</th><th>24h</th><th>Signal (weekly)</th></tr></thead>
      <tbody>{crypto_rows}</tbody>
    </table>
  </div>
  <div class="action-bar"><strong>Crypto Action:</strong> {static.get("crypto_action","Monitor conditions before new positions.")}</div>

  <!-- EDITORIAL SECTIONS -->
  {sections_html}

  <!-- SUMMARY TABLE -->
  <div class="summary-table">
    <table>
      <thead><tr><th>Section</th><th>Status</th><th>Key Number</th><th>Direction</th><th>Action</th></tr></thead>
      <tbody>{summary_rows_html}</tbody>
    </table>
  </div>

  <footer>
    Prices: Twelve Data · CoinGecko · Alternative.me &nbsp;|&nbsp; Daily metrics (VIX/Oil/10Y/Spreads/MA): FRED via GitHub Actions &nbsp;|&nbsp; Not financial advice.
  </footer>

</div>

<script>
const TWELVE_KEY = '9de622129104418cb717994ac9d7d70e';

function dh(val, reverse) {{
  if (val == null) return '';
  const up = reverse ? '#ff4444' : '#22c55e';
  const dn = reverse ? '#22c55e' : '#ff4444';
  const s  = val >= 0 ? '+' : '';
  if (val >  0.05) return `<span style="color:${{up}};font-weight:700">▲ ${{s}}${{val.toFixed(2)}}%</span>`;
  if (val < -0.05) return `<span style="color:${{dn}};font-weight:700">▼ ${{val.toFixed(2)}}%</span>`;
  return `<span style="color:#94a3b8;font-weight:700">= ${{s}}${{val.toFixed(2)}}%</span>`;
}}

function bh(bps) {{
  if (bps == null) return '';
  if (bps > 0) return `<span style="color:#ff4444;font-weight:700">▲ +${{bps.toFixed(0)}} bps</span>`;
  if (bps < 0) return `<span style="color:#22c55e;font-weight:700">▼ ${{bps.toFixed(0)}} bps</span>`;
  return `<span style="color:#94a3b8;font-weight:700">= 0 bps</span>`;
}}

function set(id, val, isText) {{
  const el = document.getElementById(id);
  if (!el) return;
  isText ? (el.textContent = val) : (el.innerHTML = val);
}}

// ── Load FRED data from market_data.json (served same-origin, no CORS) ──
async function loadMarketData() {{
  try {{
    const r = await fetch('market_data.json?t=' + Date.now());
    if (!r.ok) return;
    const d = await r.json();

    // VIX
    if (d.vix?.price != null) {{
      const el = document.getElementById('vix-val');
      const v  = d.vix.price;
      el.style.color = v > 30 ? '#ff4444' : (v > 20 ? '#f59e0b' : '#22c55e');
      el.textContent  = v.toFixed(1);
      set('vix-delta', dh(d.vix.change_pct, true));
    }}
    // Oil
    if (d.oil?.price != null) {{
      set('oil-val',   '$' + d.oil.price.toFixed(2), true);
      set('oil-delta', dh(d.oil.change_pct, true));
    }}
    // 10Y
    if (d.tnx?.price != null) {{
      set('tnx-val',   d.tnx.price.toFixed(2) + '%', true);
      set('tnx-delta', dh(d.tnx.change_pct, true));
    }}
    // HY Spreads
    if (d.hy?.price != null) {{
      const el = document.getElementById('hy-val');
      const v  = d.hy.price;
      el.textContent = v.toFixed(0) + ' bps';
      el.style.color  = v > 500 ? '#ff4444' : (v > 350 ? '#f59e0b' : '#22c55e');
      set('hy-delta', bh(d.hy.change_bps) + (d.hy.date ? ` · <span style="font-size:11px">FRED: ${{d.hy.date}}</span>` : ''));
    }}
    // IG Spreads
    if (d.ig?.price != null) {{
      const el = document.getElementById('ig-val');
      const v  = d.ig.price;
      el.textContent = v.toFixed(0) + ' bps';
      el.style.color  = v > 200 ? '#ff4444' : (v > 120 ? '#f59e0b' : '#22c55e');
      set('ig-delta', bh(d.ig.change_bps) + (d.ig.date ? ` · <span style="font-size:11px">FRED: ${{d.ig.date}}</span>` : ''));
    }}
    // Death Cross
    if (d.sp_ma?.ma50 != null) {{
      const isDeath = d.sp_ma.death_cross;
      const el = document.getElementById('dc-label');
      el.style.color = isDeath ? '#ff4444' : '#22c55e';
      el.textContent  = isDeath ? '⚠ Death Cross Active' : '✓ No Death Cross';
      set('dc-sub', `50d: ${{d.sp_ma.ma50}} · 200d: ${{d.sp_ma.ma200}}`, true);
    }}
  }} catch(e) {{ console.warn('market_data.json load failed:', e); }}
}}

// ── Twelve Data: SPX (separate call), Gold + AUD/USD ──
async function fetchTwelve() {{
  // Forex batch
  try {{
    const fd = await (await fetch(`https://api.twelvedata.com/quote?symbol=XAU/USD,AUD/USD&apikey=${{TWELVE_KEY}}`)).json();
    const gold = fd['XAU/USD'];
    if (gold?.close) {{
      const p = +gold.close, pv = +gold.previous_close;
      set('gold-val',   '$' + p.toLocaleString('en-US', {{maximumFractionDigits:0}}), true);
      set('gold-delta', dh((p-pv)/pv*100));
    }}
    const aud = fd['AUD/USD'];
    if (aud?.close) {{
      const p = +aud.close, pv = +aud.previous_close;
      set('aud-val',   p.toFixed(4), true);
      set('aud-delta', dh((p-pv)/pv*100));
    }}
  }} catch(e) {{ console.warn('Twelve forex failed:', e); }}

  // SPX separate call
  try {{
    const sd = await (await fetch(`https://api.twelvedata.com/quote?symbol=SPX&apikey=${{TWELVE_KEY}}`)).json();
    if (sd?.close) {{
      const p = +sd.close, pv = +sd.previous_close;
      set('spx-val',   '$' + p.toLocaleString('en-US', {{maximumFractionDigits:0}}), true);
      set('spx-delta', dh((p-pv)/pv*100));
    }}
  }} catch(e) {{ console.warn('Twelve SPX failed:', e); }}
}}

// ── CoinGecko crypto ──
async function fetchCrypto() {{
  try {{
    const url = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,ripple,solana&vs_currencies=usd&include_24hr_change=true';
    const d   = await (await fetch(url)).json();
    const map = {{BTC:'bitcoin', ETH:'ethereum', XRP:'ripple', SOL:'solana'}};
    for (const [sym, id] of Object.entries(map)) {{
      const row = document.getElementById(`crypto-row-${{sym}}`);
      if (!row || !d[id]) continue;
      const p   = d[id].usd;
      const c24 = d[id].usd_24h_change || 0;
      const ps  = p > 100 ? '$' + p.toLocaleString('en-US', {{maximumFractionDigits:0}}) : '$' + p.toFixed(4);
      row.querySelector('.crypto-price').innerHTML = `<strong>${{ps}}</strong>`;
      row.querySelector('.crypto-24h').innerHTML   = dh(c24);
    }}
  }} catch(e) {{ console.warn('Crypto failed:', e); }}
}}

// ── Fear & Greed ──
async function fetchFG() {{
  try {{
    const d     = await (await fetch('https://api.alternative.me/fng/?limit=1')).json();
    const entry = d.data[0];
    const val   = +entry.value;
    const label = entry.value_classification;
    const color = val < 30 ? '#ff4444' : (val < 50 ? '#f59e0b' : '#22c55e');
    const emoji = val < 25 ? '😱' : (val < 40 ? '😨' : (val < 55 ? '😐' : (val < 75 ? '😊' : '🤩')));
    const el    = document.getElementById('fg-val');
    el.style.color = color;
    el.textContent  = `${{emoji}} ${{val}}`;
    set('fg-sub',    label, true);
    set('fg-header', `F&G: ${{val}} — ${{label}} ${{emoji}}`, true);
  }} catch(e) {{ console.warn('F&G failed:', e); }}
}}

// ── Refresh loop ──
let lastRefresh = null;

function updateTimer() {{
  if (!lastRefresh) return;
  const s   = Math.round((Date.now() - lastRefresh) / 1000);
  const txt = s < 60 ? `${{s}}s ago` : `${{Math.floor(s/60)}}m ${{s%60}}s ago`;
  set('last-updated', txt, true);
}}

async function refreshAll() {{
  const spin = document.getElementById('refresh-spinner');
  if (spin) spin.style.display = 'inline-block';
  await Promise.allSettled([fetchTwelve(), fetchCrypto(), fetchFG()]);
  lastRefresh = Date.now();
  if (spin) spin.style.display = 'none';
  updateTimer();
}}

// Market data (FRED) loads once — it's daily, no need to re-fetch every 5 min
loadMarketData();
// Live prices refresh every 5 min
refreshAll();
setInterval(refreshAll,  5 * 60 * 1000);
setInterval(updateTimer, 15 * 1000);
</script>
</body>
</html>"""


# ─── MAIN ─────────────────────────────────────────────────────

if __name__ == "__main__":
    now_utc    = datetime.now(timezone.utc)
    now_sydney = now_utc + timedelta(hours=11)
    build_str  = now_sydney.strftime("%a %d %b %Y %H:%M AEDT")

    print("📡 Fetching FRED market data...")
    market_data = fetch_market_data()
    print(f"   VIX:  {market_data.get('vix',{}).get('price','—')}")
    print(f"   Oil:  {market_data.get('oil',{}).get('price','—')}")
    print(f"   10Y:  {market_data.get('tnx',{}).get('price','—')}")
    print(f"   HY:   {market_data.get('hy',{}).get('price','—')} bps")
    print(f"   IG:   {market_data.get('ig',{}).get('price','—')} bps")
    print(f"   MA50: {market_data.get('sp_ma',{}).get('ma50','—')}")

    md_path = Path(__file__).parent / "market_data.json"
    md_path.write_text(json.dumps(market_data, indent=2), encoding="utf-8")
    print(f"✅ market_data.json written")

    print("📋 Loading editorial content...")
    static       = load_static_content()
    briefing_date = static.get("briefing_date", "Unknown")

    print("📝 Generating index.html...")
    html = generate_html(static, build_str, briefing_date)
    out_path = Path(__file__).parent / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ index.html written")
