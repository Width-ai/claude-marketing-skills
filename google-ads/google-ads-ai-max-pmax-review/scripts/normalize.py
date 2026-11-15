#!/usr/bin/env python3
"""Normalize Google Ads data into clean, standard CSVs.

Accepts any mix of:
  - connector output as JSON (GAQL rows, nested or dotted, camelCase or snake_case,
    including searchStream chunks with a "results" list)
  - CSVs whose headers are GAQL field names (campaign.name, metrics.cost_micros, ...)
  - Google Ads UI report downloads (title and date rows above the header, Total rows)
  - Google Ads Editor exports (UTF-16, tab-separated)

Writes one CSV with standard column names, money in currency units (micros
divided by 1,000,000), shares as fractions, statuses and match types in lower
case, an is_negative flag for negative keywords, and no Total rows. Reported
ratios (CTR, CPC, CPA, ROAS, conversion rate) are dropped so they get
recomputed from sums by metrics.py. Use --keep-ratios to keep them as
reported_<name>.

Usage:
  python3 normalize.py INPUT [INPUT ...] --out OUT.csv
         [--group-by col1,col2] [--keep-ratios]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

# Standard column name -> aliases (lower case). GAQL names use snake_case dotted paths.
ALIASES: dict[str, list[str]] = {
    "customer_id": ["customer.id", "customer id", "account id", "customer_client.id"],
    "account": ["customer.descriptive_name", "account", "account name", "customer_client.descriptive_name"],
    "currency": ["customer.currency_code", "currency code", "currency", "customer_client.currency_code"],
    "time_zone": ["customer.time_zone", "time zone", "customer_client.time_zone"],
    "campaign_id": ["campaign.id", "campaign id"],
    "campaign": ["campaign.name", "campaign", "campaign name"],
    "campaign_status": ["campaign.status", "campaign status", "campaign state"],
    "campaign_type": ["campaign.advertising_channel_type", "campaign type", "advertising channel type"],
    "bid_strategy_type": ["campaign.bidding_strategy_type", "bid strategy type", "campaign bid strategy type", "bidding strategy type"],
    "budget": ["campaign_budget.amount", "budget", "campaign daily budget", "daily budget", "budget amount"],
    "budget_shared": ["campaign_budget.explicitly_shared"],
    "ad_group_id": ["ad_group.id", "ad group id"],
    "ad_group": ["ad_group.name", "ad group", "ad group name"],
    "ad_group_status": ["ad_group.status", "ad group status", "ad group state"],
    "keyword_id": ["ad_group_criterion.criterion_id", "keyword id", "criterion id"],
    "keyword": [
        "ad_group_criterion.keyword.text", "campaign_criterion.keyword.text",
        "shared_criterion.keyword.text", "keyword", "search keyword", "keyword text",
        "negative keyword",
    ],
    "match_type": [
        "ad_group_criterion.keyword.match_type", "campaign_criterion.keyword.match_type",
        "shared_criterion.keyword.match_type", "match type", "keyword match type",
        "search keyword match type", "criterion type",
    ],
    "keyword_status": ["ad_group_criterion.status", "keyword status", "keyword state"],
    "is_negative": ["ad_group_criterion.negative", "campaign_criterion.negative", "negative"],
    "max_cpc": ["ad_group_criterion.cpc_bid", "max. cpc", "max cpc", "max cpc bid", "default max. cpc"],
    "quality_score": ["ad_group_criterion.quality_info.quality_score", "quality score", "qual. score"],
    "shared_set": ["shared_set.name", "shared set", "negative keyword list", "list name"],
    "search_term": ["search_term_view.search_term", "search term", "search query"],
    "search_term_status": ["search_term_view.status", "added/excluded", "added / excluded"],
    "search_term_match_type": ["segments.search_term_match_type"],
    "date": ["segments.date", "day", "date"],
    "week": ["segments.week", "week"],
    "month": ["segments.month", "month"],
    "device": ["segments.device", "device"],
    "network": ["segments.ad_network_type", "network", "network (with search partners)"],
    "conversion_action": ["segments.conversion_action_name", "conversion action", "conversion_action.name"],
    "conversion_action_category": ["segments.conversion_action_category", "conversion category", "conversion_action.category"],
    "impressions": ["metrics.impressions", "impr.", "impressions", "impr"],
    "clicks": ["metrics.clicks", "clicks"],
    "interactions": ["metrics.interactions", "interactions"],
    "cost": ["metrics.cost", "cost"],
    "conversions": ["metrics.conversions", "conversions", "conv."],
    "conversion_value": ["metrics.conversions_value", "conv. value", "conversion value", "total conv. value"],
    "all_conversions": ["metrics.all_conversions", "all conv.", "all conversions"],
    "all_conversions_value": ["metrics.all_conversions_value", "all conv. value"],
    "view_through_conversions": ["metrics.view_through_conversions", "view-through conv."],
    "search_impression_share": ["metrics.search_impression_share", "search impr. share", "search impression share"],
    "search_budget_lost_is": [
        "metrics.search_budget_lost_impression_share", "search lost is (budget)",
        "search lost impr. share (budget)",
    ],
    "search_rank_lost_is": [
        "metrics.search_rank_lost_impression_share", "search lost is (rank)",
        "search lost impr. share (rank)",
    ],
    "search_top_is": ["metrics.search_top_impression_share", "search top is", "search top impr. share"],
    "search_abs_top_is": [
        "metrics.search_absolute_top_impression_share", "search abs. top is",
        "search abs. top impr. share",
    ],
    "ad_id": ["ad_group_ad.ad.id", "ad id"],
    "ad_type": ["ad_group_ad.ad.type", "ad type"],
    "ad_status": ["ad_group_ad.status", "ad status", "ad state"],
    "ad_strength": ["ad_group_ad.ad_strength", "ad strength"],
    "approval_status": ["ad_group_ad.policy_summary.approval_status", "approval status"],
    "final_url": ["ad_group_ad.ad.final_urls", "ad_group_criterion.final_urls", "final url", "final urls"],
    "landing_page": ["landing_page_view.unexpanded_final_url", "landing page"],
    "change_date_time": ["change_event.change_date_time", "date & time", "date and time"],
    "change_resource_type": ["change_event.change_resource_type"],
    "change_resource_name": ["change_event.change_resource_name"],
    "change_operation": ["change_event.resource_change_operation"],
    "client_type": ["change_event.client_type"],
    "user_email": ["change_event.user_email", "user"],
    "changed_fields": ["change_event.changed_fields"],
    "change_campaign": ["change_event.campaign"],
}

# Reported ratios: dropped by default so they are recomputed from sums.
RATIO_ALIASES: dict[str, list[str]] = {
    "ctr": ["metrics.ctr", "ctr"],
    "avg_cpc": ["metrics.average_cpc", "avg. cpc", "average cpc"],
    "avg_cpm": ["metrics.average_cpm", "avg. cpm"],
    "conversion_rate": ["metrics.conversions_from_interactions_rate", "conv. rate", "conversion rate"],
    "cost_per_conversion": ["metrics.cost_per_conversion", "cost / conv.", "cost per conversion"],
    "value_per_conversion": ["metrics.value_per_conversion", "conv. value / conv.", "value / conv."],
    "roas": ["conv. value / cost", "conversion value / cost", "roas"],
    "cost_per_all_conversion": ["metrics.cost_per_all_conversions", "cost / all conv."],
    "all_conversion_rate": ["metrics.all_conversions_from_interactions_rate", "all conv. rate"],
    "interaction_rate": ["metrics.interaction_rate", "interaction rate"],
}

MONEY = {"cost", "budget", "max_cpc", "conversion_value", "all_conversions_value"}
COUNTS = {"impressions", "clicks", "interactions", "conversions", "all_conversions", "view_through_conversions"}
ADDITIVE = COUNTS | {"cost", "conversion_value", "all_conversions_value"}
SHARES = {"search_impression_share", "search_budget_lost_is", "search_rank_lost_is", "search_top_is", "search_abs_top_is"}
LOWERCASE = {"campaign_status", "ad_group_status", "keyword_status", "ad_status", "search_term_status",
             "campaign_type", "bid_strategy_type", "device", "network", "approval_status", "ad_strength",
             "change_operation", "change_resource_type", "client_type", "search_term_match_type", "ad_type",
             "status"}
NULLS = {"", "--", " --", "-", "n/a", "null", "none", "unknown"}

LOOKUP: dict[str, str] = {}
for std, names in ALIASES.items():
    for name in names:
        LOOKUP[name] = std
RATIO_LOOKUP: dict[str, str] = {}
for std, names in RATIO_ALIASES.items():
    for name in names:
        RATIO_LOOKUP[name] = std

warnings: list[str] = []


def warn(message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def flatten(obj, prefix: str = "") -> dict:
    """Flatten nested dicts into dotted snake_case keys."""
    out: dict = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            key = ".".join(camel_to_snake(part) for part in str(key).split("."))
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                out.update(flatten(value, path))
            else:
                out[path] = value
    else:
        out[prefix or "value"] = obj
    return out


def list_to_text(value) -> str:
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return " ".join(str(v) for v in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    # UTF-16 without BOM shows up as many NUL bytes.
    if raw[:200].count(b"\x00") > 20:
        return raw.decode("utf-16-le")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def rows_from_json(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("results", "rows", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    rows: list[dict] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("results"), list) and len(item) <= 4:
            rows.extend(flatten(r) for r in item["results"])  # searchStream chunk
        else:
            rows.append(flatten(item))
    return [{k: list_to_text(v) for k, v in row.items()} for row in rows]


def known_header(cell: str) -> bool:
    c = cell.strip().lower()
    return c in LOOKUP or c in RATIO_LOOKUP or c.startswith(("metrics.", "segments.", "campaign.", "ad_group"))


def rows_from_csv(text: str) -> list[dict]:
    sample = "\n".join(text.splitlines()[:20])
    counts = {d: sample.count(d) for d in (",", "\t", ";")}
    delimiter = max(counts, key=counts.get)
    table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header_index = 0
    for i, row in enumerate(table[:15]):
        if sum(known_header(c) for c in row) >= 2:
            header_index = i
            break
    header = [h.strip() for h in table[header_index]]
    rows: list[dict] = []
    totals = 0
    for row in table[header_index + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        if any(cell.strip().lower().startswith("total") for cell in row[:4]):
            totals += 1
            continue
        rows.append({header[i]: (row[i] if i < len(row) else "") for i in range(len(header))})
    if totals:
        warn(f"dropped {totals} Total row(s)")
    return rows


def standard_name(column: str, has_search_term: bool) -> tuple[str, str]:
    """Return (kind, name) where kind is std, ratio, or other."""
    raw = column.strip()
    key = raw.lower()
    micros = False
    if key.endswith("_micros"):
        key = key[: -len("_micros")]
        micros = True
    if key == "match type" and has_search_term:
        return "std", "search_term_match_type"
    if key in LOOKUP:
        return ("std_micros" if micros else "std"), LOOKUP[key]
    if key in RATIO_LOOKUP:
        return "ratio", RATIO_LOOKUP[key]
    name = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    return ("other_micros" if micros else "other"), name


def parse_number(text: str):
    t = text.strip().replace(" ", "")
    if t.lower() in NULLS:
        return None, ""
    bound = ""
    if t.startswith("<"):
        bound, t = "lt", t[1:].strip()
    elif t.startswith(">"):
        bound, t = "gt", t[1:].strip()
    percent = t.endswith("%")
    t = t.rstrip("%")
    t = re.sub(r"[^\d.\-eE]", "", t.replace(",", ""))
    if t in ("", "-", "."):
        return None, ""
    try:
        value = float(t)
    except ValueError:
        return None, ""
    if percent:
        value /= 100
    return value, bound


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


MATCH_WORDS = {"exact": "exact", "phrase": "phrase", "broad": "broad"}


def parse_match(value: str) -> tuple[str, str]:
    """Return (match_type, negative_level) where negative_level is '', 'ad_group', or 'campaign'."""
    v = value.strip().lower().replace("_", " ")
    level = ""
    if v.startswith("campaign negative"):
        level, v = "campaign", v[len("campaign negative"):].strip()
    elif v.startswith("negative"):
        level, v = "ad_group", v[len("negative"):].strip()
    for word, std in MATCH_WORDS.items():
        if word in v:
            return std, level
    return v, level


def strip_keyword(text: str) -> tuple[str, str]:
    """Strip match-type punctuation. Returns (text, implied_match_type)."""
    t = text.strip()
    negative = t.startswith("-")
    if negative:
        t = t[1:].strip()
    implied = ""
    if t.startswith("[") and t.endswith("]"):
        implied, t = "exact", t[1:-1]
    elif t.startswith('"') and t.endswith('"') and len(t) > 1:
        implied, t = "phrase", t[1:-1]
    elif t.startswith("+"):
        warn("keywords with + prefixes found (retired broad match modifier); treated as broad")
        t = t.replace("+", "")
        implied = "broad"
    return t.strip(), ("negative " + implied).strip() if negative else implied


def normalize_rows(rows: list[dict], keep_ratios: bool, source: str) -> list[OrderedDict]:
    if not rows:
        return []
    columns = list(rows[0].keys())
    for r in rows[1:]:
        for c in r:
            if c not in columns:
                columns.append(c)
    has_search_term = any(standard_name(c, False)[1] == "search_term" for c in columns)
    plan = []
    for c in columns:
        kind, name = standard_name(c, has_search_term)
        if kind == "ratio":
            if keep_ratios:
                plan.append((c, "other", f"reported_{name}"))
            else:
                warn(f"dropped reported ratio column '{c}' (recomputed by metrics.py)")
            continue
        plan.append((c, kind, name))

    out_rows = []
    implied_seen = False
    for row in rows:
        out: OrderedDict = OrderedDict()
        for col, kind, name in plan:
            raw = list_to_text(row.get(col, ""))
            micros = kind.endswith("_micros")
            if name in MONEY or name in COUNTS or name in SHARES or micros or name == "quality_score":
                value, bound = parse_number(raw)
                if value is not None and micros:
                    value /= 1_000_000
                if name in SHARES and value is not None and value > 1:
                    value /= 100  # a share written as 45.2 rather than 45.2% or 0.452
                out[name] = fmt(value)
                if bound:
                    out[f"{name}_bound"] = bound
            elif name == "is_negative":
                out[name] = "true" if raw.strip().lower() in ("true", "1", "yes") else ("false" if raw.strip() else "")
            else:
                text = raw.strip()
                if text.lower() in NULLS:
                    text = ""
                if name in LOWERCASE:
                    underscore = name.endswith(("_type", "_status", "operation")) and name != "search_term_match_type"
                    text = text.lower().replace(" ", "_") if underscore else text.lower()
                out[name] = text
        # Match types, negatives, and keyword punctuation.
        if "match_type" in out and out["match_type"]:
            match, level = parse_match(out["match_type"])
            out["match_type"] = match
            if level:
                out["is_negative"] = "true"
                out["negative_level"] = level
        if "keyword" in out and out["keyword"]:
            text, implied = strip_keyword(out["keyword"])
            out["keyword"] = text
            if implied.startswith("negative"):
                out["is_negative"] = "true"
                implied = implied.replace("negative", "").strip()
            if implied:
                implied_seen = True
                if not out.get("match_type"):
                    out["match_type"] = implied
        if source:
            out["source_file"] = source
        out_rows.append(out)
    if implied_seen:
        # The file writes match types as [exact] and "phrase", so bare keywords are broad.
        for out in out_rows:
            if out.get("keyword") and not out.get("match_type"):
                out["match_type"] = "broad"
    return out_rows


def group_rows(rows: list[OrderedDict], keys: list[str]) -> list[OrderedDict]:
    missing = [k for k in keys if rows and k not in rows[0]]
    if missing:
        sys.exit(f"--group-by columns not found: {', '.join(missing)}")
    groups: "OrderedDict[tuple, OrderedDict]" = OrderedDict()
    conflicts: set[str] = set()
    for row in rows:
        key = tuple(row.get(k, "") for k in keys)
        if key not in groups:
            groups[key] = OrderedDict((k, v) for k, v in row.items() if k not in ("date", "week", "month", "source_file"))
            continue
        agg = groups[key]
        for col, value in row.items():
            if col in ("date", "week", "month", "source_file") or col in keys:
                continue
            if col in ADDITIVE:
                a = float(agg.get(col) or 0)
                b = float(value or 0)
                agg[col] = fmt(a + b) if (agg.get(col) or value) else ""
            elif agg.get(col, "") != value:
                if agg.get(col, "") and value:
                    conflicts.add(col)
                    agg[col] = ""
                elif value:
                    agg[col] = value
    for col in sorted(conflicts):
        warn(f"'{col}' differs across grouped rows and was left blank (not additive)")
    return list(groups.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="JSON or CSV files")
    parser.add_argument("--out", required=True, help="output CSV path")
    parser.add_argument("--group-by", help="comma-separated standard columns to aggregate by")
    parser.add_argument("--keep-ratios", action="store_true", help="keep reported ratios as reported_<name>")
    args = parser.parse_args()

    all_rows: list[OrderedDict] = []
    rows_in = 0
    for path_str in args.inputs:
        path = Path(path_str)
        text = decode(path.read_bytes())
        stripped = text.lstrip()
        rows = rows_from_json(stripped) if stripped[:1] in "[{" else rows_from_csv(text)
        rows_in += len(rows)
        all_rows.extend(normalize_rows(rows, args.keep_ratios, path.name if len(args.inputs) > 1 else ""))

    if args.group_by:
        all_rows = group_rows(all_rows, [k.strip() for k in args.group_by.split(",") if k.strip()])

    columns: list[str] = []
    for row in all_rows:
        for c in row:
            if c not in columns:
                columns.append(c)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"rows in: {rows_in}, rows out: {len(all_rows)}, columns: {len(columns)}", file=sys.stderr)
    print(f"columns: {', '.join(columns)}", file=sys.stderr)
    bounds = [c for c in columns if c.endswith("_bound")]
    if bounds:
        print(f"bound flags (values shown as < or > in the source): {', '.join(bounds)}", file=sys.stderr)
    for message in warnings:
        print(f"note: {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
