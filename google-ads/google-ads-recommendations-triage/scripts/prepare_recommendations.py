#!/usr/bin/env python3
"""Turn Google Ads recommendations into one flat CSV that triage.py reads.

Accepts any mix of:
  - connector output as JSON from a GAQL query on the recommendation resource
    (nested or dotted, camelCase or snake_case, searchStream chunks included)
  - CSVs whose headers are GAQL field names (recommendation.type, ...)
  - a download of the Recommendations page table view, or a CSV typed from
    recommendation cards or screenshots, using the column names listed in
    references/data-access.md (rec_id, name, campaign, current_budget, ...)

Writes one row per recommendation with standard columns: money in currency
units (micros divided by 1,000,000), ROAS as a ratio, shares as fractions.
Campaign and ad group names are filled from IDs when --lookup files have them.

Usage:
  python3 prepare_recommendations.py INPUT [INPUT ...] --out recommendations.csv
         [--lookup campaigns.csv keywords.csv ...] [--keep-dismissed]

Standard library only. Reads files with the copied normalize.py helpers.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize import decode, rows_from_csv, rows_from_json  # noqa: E402  (copied unchanged from google-ads-data-pull)

COLUMNS = [
    "rec_id", "type", "name", "campaign_id", "campaign", "ad_group_id", "ad_group", "budget_id", "dismissed",
    "current_budget", "recommended_budget", "required_budget",
    "current_target", "recommended_target", "target_multiplier", "target_type",
    "keyword", "match_type", "keyword_count", "search_terms",
    "negative_keyword", "negative_match_type", "negative_level",
    "source_campaign", "source_budget_id",
    "base_impressions", "base_clicks", "base_cost", "base_conversions", "base_conversion_value",
    "potential_impressions", "potential_clicks", "potential_cost", "potential_conversions",
    "potential_conversion_value",
    "uplift", "notes", "source",
]
MONEY_COLUMNS = {"current_budget", "recommended_budget", "required_budget", "base_cost", "potential_cost",
                 "base_conversion_value", "potential_conversion_value"}
NUMBER_COLUMNS = MONEY_COLUMNS | {"current_target", "recommended_target", "target_multiplier", "keyword_count",
                                  "base_impressions", "base_clicks", "base_conversions",
                                  "potential_impressions", "potential_clicks", "potential_conversions", "uplift"}

# Friendly or interface headers -> standard column (lower case keys).
HEADER_ALIASES = {
    "rec_id": "rec_id", "id": "rec_id", "recommendation id": "rec_id",
    "type": "type", "recommendation type": "type",
    "name": "name", "recommendation": "name", "recommendation name": "name", "title": "name",
    "campaign": "campaign", "campaign name": "campaign", "campaign_id": "campaign_id", "campaign id": "campaign_id",
    "ad group": "ad_group", "ad_group": "ad_group", "ad group name": "ad_group",
    "ad_group_id": "ad_group_id", "ad group id": "ad_group_id",
    "current budget": "current_budget", "recommended budget": "recommended_budget",
    "required budget": "required_budget",
    "current target": "current_target", "recommended target": "recommended_target",
    "target multiplier": "target_multiplier", "target type": "target_type",
    "keyword": "keyword", "keywords": "keyword", "match type": "match_type", "keyword count": "keyword_count",
    "search terms": "search_terms",
    "negative keyword": "negative_keyword", "negative match type": "negative_match_type",
    "negative level": "negative_level",
    "source campaign": "source_campaign",
    "optimization score uplift": "uplift", "score uplift": "uplift", "uplift": "uplift",
    "opt. score uplift": "uplift",
    "notes": "notes", "description": "notes", "status": "status",
    "extra cost": "extra_cost", "estimated extra cost": "extra_cost", "extra conversions": "extra_conversions",
    "estimated extra conversions": "extra_conversions", "extra conversion value": "extra_conversion_value",
    "estimated extra conversion value": "extra_conversion_value",
}
EXTRA = {"extra_cost": "cost", "extra_conversions": "conversions", "extra_conversion_value": "conversion_value"}

ID_RE = {
    "campaign": re.compile(r"campaigns/(\d+)"),
    "ad_group": re.compile(r"adGroups/(\d+)", re.IGNORECASE),
    "budget": re.compile(r"campaignBudgets/(\d+)", re.IGNORECASE),
}

notes_out: list[str] = []


def note(message: str) -> None:
    if message not in notes_out:
        notes_out.append(message)


def number(text):
    if text in (None, ""):
        return None
    t = str(text).strip().replace(",", "").replace(" ", "")
    if t.lower() in ("", "--", "-", "n/a", "null", "none", "missing", "unknown"):
        return None
    percent = t.endswith("%")
    t = re.sub(r"[^\d.\-eE]", "", t.rstrip("%"))
    if t in ("", "-", "."):
        return None
    try:
        value = float(t)
    except ValueError:
        return None
    return value / 100 if percent else value


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def extract_id(kind: str, text: str) -> str:
    if not text:
        return ""
    m = ID_RE[kind].search(text)
    if m:
        return m.group(1)
    return text if text.isdigit() else ""


def json_list(text: str) -> list:
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def from_gaql_row(row: dict) -> dict:
    """Map one flattened recommendation row (dotted snake_case keys) to standard columns."""
    flat = {}
    for key, value in row.items():
        k = key.strip().lower()
        if k.startswith("recommendation."):
            k = k[len("recommendation."):]
        flat[k] = value
    out = {c: "" for c in COLUMNS}
    out["source"] = "connector"
    out["rec_id"] = flat.get("resource_name", "")
    out["type"] = (flat.get("type") or flat.get("type_") or "").strip().upper()
    out["dismissed"] = str(flat.get("dismissed", "")).lower()
    camp = flat.get("campaign", "")
    if not camp and flat.get("campaigns"):
        listed = json_list(flat["campaigns"]) or flat["campaigns"].split()
        camp = listed[0] if listed else ""
    out["campaign_id"] = extract_id("campaign", camp)
    out["ad_group_id"] = extract_id("ad_group", flat.get("ad_group", ""))
    out["budget_id"] = extract_id("budget", flat.get("campaign_budget", ""))

    # Google's estimate: base and potential metrics.
    for side in ("base", "potential"):
        for metric, column in (("impressions", "impressions"), ("clicks", "clicks"), ("cost_micros", "cost"),
                               ("conversions", "conversions"), ("conversions_value", "conversion_value")):
            raw = flat.get(f"impact.{side}_metrics.{metric}")
            value = number(raw)
            if value is not None and metric.endswith("_micros"):
                value /= 1_000_000
            out[f"{side}_{column}"] = fmt(value)

    rec_type = out["type"]
    for key, raw in flat.items():
        if key.startswith("impact.") or raw in (None, ""):
            continue
        value = number(raw)
        if key.endswith("current_budget_amount_micros") and value is not None:
            out["current_budget"] = fmt(value / 1_000_000)
        elif key.endswith("recommended_budget_amount_micros") and value is not None:
            out["recommended_budget"] = fmt(value / 1_000_000)
        elif key.endswith("required_campaign_budget_amount_micros") and value is not None:
            out["required_budget"] = fmt(value / 1_000_000)
        elif (key.endswith("current_average_target_micros") or key.endswith("average_target_cpa_micros")) and value is not None:
            out["current_target"] = fmt(value / 1_000_000)
        elif key.endswith("average_target_roas") and value is not None:
            out["current_target"] = fmt(value)
        elif key.endswith("recommended_target_multiplier") and value is not None:
            out["target_multiplier"] = fmt(value)
        elif re.search(r"(recommended_)?target_cpa_micros$", key) and value is not None and "options" not in key:
            out["recommended_target"] = fmt(value / 1_000_000)
            out["target_type"] = "cpa"
        elif re.search(r"(recommended_)?target_roas$", key) and value is not None and "options" not in key:
            out["recommended_target"] = fmt(value)
            out["target_type"] = "roas"
        elif key.endswith("keyword_recommendation.keyword.text"):
            out["keyword"] = str(raw)
        elif key.endswith("keyword_recommendation.keyword.match_type"):
            out["match_type"] = str(raw).lower()
        elif key.endswith("keyword_recommendation.search_terms"):
            terms = [t.get("text", "") for t in json_list(raw) if isinstance(t, dict)]
            out["search_terms"] = "; ".join(t for t in terms if t)
        elif key.endswith("use_broad_match_keyword_recommendation.keyword"):
            words = [k.get("text", "") for k in json_list(raw) if isinstance(k, dict)]
            out["keyword"] = "; ".join(w for w in words if w)
            out["match_type"] = "broad"
        elif key.endswith("suggested_keywords_count") and value is not None:
            out["keyword_count"] = fmt(value)
        elif key.endswith("campaign_uses_shared_budget") and str(raw).lower() == "true":
            out["notes"] = (out["notes"] + " campaign uses a shared budget").strip()
        elif key.endswith("excess_campaign_budget"):
            out["source_budget_id"] = extract_id("budget", str(raw))
        elif key.endswith("keyword_match_type_recommendation.keyword.text"):
            out["keyword"] = str(raw)
        elif key.endswith("recommended_match_type"):
            out["match_type"] = str(raw).lower()
    if not out["target_type"]:
        if "ROAS" in rec_type:
            out["target_type"] = "roas"
        elif "CPA" in rec_type:
            out["target_type"] = "cpa"
    return out


def from_friendly_row(row: dict) -> dict:
    out = {c: "" for c in COLUMNS}
    out["source"] = "export"
    for key, value in row.items():
        std = HEADER_ALIASES.get(key.strip().lower())
        if not std:
            std = key.strip().lower() if key.strip().lower() in COLUMNS else ""
        if not std or value in (None, ""):
            continue
        if std == "status":
            if "dismiss" in str(value).lower():
                out["dismissed"] = "true"
            continue
        if std in EXTRA:
            # An estimate typed from a card ("+$340 cost, +4 conversions a week") becomes base 0, potential = extra.
            extra = number(str(value))
            if extra is not None:
                out[f"base_{EXTRA[std]}"] = "0"
                out[f"potential_{EXTRA[std]}"] = fmt(extra)
            continue
        text = str(value).strip()
        if std in NUMBER_COLUMNS:
            out[std] = fmt(number(text))
        elif std == "type":
            out[std] = text.upper().replace(" ", "_")
        else:
            out[std] = text
    if out["match_type"]:
        out["match_type"] = out["match_type"].lower().replace(" match", "").strip()
    if out["target_type"]:
        out["target_type"] = out["target_type"].lower()
    elif "roas" in (out["name"] + out["type"]).lower():
        out["target_type"] = "roas"
    elif "cpa" in (out["name"] + out["type"]).lower():
        out["target_type"] = "cpa"
    return out


def rows_from_table(text: str) -> list[dict]:
    """Read a CSV, finding the header row by recommendation column names (skips title rows)."""
    sample = "\n".join(text.splitlines()[:20])
    delimiter = max((",", "\t", ";"), key=sample.count)
    table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    for i, row in enumerate(table[:15]):
        cells = [c.strip().lower() for c in row]
        if sum(1 for c in cells if c in HEADER_ALIASES or c in COLUMNS or c.startswith("recommendation.")) >= 2:
            header = [c.strip() for c in row]
            out = []
            for r in table[i + 1:]:
                if not any(cell.strip() for cell in r) or (r and r[0].strip().lower().startswith("total")):
                    continue
                out.append({header[k]: (r[k] if k < len(r) else "") for k in range(len(header))})
            return out
    return rows_from_csv(text)


def is_gaql(rows: list[dict]) -> bool:
    keys = {k.lower() for r in rows[:5] for k in r}
    return any(k.startswith("recommendation.") or k in ("resource_name", "type_") for k in keys)


def read_lookup(paths: list[str]) -> tuple[dict, dict, dict]:
    campaigns, ad_groups, budgets = {}, {}, {}
    for path in paths:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            for r in csv.DictReader(handle):
                cid, name = r.get("campaign_id", ""), r.get("campaign", "")
                if cid and name:
                    campaigns.setdefault(cid, name)
                gid, gname = r.get("ad_group_id", ""), r.get("ad_group", "")
                if gid and gname:
                    ad_groups.setdefault(gid, (name, gname))
                for col, value in r.items():
                    if col.endswith("campaign_budget") and value and name:
                        budgets.setdefault(extract_id("budget", value), name)
    return campaigns, ad_groups, budgets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--lookup", nargs="*", default=[], help="normalized CSVs with campaign_id/campaign or ad_group_id/ad_group")
    parser.add_argument("--keep-dismissed", action="store_true")
    args = parser.parse_args()

    rows_out: list[dict] = []
    for path_str in args.inputs:
        text = decode(Path(path_str).read_bytes())
        stripped = text.lstrip()
        rows = rows_from_json(stripped) if stripped[:1] in "[{" else rows_from_table(text)
        if not rows:
            note(f"{path_str}: no rows")
            continue
        mapper = from_gaql_row if is_gaql(rows) else from_friendly_row
        for r in rows:
            out = mapper(r)
            if not out["type"] and not out["name"]:
                continue
            rows_out.append(out)

    campaigns, ad_groups, budgets = read_lookup(args.lookup)
    dismissed = 0
    kept: list[dict] = []
    for i, r in enumerate(rows_out, 1):
        if r["dismissed"] == "true" and not args.keep_dismissed:
            dismissed += 1
            continue
        if not r["rec_id"]:
            r["rec_id"] = f"r{i}"
        if r["campaign_id"] and not r["campaign"]:
            r["campaign"] = campaigns.get(r["campaign_id"], "")
            if not r["campaign"]:
                note(f"campaign id {r['campaign_id']} not found in the lookup files; name left blank")
        if r["ad_group_id"] and not r["ad_group"]:
            r["ad_group"] = ad_groups.get(r["ad_group_id"], ("", ""))[1]
        if r["source_budget_id"] and not r["source_campaign"]:
            r["source_campaign"] = budgets.get(r["source_budget_id"], "")
        kept.append(r)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    by_type: dict[str, int] = {}
    for r in kept:
        label = r["type"] or r["name"]
        by_type[label] = by_type.get(label, 0) + 1
    print(f"recommendations in: {len(rows_out)}, written: {len(kept)}, dismissed skipped: {dismissed}", file=sys.stderr)
    for label, count in sorted(by_type.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {count:>3}  {label}", file=sys.stderr)
    with_impact = sum(1 for r in kept if r["base_cost"] or r["potential_cost"])
    print(f"with Google's impact estimate: {with_impact}", file=sys.stderr)
    for message in notes_out:
        print(f"note: {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
