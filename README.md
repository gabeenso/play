# Intel Briefing — gabeenso/play

Daily auto-updating market intelligence dashboard. Fetches live data each morning and publishes to GitHub Pages.

**Live URL (once set up):** https://gabeenso.github.io/play

---

## One-time setup (5 minutes)

### 1. Push this folder to your repo

```bash
cd intel-briefing-site
git init
git remote add origin https://github.com/gabeenso/play.git
git add .
git commit -m "initial: intel briefing site"
git push -u origin main
```

### 2. Enable GitHub Pages

1. Go to https://github.com/gabeenso/play/settings/pages
2. Under **Source**, select **Deploy from a branch**
3. Branch: `main` · Folder: `/ (root)`
4. Click **Save**

Your URL will be: `https://gabeenso.github.io/play`

### 3. That's it

GitHub Actions will run every day at ~9am Sydney and regenerate `index.html` with fresh market data. Share the URL with friends.

---

## Manual trigger

Go to: https://github.com/gabeenso/play/actions → **Daily Briefing Update** → **Run workflow**

---

## Weekly editorial update

When the weekly briefing runs, update `static_content.json` with new research and push to main. The next daily run will pick it up.

---

## Live data sources (all free, no API keys)

| Data | Source |
|------|--------|
| S&P 500, VIX, Oil, Gold, AUD/USD, 10Y | Yahoo Finance (yfinance) |
| BTC, ETH, XRP, SOL prices + 7d change | CoinGecko public API |
| Fear & Greed Index | alternative.me |
| HY + IG credit spreads | FRED (St. Louis Fed) |

---

## Roadmap

- [ ] Real-time page (Vercel + serverless function)
- [ ] Push notifications for trigger conditions
- [ ] Automated weekly editorial update via Claude
