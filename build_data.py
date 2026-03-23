from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import snowflake.connector
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "dashboard-data.json"
QUERY_CACHE_PATH = DATA_DIR / "allium-queries.json"
TEMPLATE_PATH = ROOT / "index.template.html"
ROOT_INDEX_PATH = ROOT / "index.html"
DIST_DIR = ROOT / "dist"
LOOKBACK_DAYS = 180

ALLIUM_API_BASE = "https://api.allium.so/api/v1/explorer"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


ALLIUM_OVERVIEW_SQL = f"""
select
  activity_date,
  token_price_usd,
  hip3_volume_usd,
  hip3_trading_fees_usd,
  perpetual_volume_usd,
  perpetual_trading_fees_usd,
  spot_volume_usd,
  spot_trading_fees_usd
from hyperliquid.metrics.overview
where activity_date >= current_date - interval '{LOOKBACK_DAYS} days'
  and activity_date < current_date
order by activity_date asc
"""


ALLIUM_HIP3_MARKET_LATEST_SQL = """
with market_daily as (
  select
    cast(date_trunc('day', timestamp) as date) as activity_date,
    perp_dex as dex_name,
    coalesce(token_a_symbol, coin, perp_market_name) as market_symbol,
    sum(usd_amount) as volume_usd,
    sum(coalesce(buyer_fee, 0) + coalesce(seller_fee, 0)) as trading_fees_usd
  from hyperliquid.dex.trades
  where is_hip3 = true
    and timestamp >= current_date - interval '30 days'
  group by 1, 2, 3
)
select *
from market_daily
qualify row_number() over (
  partition by dex_name, market_symbol
  order by activity_date desc
) = 1
"""


ARTEMIS_TOTALS_SQL = f"""
select
  date,
  revenue,
  buybacks,
  buybacks_native
from ART_SHARE.HYPERLIQUID.EZ_METRICS
where date >= '{(date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()}'
order by date asc
"""


@dataclass
class Hip3TokenMeta:
    token: str
    dex: str
    display_name: str
    growth_enabled_now: bool
    growth_change_date: date | None

    def growth_active_on(self, day: date) -> bool:
        if self.growth_enabled_now:
            return self.growth_change_date is None or day >= self.growth_change_date
        if self.growth_change_date is not None:
            return day < self.growth_change_date
        return False


class AlliumClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            }
        )
        self.cache = self._load_cache()

    def _load_cache(self) -> dict[str, Any]:
        if QUERY_CACHE_PATH.exists():
            return json.loads(QUERY_CACHE_PATH.read_text(encoding="utf-8"))
        return {}

    def _save_cache(self) -> None:
        QUERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUERY_CACHE_PATH.write_text(json.dumps(self.cache, indent=2), encoding="utf-8")

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(method, f"{ALLIUM_API_BASE}{path}", timeout=60, **kwargs)
        response.raise_for_status()
        return response

    def ensure_query(self, title: str, sql: str, limit: int) -> str:
        sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        cached = self.cache.get(title)

        if cached and cached.get("sql_hash") == sql_hash and cached.get("query_id"):
            return cached["query_id"]

        if cached and cached.get("query_id"):
            payload = {
                "config": {
                    "sql": sql,
                    "limit": limit,
                }
            }
            self._request("PUT", f"/queries/{cached['query_id']}", json=payload)
            query_id = cached["query_id"]
        else:
            payload = {
                "title": title,
                "config": {
                    "sql": sql,
                    "limit": limit,
                },
            }
            response = self._request("POST", "/queries", json=payload).json()
            query_id = response.get("query_id") or response.get("id")
            if not query_id:
                raise RuntimeError(f"Unexpected create query response for {title}: {response}")

        self.cache[title] = {"query_id": query_id, "sql_hash": sql_hash}
        self._save_cache()
        return query_id

    def run_query(self, query_id: str) -> list[dict[str, Any]]:
        run_response = self._request(
            "POST",
            f"/queries/{query_id}/run-async",
            json={"parameters": {}, "run_config": {}},
        ).json()
        run_id = run_response["run_id"]

        status = "created"
        for _ in range(180):
            status_response = self._request("GET", f"/query-runs/{run_id}/status").json()
            status = status_response if isinstance(status_response, str) else status_response.get("status")
            if status == "success":
                break
            if status in {"failed", "canceled"}:
                raise RuntimeError(f"Allium query run {run_id} ended with status {status}")
            time.sleep(2)
        else:
            raise TimeoutError(f"Timed out waiting for Allium query run {run_id}")

        result = self._request("GET", f"/query-runs/{run_id}/results").json()
        data = result.get("data")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected results payload for run {run_id}: {result}")
        return data


