#!/usr/bin/env python3
"""
Gabe's Weekly Intelligence Briefing — Daily Auto-Generator
Fetches live market data and merges with weekly editorial content.
Run manually or via GitHub Actions cron.
"""

import requests
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IntelBriefing/1.0)"}

# ─── LIVE DATA FETCHERS ────────────────────────────────────────

def fetch_crypto():
    """CoinGecko public API — no key required."""
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,ripple,solana"
            "&vs_currencies=usd"
            "&include_24hr_change=true"
            "&include_7d_vol_cap=false"
            "&include_7d_change=true"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()
        return {
            "BTC": {
                "price": d["bitcoin"]["usd"],
                "change_24h": round(d["bitcoin"].get("usd_24h_change", 0), 2),
                "change_7d":  round(d["bitcoin"].get("usd_7d_change", 0), 2),
            },
            "ETH": {
                "price": d["ethereum"]["usd"],
                "change_24h": round(d["ethereum"].get("usd_24h_change", 0), 2),
                "change_7d":  round(d["ethereum"].get("usd_7d_change", 0), 2),
            },
            "XRP": {
                "price": round(d["ripple"]["usd"], 4),
                "change_24h": round(d["ripple"].get("usd_24h_change", 0), 2),
                "change_7d":  round(d["ripple"].get("usd_7d_change", 0), 2),
            },
            "SOL": {
                "price": round(d["solana"]["usd"], 2),
                "change_24h": round(d["solana"].get("usd_24h_change", 0), 2),
                "change_7d":  round(d["solana"].get("usd_7d_change", 0), 2),
            },
        }
    except Exception as e:
        print(f"[WARN] CoinGecko fetch failed: {e}")
        return None


