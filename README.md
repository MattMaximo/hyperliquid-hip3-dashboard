# Hyperliquid HIP3 Dashboard

Static dashboard for tracking:
- daily Hyperliquid core vs HIP3 fees
- estimated revenue and burn split
- HIP3 full-fee counterfactual
- current HIP3 market table with sortable sticky headers
- chart aggregation controls for `D / W / M / Y`

## Repo Use

This repo is meant to be usable by multiple Codex sessions.

- UI-only changes:
  - edit `index.template.html`, `app.js`, or `styles.css`
  - rebuild the embedded static site with:

```bash
cd /Users/mattmaximo/Code/hype-dash
.venv/bin/python build_static.py
```

- Data refreshes:
  - rerun the Allium / Artemis build with:

```bash
cd /Users/mattmaximo/Code/hype-dash
ALLIUM_API_KEY=... .venv/bin/python build_data.py
```

## Publish

Push `main` and GitHub Pages serves the static root:

```bash
git -C /Users/mattmaximo/Code/hype-dash push origin main
```

Live site:
- `https://mattmaximo.github.io/hyperliquid-hip3-dashboard/`

## Files

- `index.template.html`: editable template
- `index.html`: generated static page with embedded data
- `build_data.py`: refresh data and regenerate the static site
- `build_static.py`: regenerate the static site from existing local data
- `data/dashboard-data.json`: latest local dataset snapshot