def fetch_json(payload: dict[str, Any]) -> Any:
    response = requests.post(HYPERLIQUID_INFO_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def connect_snowflake():
    env = dotenv_values("/Users/mattmaximo/Code/.env.global")
    return snowflake.connector.connect(
        user=env["SNOWFLAKE_USER"],
        password=env["SNOWFLAKE_PASSWORD"],
        account=env["SNOWFLAKE_ACCOUNT"],
        warehouse=env["SNOWFLAKE_WAREHOUSE"],
        database=env["SNOWFLAKE_DATABASE"],
        role=env["SNOWFLAKE_ROLE"],
    )


def parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return datetime.strptime(text, "%Y-%m-%d").date()


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, float) and math.isnan(value):
        return 0.0
    return float(value)


def rows_to_dicts(cursor) -> list[dict[str, Any]]:
    columns = [description[0].lower() for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_artemis_totals(conn) -> list[dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(ARTEMIS_TOTALS_SQL)
        return rows_to_dicts(cur)
    finally:
        cur.close()


def load_category_metrics(conn) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    sql = f"""
        select
            date,
            category,
            perp_fees,
            perp_volume
        from ART_SHARE.HYPERLIQUID.EZ_METRICS_BY_CATEGORY
        where date >= '{cutoff.isoformat()}'
          and perp_volume is not null
        order by date asc, category asc
    """
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return rows_to_dicts(cur)
    finally:
        cur.close()


def load_token_metrics(conn) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    sql = f"""
        select
            date,
            token,
            perp_volume,
            open_interest
        from ART_SHARE.HYPERLIQUID.EZ_METRICS_BY_TOKEN
        where date >= '{cutoff.isoformat()}'
          and token like '%:%'
          and perp_volume is not null
        order by date asc, token asc
    """
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return rows_to_dicts(cur)
    finally:
        cur.close()


def build_hip3_metadata() -> dict[str, Hip3TokenMeta]:
    dexes = fetch_json({"type": "perpDexs"})
    metas = fetch_json({"type": "allPerpMetas"})

    hip3_tokens: dict[str, Hip3TokenMeta] = {}
    for index, meta in enumerate(metas):
        dex_info = dexes[index] if index < len(dexes) else None
        if not dex_info:
            continue
        dex_name = dex_info["name"]
        for asset in meta.get("universe", []):
            token = asset["name"]
            if ":" not in token:
                continue
            symbol = token.split(":", 1)[1]
            hip3_tokens[token] = Hip3TokenMeta(
                token=token,
                dex=dex_name,
                display_name=symbol,
                growth_enabled_now=asset.get("growthMode") == "enabled",
                growth_change_date=parse_iso_date(asset.get("lastGrowthModeChangeTime")),
            )
    return hip3_tokens


def load_allium_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    api_key = os.environ.get("ALLIUM_API_KEY")
    if not api_key:
        raise RuntimeError("Set ALLIUM_API_KEY before running build_data.py")

    client = AlliumClient(api_key)
    overview_query_id = client.ensure_query(
        "hype-dash allium hyperliquid overview",
        ALLIUM_OVERVIEW_SQL,
        limit=5000,
    )
    market_query_id = client.ensure_query(
        "hype-dash allium hyperliquid hip3 market latest",
        ALLIUM_HIP3_MARKET_LATEST_SQL,
        limit=5000,
    )

    return client.run_query(overview_query_id), client.run_query(market_query_id)


def build_dataset() -> dict[str, Any]:
    allium_overview_rows, allium_latest_market_rows = load_allium_data()
    with connect_snowflake() as conn:
        artemis_totals = load_artemis_totals(conn)
        category_metrics = load_category_metrics(conn)
        token_metrics = load_token_metrics(conn)

    hip3_meta = build_hip3_metadata()

    artemis_totals_by_day = {
        parse_date(row["date"]): {
            "total_revenue_actual": num(row["revenue"]),
            "total_burn_actual": num(row["buybacks"]),
            "total_burn_actual_hype": num(row["buybacks_native"]),
        }
        for row in artemis_totals
    }

    daily_by_day: dict[date, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []

    for row in allium_overview_rows:
        day = parse_date(row["activity_date"])
        totals = artemis_totals_by_day.get(
            day,
            {
                "total_revenue_actual": 0.0,
                "total_burn_actual": 0.0,
                "total_burn_actual_hype": 0.0,
            },
        )
        hip3_actual_fees = num(row["hip3_trading_fees_usd"])
        core_actual_fees = (
            num(row["perpetual_trading_fees_usd"])
            - hip3_actual_fees
            + num(row["spot_trading_fees_usd"])
        )
        daily_by_day[day] = {
            "date": day.isoformat(),
            "hype_price": num(row["token_price_usd"]),
            "regular_actual_fees": core_actual_fees,
            "regular_actual_volume": (
                num(row["perpetual_volume_usd"]) - num(row["hip3_volume_usd"]) + num(row["spot_volume_usd"])
            ),
            "hip3_actual_fees": hip3_actual_fees,
            "hip3_actual_volume": num(row["hip3_volume_usd"]),
            **totals,
        }

    category_fee_by_day: dict[tuple[date, str], float] = {}
    for row in category_metrics:
        day = parse_date(row["date"])
        category_fee_by_day[(day, row["category"])] = num(row["perp_fees"])

    token_volume_by_day_category: dict[tuple[date, str], list[dict[str, Any]]] = {}
    for row in token_metrics:
        token = row["token"]
        meta = hip3_meta.get(token)
        if not meta:
            continue
        day = parse_date(row["date"])
        category = meta.display_name
        token_volume_by_day_category.setdefault((day, category), []).append(
            {
                "token": token,
                "dex": meta.dex,
                "volume": num(row["perp_volume"]),
                "open_interest": num(row["open_interest"]),
                "growth_active": meta.growth_active_on(day),
            }
        )

    for day, daily_row in daily_by_day.items():
        category_actual_total = 0.0
        category_full_total = 0.0
        for (group_day, category), tokens in token_volume_by_day_category.items():
            if group_day != day:
                continue
            category_fee = category_fee_by_day.get((group_day, category), 0.0)
            total_volume = sum(item["volume"] for item in tokens)
            if category_fee <= 0 or total_volume <= 0:
                continue
            weighted_full_volume = sum(item["volume"] * (10.0 if item["growth_active"] else 1.0) for item in tokens)
            multiplier = weighted_full_volume / total_volume if total_volume else 1.0
            category_actual_total += category_fee
            category_full_total += category_fee * multiplier

        multiplier = category_full_total / category_actual_total if category_actual_total else 1.0
        official_actual = daily_row["hip3_actual_fees"]
        hip3_full_fee_est = official_actual * multiplier
        daily_row["hip3_full_fee_est"] = hip3_full_fee_est
        daily_row["hip3_full_fee_uplift_est"] = hip3_full_fee_est - official_actual
        daily_row["category_fee_coverage_ratio"] = category_actual_total / official_actual if official_actual else 1.0
        diagnostics.append(
            {
                "date": daily_row["date"],
                "official_hip3_actual_fees": official_actual,
                "category_fee_sum": category_actual_total,
                "category_fee_coverage_ratio": daily_row["category_fee_coverage_ratio"],
                "full_fee_multiplier": multiplier,
            }
        )

    latest_day = max(daily_by_day)
    latest_market_rows = []
    for row in allium_latest_market_rows:
        day = parse_date(row["activity_date"])
        dex_name = row["dex_name"]
        symbol = row["market_symbol"]
        token = f"{dex_name}:{symbol}"
        meta = hip3_meta.get(token)
        growth_active = meta.growth_active_on(day) if meta else False
        actual_fee = num(row["trading_fees_usd"])
        full_fee = actual_fee * (10.0 if growth_active else 1.0)
        latest_market_rows.append(
            {
                "token": token,
                "display_name": symbol,
                "dex": dex_name,
                "activity_date": day.isoformat(),
                "growth_active": growth_active,
                "volume": num(row["volume_usd"]),
                "actual_fee_est": actual_fee,
                "full_fee_est": full_fee,
                "uplift_est": full_fee - actual_fee,
            }
        )

    latest_market_rows.sort(key=lambda item: item["uplift_est"], reverse=True)

    growth_markets = sorted(
        [
            {
                "token": meta.token,
                "display_name": meta.display_name,
                "dex": meta.dex,
                "growth_enabled_now": meta.growth_enabled_now,
                "growth_change_date": meta.growth_change_date.isoformat() if meta.growth_change_date else None,
            }
            for meta in hip3_meta.values()
        ],
        key=lambda item: (
            not item["growth_enabled_now"],
            item["dex"],
            item["display_name"],
        ),
    )

    methodology = {
        "exact_fields": [
            "regular_actual_fees",
            "hip3_actual_fees",
            "regular_actual_volume",
            "hip3_actual_volume",
        ],
        "estimated_fields": [
            "regular_revenue_split",
            "hip3_revenue_split",
            "regular_burn_split",
            "hip3_burn_split",
            "hip3_full_fee_est",
        ],
        "notes": [
            "Core Hyperliquid and HIP3 daily fees and volumes now come from Allium Hyperliquid metrics.",
            "The latest HIP3 market table now comes from exact Allium Hyperliquid trade data grouped by DEX and market.",
            "Current HIP3 market growth-mode status still comes from the public Hyperliquid info endpoint.",
            "The full-fees toggle scales HIP3 market fees by 10x on growth-mode markets, matching Hyperliquid's documented 90% growth-mode discount.",
            "The historical full-fee time series still uses the lighter category-and-volume share model because a full Allium trade-level market history query is operationally too slow for this dashboard build.",
            "Allium does not publish daily protocol revenue or Assistance Fund burn totals, so those totals still come from Artemis and are allocated between core Hyperliquid and HIP3 by that day's fee mix.",
        ],
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": LOOKBACK_DAYS,
        "latest_date": latest_day.isoformat(),
        "methodology": methodology,
        "days": [daily_by_day[day] for day in sorted(daily_by_day)],
        "latest_market_rows": latest_market_rows,
        "growth_markets": growth_markets,
        "diagnostics": diagnostics,
    }


def write_static_site(payload: dict[str, Any]) -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    embedded_json = json.dumps(payload, separators=(",", ":"))
    rendered = template.replace("__DASHBOARD_DATA__", embedded_json)

    ROOT_INDEX_PATH.write_text(rendered, encoding="utf-8")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    (DIST_DIR / "index.html").write_text(rendered, encoding="utf-8")
    shutil.copy2(ROOT / "app.js", DIST_DIR / "app.js")
    shutil.copy2(ROOT / "styles.css", DIST_DIR / "styles.css")
    shutil.copytree(ROOT / "vendor", DIST_DIR / "vendor", dirs_exist_ok=True)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_dataset()
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_static_site(payload)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