def fetch_fear_greed():
    """Alternative.me Fear & Greed Index — no key required."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        r.raise_for_status()
        data = r.json()["data"][0]
        return {
            "value": int(data["value"]),
            "label": data["value_classification"],
        }
    except Exception as e:
        print(f"[WARN] Fear & Greed fetch failed: {e}")
        return {"value": 0, "label": "Unknown"}


def fetch_stooq(symbol, days=5):
    """Fetch closing prices from Stooq — free, no key, no blocks."""
    try:
        from datetime import date, timedelta
        end   = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=days*2 + 10)).strftime("%Y%m%d")
        url = f"https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d"
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("Date")]
        if len(lines) < 2:
            return None
        def parse_close(row):
            parts = row.split(",")
            return float(parts[4]) if len(parts) >= 5 else None
        latest = parse_close(lines[-1])
        prev   = parse_close(lines[-2])
        if not latest or not prev:
            return None
        return {"price": round(latest, 4), "change_pct": round((latest - prev) / prev * 100, 2), "all": lines}
    except Exception as e:
        print(f"[WARN] Stooq {symbol} failed: {e}")
        return None


def fetch_market_indices():
    """Stooq — free market data, no API key, reliable from GitHub Actions."""
    tickers = {
        "SPX":    "^spx",
        "VIX":    "^vix.cboe",
        "OIL":    "cl.f",
        "GOLD":   "xauusd",
        "AUDUSD": "audusd",
        "TNX":    "10us.b",
    }
    results = {}
    for name, sym in tickers.items():
        q = fetch_stooq(sym)
        results[name] = {"price": q["price"], "change_pct": q["change_pct"]} if q else {"price": None, "change_pct": None}
    return results


def fetch_sp500_ma():
    """S&P 500 50d vs 200d MA via Stooq — death cross detector."""
    try:
        from datetime import date, timedelta
        end   = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=300)).strftime("%Y%m%d")
        url   = f"https://stooq.com/q/d/l/?s=^spx&d1={start}&d2={end}&i=d"
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("Date")]
        closes = []
        for l in lines:
            parts = l.split(",")
            try:
                closes.append(float(parts[4]))
            except:
                pass
        if len(closes) < 200:
            return {"ma50": None, "ma200": None, "death_cross": None}
        ma50  = round(sum(closes[-50:])  / 50,  0)
        ma200 = round(sum(closes[-200:]) / 200, 0)
        return {"ma50": ma50, "ma200": ma200, "death_cross": ma50 < ma200}
    except Exception as e:
        print(f"[WARN] S&P MA (Stooq) failed: {e}")
        return {"ma50": None, "ma200": None, "death_cross": None}


def fetch_credit_spreads():
    """FRED public CSV endpoint — no API key required."""
    series = {
        "hy_spread": "BAMLH0A0HYM2",   # ICE BofA US High Yield OAS
        "ig_spread": "BAMLC0A4CBBB",   # ICE BofA BBB Corp OAS
    }
    results = {}
    for name, sid in series.items():
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("DATE")]
            # Get last two valid rows
            valid = []
            for line in reversed(lines):
                parts = line.split(",")
                if len(parts) == 2 and parts[1].strip() not in (".", ""):
                    valid.append((parts[0].strip(), float(parts[1].strip())))
                if len(valid) == 2:
                    break
            if valid:
                latest_date, latest_val = valid[0]
                prev_val = valid[1][1] if len(valid) > 1 else latest_val
                results[name] = {
                    "value":      round(latest_val * 100, 0),   # convert to bps
                    "prev":       round(prev_val * 100, 0),
                    "date":       latest_date,
                    "change_bps": round((latest_val - prev_val) * 100, 1),
                }
            else:
                results[name] = {"value": None, "prev": None, "date": None, "change_bps": None}
        except Exception as e:
            print(f"[WARN] FRED {sid} failed: {e}")
            results[name] = {"value": None, "prev": None, "date": None, "change_bps": None}
    return results


def load_static_content():
    """Load editorial sections from static_content.json."""
    path = Path(__file__).parent / "static_content.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ─── DELTA HELPER ─────────────────────────────────────────────

def delta_html(val, reverse=False):
    """Return a coloured delta arrow string. reverse=True means up is bad."""
    if val is None:
        return ""
    if val > 0.1:
        color = "#ff4444" if reverse else "#22c55e"
        return f'<span style="color:{color};font-weight:700">▲ {val:+.2f}%</span>'
    elif val < -0.1:
        color = "#22c55e" if reverse else "#ff4444"
        return f'<span style="color:{color};font-weight:700">▼ {val:+.2f}%</span>'
    else:
        return f'<span style="color:#94a3b8;font-weight:700">= {val:+.2f}%</span>'


def bps_delta_html(bps, reverse=True):
    if bps is None:
        return ""
    if bps > 0:
        color = "#ff4444" if reverse else "#22c55e"
        return f'<span style="color:{color};font-weight:700">▲ +{bps:.0f} bps</span>'
    elif bps < 0:
        color = "#22c55e" if reverse else "#ff4444"
        return f'<span style="color:{color};font-weight:700">▼ {bps:.0f} bps</span>'
    else:
        return f'<span style="color:#94a3b8;font-weight:700">= 0 bps</span>'


def fmt_price(val, prefix="", decimals=2):
    if val is None:
        return "—"
    if val >= 1000:
        return f"{prefix}{val:,.0f}"
    return f"{prefix}{val:,.{decimals}f}"


# ─── HTML GENERATOR ───────────────────────────────────────────

def generate_html(crypto, fear_greed, indices, sp_ma, spreads, static):
    now_utc = datetime.now(timezone.utc)
    # Sydney = UTC+11 (AEDT) or UTC+10 (AEST); approximate
    sydney_offset = timedelta(hours=11)
    now_sydney = now_utc + sydney_offset
    updated_str = now_sydney.strftime("%a %d %b %Y %H:%M AEDT")
    briefing_date = static.get("briefing_date", "Unknown")
    master_verdict = static.get("master_verdict", "CAUTION")
    verdict_color = {"DANGER": "#ff4444", "CAUTION": "#f59e0b", "CLEAR": "#22c55e", "WAIT": "#6366f1"}.get(master_verdict, "#f59e0b")

    # S&P 500
    spx = indices.get("SPX", {})
    spx_price = fmt_price(spx.get("price"), "$")
    spx_delta = delta_html(spx.get("change_pct"))
    dc = sp_ma.get("death_cross")
    dc_label = "⚠ Death Cross Active" if dc else ("✓ No Death Cross" if dc is not None else "—")
    dc_color = "#ff4444" if dc else "#22c55e"

    # VIX
    vix = indices.get("VIX", {})
    vix_val = fmt_price(vix.get("price"), decimals=1)
    vix_delta = delta_html(vix.get("change_pct"), reverse=True)
    vix_level = "DANGER" if (vix.get("price") or 0) > 30 else ("CAUTION" if (vix.get("price") or 0) > 20 else "CLEAR")

    # Oil
    oil = indices.get("OIL", {})
    oil_price = fmt_price(oil.get("price"), "$")
    oil_delta = delta_html(oil.get("change_pct"), reverse=True)

    # Gold
    gold = indices.get("GOLD", {})
    gold_price = fmt_price(gold.get("price"), "$")
    gold_delta = delta_html(gold.get("change_pct"))

    # AUDUSD
    aud = indices.get("AUDUSD", {})
    aud_price = fmt_price(aud.get("price"), decimals=4)
    aud_delta = delta_html(aud.get("change_pct"))

    # 10Y
    tnx = indices.get("TNX", {})
    tnx_price = f"{tnx.get('price', '—')}%" if tnx.get("price") else "—"
    tnx_delta = delta_html(tnx.get("change_pct"), reverse=True)

    # Spreads
    hy = spreads.get("hy_spread", {})
    ig = spreads.get("ig_spread", {})
    hy_val = f"{hy.get('value', '—'):.0f} bps" if hy.get("value") else "—"
    ig_val = f"{ig.get('value', '—'):.0f} bps" if ig.get("value") else "—"
    hy_delta = bps_delta_html(hy.get("change_bps"))
    ig_delta = bps_delta_html(ig.get("change_bps"))
    hy_date = f"FRED data: {hy.get('date', 'N/A')}"
    ig_date = f"FRED data: {ig.get('date', 'N/A')}"

    # Fear & Greed
    fg_val = fear_greed.get("value", 0)
    fg_label = fear_greed.get("label", "Unknown")
    fg_color = "#ff4444" if fg_val < 30 else ("#f59e0b" if fg_val < 50 else "#22c55e")
    fg_emoji = "😱" if fg_val < 25 else ("😨" if fg_val < 40 else ("😐" if fg_val < 55 else ("😊" if fg_val < 75 else "🤩")))

    # Crypto rows
    crypto_rows = ""
    if crypto:
        sym_styles = {"BTC": "#f7931a", "ETH": "#627eea", "XRP": "#00aae4", "SOL": "#9945ff"}
        sym_signals = static.get("crypto_signals", {})
        for sym, c in crypto.items():
            color = sym_styles.get(sym, "#fff")
            sig = sym_signals.get(sym, "—")
            p24 = delta_html(c.get("change_24h"))
            p7 = delta_html(c.get("change_7d"))
            price_str = f"${c['price']:,.0f}" if c['price'] > 100 else f"${c['price']:,.4f}"
            crypto_rows += f"""
            <tr>
              <td><span style="font-weight:700;color:{color};font-size:15px">{sym}</span></td>
              <td><strong>{price_str}</strong></td>
              <td>{p24}</td>
              <td>{p7}</td>
              <td style="color:#8892a4;font-size:12px">{sig}</td>
            </tr>"""

    # Editorial sections from JSON
    sections_html = ""
    for section in static.get("sections", []):
        verdict = section.get("verdict", "CAUTION")
        v_color = {"DANGER": "#ff4444", "CAUTION": "#f59e0b", "CLEAR": "#22c55e", "WAIT": "#a5b4fc", "ACCELERATING": "#22c55e", "FEAR": "#ff4444"}.get(verdict, "#f59e0b")
        items_html = ""
        for item in section.get("items", []):
            status = item.get("status", "caution")
            dot_color = {"danger": "#ff4444", "caution": "#f59e0b", "clear": "#22c55e"}.get(status, "#f59e0b")
            delta_icon = {"up": "▲", "down": "▼", "flat": "="}.get(item.get("delta", "flat"), "=")
            delta_c = {"up": "#22c55e", "down": "#ff4444", "flat": "#94a3b8"}.get(item.get("delta", "flat"), "#94a3b8")
            items_html += f"""
            <div class="edit-card {status}">
              <div class="glow-dot" style="background:{dot_color};box-shadow:0 0 8px {dot_color}"></div>
              <div class="card-label">{item.get('label','')}</div>
              <div class="card-value" style="color:{dot_color}">{item.get('value','')}</div>
              <div class="card-sub"><span style="color:{delta_c};font-weight:700">{delta_icon}</span> {item.get('sub','')}</div>
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

    # Checklist
    checklist_html = ""
    for item in static.get("checklist", []):
        state = item.get("state", "open")
        cls = {"done": "done", "partial": "partial", "open": "open"}.get(state, "open")
        icon = {"done": "✓", "partial": "◐", "open": "☐"}.get(state, "☐")
        checklist_html += f'<div class="check-item {cls}"><span class="check-icon">{icon}</span>{item.get("text","")}</div>'

    # Master verdict colour
    mv_bg = {"DANGER": "linear-gradient(135deg,#1a0a0a,#2a1010)", "CAUTION": "linear-gradient(135deg,#1a1400,#2a2000)", "CLEAR": "linear-gradient(135deg,#0a1a0a,#102a10)"}.get(master_verdict, "linear-gradient(135deg,#0d0f14,#141720)")

    # Summary table rows (built outside f-string to avoid nested dict issues)
    verdict_colors = {"DANGER":"#ff4444","CAUTION":"#f59e0b","CLEAR":"#22c55e","WAIT":"#a5b4fc","ACCELERATING":"#22c55e","FEAR":"#ff4444"}
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
<title>Intel Briefing · {updated_str}</title>
<style>
  :root{{--bg:#0d0f14;--card:#141720;--card2:#1a1f2e;--border:#252a3a;--text:#e2e8f0;--muted:#8892a4;--danger:#ff4444;--danger-glow:rgba(255,68,68,.25);--caution:#f59e0b;--caution-glow:rgba(245,158,11,.25);--clear:#22c55e;--clear-glow:rgba(34,197,94,.25);--accent:#6366f1}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.5}}
  .container{{max-width:1280px;margin:0 auto;padding:24px 16px}}
  .master-banner{{background:{mv_bg};border:2px solid {verdict_color};border-radius:12px;padding:20px 28px;margin-bottom:24px;box-shadow:0 0 30px rgba({",".join(str(int(verdict_color.lstrip("#")[i:i+2],16)) for i in (0,2,4))},.3);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}}
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
</style>
</head>
<body>
<div class="container">

  <!-- MASTER BANNER -->
  <div class="master-banner">
    <div>
      <h1>⚡ Weekly Intelligence Briefing</h1>
      <div class="meta">Gabe Enslin · Market data updated: {updated_str} &nbsp;<span class="live-badge">● LIVE</span></div>
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
      <span class="live-badge">● AUTO-UPDATES DAILY</span>
    </div>
    <div class="live-grid">
      <div class="live-card">
        <div class="live-card-label">S&amp;P 500</div>
        <div class="live-card-value">{spx_price}</div>
        <div class="live-card-sub">{spx_delta}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">VIX (Fear Index)</div>
        <div class="live-card-value" style="color:{'#ff4444' if vix_level=='DANGER' else ('#f59e0b' if vix_level=='CAUTION' else '#22c55e')}">{vix_val}</div>
        <div class="live-card-sub">{vix_delta}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Death Cross (50d/200d)</div>
        <div class="live-card-value" style="font-size:14px;color:{dc_color}">{dc_label}</div>
        <div class="live-card-sub">50d: {sp_ma.get("ma50","—")} · 200d: {sp_ma.get("ma200","—")}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">HY Credit Spreads</div>
        <div class="live-card-value" style="color:#ff4444">{hy_val}</div>
        <div class="live-card-sub">{hy_delta} · <span style="font-size:11px">{hy_date}</span></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">IG Credit Spreads</div>
        <div class="live-card-value" style="color:#f59e0b">{ig_val}</div>
        <div class="live-card-sub">{ig_delta} · <span style="font-size:11px">{ig_date}</span></div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Fear &amp; Greed Index</div>
        <div class="live-card-value" style="color:{fg_color}">{fg_emoji} {fg_val}</div>
        <div class="live-card-sub">{fg_label}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Oil (WTI)</div>
        <div class="live-card-value">{oil_price}</div>
        <div class="live-card-sub">{oil_delta}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">Gold</div>
        <div class="live-card-value">{gold_price}</div>
        <div class="live-card-sub">{gold_delta}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">AUD/USD</div>
        <div class="live-card-value">{aud_price}</div>
        <div class="live-card-sub">{aud_delta}</div>
      </div>
      <div class="live-card">
        <div class="live-card-label">US 10Y Yield</div>
        <div class="live-card-value">{tnx_price}</div>
        <div class="live-card-sub">{tnx_delta}</div>
      </div>
    </div>
  </div>

  <!-- LIVE CRYPTO -->
  <div class="section-header">
    <span class="section-num">CRYPTO</span>
    <h2>Crypto</h2>
    <span class="live-badge" style="font-size:11px;background:rgba(34,197,94,.15);color:#22c55e;border:1px solid #22c55e;border-radius:4px;padding:2px 8px;font-weight:700">● LIVE PRICES</span>
    <span style="font-size:11px;color:#8892a4;margin-left:auto">F&amp;G: {fg_val} — {fg_label} {fg_emoji}</span>
  </div>
  <div class="crypto-table-wrap">
    <table>
      <thead><tr><th>Symbol</th><th>Price (USD)</th><th>24h</th><th>7d</th><th>Signal (weekly)</th></tr></thead>
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
    Market data: Yahoo Finance · CoinGecko · FRED (St. Louis Fed) · Alternative.me &nbsp;|&nbsp; Editorial: weekly research by Claude &nbsp;|&nbsp; Auto-refreshes daily via GitHub Actions &nbsp;|&nbsp; Not financial advice.
  </footer>

</div>
</body>
</html>"""


# ─── MAIN ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("📡 Fetching live data...")

    print("  → Crypto (CoinGecko)...")
    crypto = fetch_crypto()

    print("  → Fear & Greed (alternative.me)...")
    fear_greed = fetch_fear_greed()

    print("  → Market indices (Yahoo Finance)...")
    indices = fetch_market_indices()

    print("  → S&P 500 moving averages...")
    sp_ma = fetch_sp500_ma()

    print("  → Credit spreads (FRED)...")
    spreads = fetch_credit_spreads()

    print("  → Loading editorial content...")
    static = load_static_content()

    print("  → Generating HTML...")
    html = generate_html(crypto, fear_greed, indices, sp_ma, spreads, static)

    out_path = Path(__file__).parent / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ Done → {out_path}")
    print(f"   SPX: {indices.get('SPX',{}).get('price','—')}")
    print(f"   BTC: {crypto.get('BTC',{}).get('price','—') if crypto else '—'}")
    print(f"   F&G: {fear_greed.get('value','—')} ({fear_greed.get('label','—')})")
    print(f"   HY:  {spreads.get('hy_spread',{}).get('value','—')} bps")
