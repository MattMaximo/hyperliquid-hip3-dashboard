# Hyperliquid HIP3 Dashboard

Static dashboard for tracking:
- daily Hyperliquid core vs HIP3 fees
- estimated revenue and burn split
- HIP3 full-fee counterfactual
- current HIP3 market table with sortable sticky headers

## Refresh

Run:

```bash
cd /Users/mattmaximo/Code/hype-dash
ALLIUM_API_KEY=... .venv/bin/python build_data.py
```

That regenerates the embedded static site and the deployable `dist/` output.
