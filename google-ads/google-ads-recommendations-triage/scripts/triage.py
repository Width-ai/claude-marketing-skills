#!/usr/bin/env python3
# Rules adapted in part from google-ads-recommendations-reviewer in Insightful-Pipe/google-ads-skills (MIT, Copyright (c) 2026 InsightfulPipe).
"""Sort Google Ads recommendations into accept, reject, or test, with a reason for each.

Joins each recommendation to its campaign's own numbers and to the account
context (Economics, Conversions, Permissions and limits, terms), applies the
rule table in references/recommendation-types.md, and writes:
  - triage.csv     one row per recommendation: kind, verdict, reason, route
  - triage.md      the report: table, accept steps, dismiss steps, experiments,
                   holds, auto-apply check, optimization score note
  - a change set   (with --changes-out) for google-ads-apply-changes, holding
                   only accepted items that map to set_budget, set_target,
                   add_keyword, set_status (pause), or remove_negative

It never applies or dismisses anything. Every number in the output is
computed here.

Usage:
  python3 triage.py --recommendations recommendations.csv --campaigns campaigns.csv [more.csv]
      --context .agents/google-ads-context.md --days 30 --window "2026-10-16 to 2026-11-14"
      [--keywords keywords.csv] [--negatives negatives.csv] [--ads ads.csv]
      [--subscriptions subscriptions.csv] [--change-history change_history.csv]
      [--optimization-score 0.81] [--overrides overrides.csv]
      [--target-cpa 80 --breakeven-cpa 120 | --target-roas 4 --breakeven-roas 3]
      [--conversion-lag 3] [--today YYYY-MM-DD]
      [--max-budget-change 0.20] [--max-target-change 0.15]
      [--budget-lost-threshold 0.10] [--budget-use-threshold 0.90] [--min-test-conversions 30]
      --out-dir triage/ [--changes-out google-ads-changes/2026-11-15-recommendations.json]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import zero_conv_upper  # noqa: E402  (copied unchanged from google-ads-data-pull)

# ---------------------------------------------------------------------------
# Rule table: kinds, the API types and interface names that map to them.
# ---------------------------------------------------------------------------

KINDS = {
    # kind: (label, raises spend: yes/no/maybe, sequencing group or "")
    "raise_budget": ("Raise budget", "yes", "budget"),
    "move_budget": ("Move unused budget", "no", "budget"),
    "target_loosen": ("Loosen CPA or ROAS target", "yes", "bidding"),
    "target_set": ("Set a CPA or ROAS target", "maybe", "bidding"),
    "smart_bidding_switch": ("Switch to conversion-based bidding", "yes", "bidding"),
    "clicks_bidding": ("Switch to clicks or visibility bidding", "yes", "bidding"),
    "bidding_exploration": ("Smart Bidding Exploration", "yes", "bidding"),
    "broad_match": ("Broad match keywords", "yes", "matching"),
    "ai_max": ("AI Max for Search", "yes", "matching"),
    "add_keywords": ("Add keywords", "yes", ""),
    "remove_keywords": ("Remove redundant or non-serving keywords", "no", ""),
    "conflicting_negatives": ("Remove conflicting negatives", "maybe", ""),
    "network_expansion": ("Search partners, Display, or video partners", "yes", "reach"),
    "audience_expansion": ("Audience or optimized targeting expansion", "yes", "reach"),
    "url_expansion": ("Final URL expansion", "yes", "reach"),
    "pmax_adopt": ("Performance Max opt-in or upgrade", "yes", ""),
    "new_customers": ("Optimize for new customers", "maybe", "bidding"),
    "shopping_expand": ("Advertise more Shopping products", "yes", ""),
    "ads_improve": ("Improve ads and Ad Strength", "no", ""),
    "assets_add": ("Add assets", "no", ""),
    "auto_content": ("Google-generated assets", "no", ""),
    "measurement": ("Conversion tracking and measurement", "no", ""),
    "audience_data": ("Audience lists and reporting segments", "no", ""),
    "ad_rotation": ("Optimized ad rotation", "no", ""),
    "shopping_fix": ("Shopping feed fixes", "no", ""),
    "repair": ("Repairs", "no", ""),
    "retired": ("Retired feature", "no", ""),
    "other": ("Not in the rule table", "maybe", ""),
}

TYPE_TO_KIND = {
    "CAMPAIGN_BUDGET": "raise_budget", "FORECASTING_CAMPAIGN_BUDGET": "raise_budget",
    "MARGINAL_ROI_CAMPAIGN_BUDGET": "raise_budget", "RAISE_BUDGET_PERFORMANCE_TOO_LOW": "raise_budget",
    "MOVE_UNUSED_BUDGET": "move_budget",
    "RAISE_TARGET_CPA": "target_loosen", "RAISE_TARGET_CPA_BID_TOO_LOW": "target_loosen",
    "RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW": "target_loosen", "LOWER_TARGET_ROAS": "target_loosen",
    "LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW": "target_loosen",
    "SET_TARGET_CPA": "target_set", "SET_TARGET_ROAS": "target_set",
    "FORECASTING_SET_TARGET_CPA": "target_set", "FORECASTING_SET_TARGET_ROAS": "target_set",
    "TARGET_CPA_OPT_IN": "smart_bidding_switch", "MAXIMIZE_CONVERSIONS_OPT_IN": "smart_bidding_switch",
    "TARGET_ROAS_OPT_IN": "smart_bidding_switch", "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "smart_bidding_switch",
    "MAXIMIZE_CLICKS_OPT_IN": "clicks_bidding", "ENHANCED_CPC_OPT_IN": "retired",
    "USE_BROAD_MATCH_KEYWORD": "broad_match", "KEYWORD_MATCH_TYPE": "broad_match",
    "KEYWORD": "add_keywords",
    "DISPLAY_EXPANSION_OPT_IN": "network_expansion", "SEARCH_PARTNERS_OPT_IN": "network_expansion",
    "CUSTOM_AUDIENCE_OPT_IN": "audience_expansion",
    "REFRESH_CUSTOMER_MATCH_LIST": "audience_data",
    "PERFORMANCE_MAX_OPT_IN": "pmax_adopt", "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX": "pmax_adopt",
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX": "pmax_adopt",
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX": "pmax_adopt",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX": "retired",
    "PERFORMANCE_MAX_FINAL_URL_OPT_IN": "url_expansion",
    "IMPROVE_PERFORMANCE_MAX_AD_STRENGTH": "ads_improve", "IMPROVE_DEMAND_GEN_AD_STRENGTH": "ads_improve",
    "RESPONSIVE_SEARCH_AD": "ads_improve", "RESPONSIVE_SEARCH_AD_ASSET": "ads_improve",
    "RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH": "ads_improve", "TEXT_AD": "retired",
    "SITELINK_ASSET": "assets_add", "CALLOUT_ASSET": "assets_add", "CALL_ASSET": "assets_add",
    "LEAD_FORM_ASSET": "assets_add", "DYNAMIC_IMAGE_EXTENSION_OPT_IN": "auto_content",
    "IMPROVE_GOOGLE_TAG_COVERAGE": "measurement",
    "OPTIMIZE_AD_ROTATION": "ad_rotation",
    "OPTIMIZE_FOR_NEW_CUSTOMERS": "new_customers",
    "SHOPPING_ADD_AGE_GROUP": "shopping_fix", "SHOPPING_ADD_COLOR": "shopping_fix",
    "SHOPPING_ADD_GENDER": "shopping_fix", "SHOPPING_ADD_GTIN": "shopping_fix",
    "SHOPPING_ADD_MORE_IDENTIFIERS": "shopping_fix", "SHOPPING_ADD_SIZE": "shopping_fix",
    "SHOPPING_FIX_DISAPPROVED_PRODUCTS": "shopping_fix",
    "SHOPPING_FIX_SUSPENDED_MERCHANT_CENTER_ACCOUNT": "shopping_fix",
    "SHOPPING_FIX_MERCHANT_CENTER_ACCOUNT_SUSPENSION_WARNING": "shopping_fix",
    "SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN": "shopping_expand", "SHOPPING_TARGET_ALL_OFFERS": "shopping_expand",
    "CAMPAIGN_SPECIFIC_APP_GOAL": "other",
}

# Interface names (lower case, matched in order). Specific patterns first.
UI_PATTERNS = [
    (r"fix disapproved (demand gen|performance max|sitelink)|fix your ad (text|destination)", "repair"),
    (r"portfolio bid strategy", "other"),
    (r"remove (redundant|non-serving) keyword", "remove_keywords"),
    (r"remove conflicting negative", "conflicting_negatives"),
    (r"dynamic search ad", "retired"),
    (r"ai max", "ai_max"),
    (r"text customi[sz]ation", "auto_content"),
    (r"broad match", "broad_match"),
    (r"keywords to each ad group|ads to each ad group", "repair"),
    (r"add (new )?keywords", "add_keywords"),
    (r"move unused budget", "move_budget"),
    (r"budget", "raise_budget"),
    (r"adjust your (cpa|roas) target|fix low cpa target", "target_loosen"),
    (r"set a (target cpa|target roas|bidding strategy target)", "target_set"),
    (r"maximi[sz]e clicks|target impression share", "clicks_bidding"),
    (r"smart bidding exploration", "bidding_exploration"),
    (r"maximi[sz]e conversion|with target cpa|with target roas", "smart_bidding_switch"),
    (r"search partners|video partners|display expansion", "network_expansion"),
    (r"audience segments for reporting|customer match|customer list|audience sources", "audience_data"),
    (r"fix your audience targeting", "repair"),
    (r"optimi[sz]ed targeting|targeting expansion|reach new audiences|custom audience|broader audience|add audiences|audience gap", "audience_expansion"),
    (r"performance max.*final url|final url expansion", "url_expansion"),
    (r"performance max asset group|ad strength|improve your (responsive|demand gen)|add responsive (search|display) ads|assets to your responsive", "ads_improve"),
    (r"create a performance max|target more products with performance max|performance max", "pmax_adopt"),
    (r"optimi[sz]e for new customers", "new_customers"),
    (r"enhanced conversions|conversion tracking|site tag|google tag|auto-tagging|conversion value|data-driven attribution|conversion rate drop|conversion parameters|analytics property|in-app conversion|store visits|firebase", "measurement"),
    (r"optimi[sz]ed ad rotation", "ad_rotation"),
    (r"dynamic (image|sitelink)", "auto_content"),
    (r"target all eligible shopping", "shopping_expand"),
    (r"gtin|disapproved products|merchant center|products to your shopping", "shopping_fix"),
    (r"sitelink|callout|call asset|lead form|image asset|structured snippet|price asset|location asset|video|responsive display", "assets_add"),
    (r"^fix |complete advertiser verification|certification|deep link", "repair"),
]

# Interface titles for API types (from Google's Types of recommendations page), used as labels.
TYPE_LABELS = {
    "CAMPAIGN_BUDGET": "Raise your budgets", "FORECASTING_CAMPAIGN_BUDGET": "Raise your budgets for upcoming traffic increases",
    "MARGINAL_ROI_CAMPAIGN_BUDGET": "Adjust your budgets", "RAISE_BUDGET_PERFORMANCE_TOO_LOW": "Raise your budgets",
    "MOVE_UNUSED_BUDGET": "Move unused budgets",
    "RAISE_TARGET_CPA": "Adjust your CPA targets", "RAISE_TARGET_CPA_BID_TOO_LOW": "Adjust your CPA targets",
    "RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW": "Adjust your CPA targets", "LOWER_TARGET_ROAS": "Adjust your ROAS targets",
    "LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW": "Adjust your ROAS targets",
    "SET_TARGET_CPA": "Set a target CPA", "SET_TARGET_ROAS": "Set a target ROAS",
    "FORECASTING_SET_TARGET_CPA": "Set a target CPA to capture upcoming traffic increases",
    "FORECASTING_SET_TARGET_ROAS": "Set a target ROAS to capture upcoming traffic increases",
    "TARGET_CPA_OPT_IN": "Bid more efficiently with Target CPA", "TARGET_ROAS_OPT_IN": "Bid more efficiently with Target ROAS",
    "MAXIMIZE_CONVERSIONS_OPT_IN": "Bid more efficiently with Maximize conversions",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "Bid more efficiently with Maximize conversion value",
    "MAXIMIZE_CLICKS_OPT_IN": "Bid more efficiently with Maximize clicks", "ENHANCED_CPC_OPT_IN": "Enhanced CPC (retired)",
    "USE_BROAD_MATCH_KEYWORD": "Add broad match keywords", "KEYWORD_MATCH_TYPE": "Change keyword match types (broad)",
    "KEYWORD": "Add new keywords", "SEARCH_PARTNERS_OPT_IN": "Expand your reach with Google search partners",
    "DISPLAY_EXPANSION_OPT_IN": "Use Display Expansion", "CUSTOM_AUDIENCE_OPT_IN": "Create a custom audience",
    "REFRESH_CUSTOMER_MATCH_LIST": "Refresh your Customer Match lists",
    "SITELINK_ASSET": "Add sitelink assets to your ads", "CALLOUT_ASSET": "Add callouts to your ads",
    "CALL_ASSET": "Add call assets to your ads", "LEAD_FORM_ASSET": "Add lead form assets to your ads",
    "DYNAMIC_IMAGE_EXTENSION_OPT_IN": "Add dynamic image assets",
    "RESPONSIVE_SEARCH_AD": "Add responsive search ads", "RESPONSIVE_SEARCH_AD_ASSET": "Add assets to your responsive search ads",
    "RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH": "Improve your responsive search ads", "TEXT_AD": "Text ad (retired)",
    "IMPROVE_PERFORMANCE_MAX_AD_STRENGTH": "Improve your Performance Max asset groups",
    "IMPROVE_DEMAND_GEN_AD_STRENGTH": "Improve your Demand Gen", "OPTIMIZE_AD_ROTATION": "Use optimized ad rotation",
    "IMPROVE_GOOGLE_TAG_COVERAGE": "Improve Google tag coverage", "PERFORMANCE_MAX_OPT_IN": "Create a Performance Max campaign",
    "PERFORMANCE_MAX_FINAL_URL_OPT_IN": "Turn on Final URL expansion in Performance Max",
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX": "Upgrade Dynamic Search Ads to Performance Max",
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX": "Upgrade a Local campaign to Performance Max",
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX": "Move Shopping products to Performance Max",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX": "Smart Shopping upgrade (retired)",
    "OPTIMIZE_FOR_NEW_CUSTOMERS": "Optimize for new customers",
    "SHOPPING_TARGET_ALL_OFFERS": "Target all eligible Shopping products",
    "SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN": "Add products to your Shopping campaigns",
}


BID_NAMES = {"manual_cpc": "Manual CPC", "target_cpa": "Target CPA", "target_roas": "Target ROAS",
             "maximize_conversions": "Maximize conversions", "maximize_conversion_value": "Maximize conversion value",
             "target_spend": "Maximize clicks", "maximize_clicks": "Maximize clicks",
             "target_impression_share": "Target impression share", "manual_cpm": "Manual CPM", "manual_cpv": "Manual CPV"}


def bid_name(bid: str) -> str:
    return BID_NAMES.get(bid, bid.replace("_", " ") if bid else "an unknown strategy")


def label_of(rec: dict, with_keyword: bool = True) -> str:
    t = (rec.get("type") or "").upper()
    base = rec.get("name") or TYPE_LABELS.get(t) or t.replace("_", " ").capitalize() or "Unnamed recommendation"
    if with_keyword and rec.get("keyword") and resolve_kind(rec) in ("add_keywords", "remove_keywords", "conflicting_negatives"):
        base += f": {rec.get('keyword')}"
    return base


CONVERSION_BIDDING = {"target_cpa", "target_roas", "maximize_conversions", "maximize_conversion_value"}
VALUE_TYPES = {"TARGET_ROAS_OPT_IN", "MAXIMIZE_CONVERSION_VALUE_OPT_IN", "SET_TARGET_ROAS", "FORECASTING_SET_TARGET_ROAS"}
REVIEW_DAYS = {"raise_budget": 7, "move_budget": 7, "target_loosen": 14, "target_set": 14, "add_keywords": 14,
               "remove_keywords": 7, "conflicting_negatives": 14}
BIDDING_KINDS = {"target_loosen", "target_set"}
GROUP_ORDER = {"budget": 0, "bidding": 1, "matching": 2, "reach": 3}
VERDICT_RANK = {"reject": 0, "hold": 1, "test": 2, "accept": 3}
SETTLE_DAYS = 14   # Google's AI Max and Smart Bidding guidance: about two weeks before judging
EVAL_DAYS = 14     # Google's Smart Bidding guidance: judge over at least two weeks
MAX_EVAL_DAYS = 42
ROAS_MIN_CONV_30D = 15  # Google's Smart Bidding best practices for target ROAS (possibly dated)

# Auto-apply types the API can't report, from Google's auto-apply help page.
UI_ONLY_AUTO_APPLY = ["Remove redundant keywords", "Remove non-serving keywords",
                      "Remove conflicting negative keywords", "Use targeting expansion", "Add audiences",
                      "Add audience segments for reporting", "Upgrade your conversion tracking",
                      "Bid more efficiently with Target impression share", "Use Display expansion"]

warnings: list[str] = []


def warn(message: str) -> None:
    if message not in warnings:
        warnings.append(message)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def num(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower().strip('[]"'))


def tokens(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", norm_text(text).lstrip("-")) if t]


def contains_phrase(words: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return bool(phrase) and any(words[i:i + n] == phrase for i in range(len(words) - n + 1))


def negative_blocks(neg: list[str], match: str, query: list[str]) -> bool:
    if not neg or not query:
        return False
    if match == "exact":
        return neg == query
    if match == "phrase":
        return contains_phrase(query, neg)
    return set(neg) <= set(query)


def wilson(successes: float, trials: float, z: float = 1.96):
    if trials <= 0:
        return None, None
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return max(centre - half, 0.0), min(centre + half, 1.0)


# ---------------------------------------------------------------------------
# Context file
# ---------------------------------------------------------------------------

def section(text: str, name: str) -> str:
    m = re.search(rf"(?ms)^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)", text)
    return m.group(1) if m else ""


def field_value(block: str, label_start: str) -> str:
    for line in block.splitlines():
        m = re.match(r"^\s*[-*]\s*(.+?):\s*(.*)$", line)
        if m and m.group(1).strip().lower().startswith(label_start.lower()):
            return m.group(2).strip()
    return ""


def is_missing(value: str) -> bool:
    v = (value or "").strip().lower()
    return v == "" or v.startswith("missing") or v.startswith("[") or v in ("unknown", "n/a", "tbd")


def parse_econ(value: str):
    """Return (mode, number) from text like '$80', '400% ROAS', 'ROAS 4.0', or (None, None)."""
    if is_missing(value):
        return None, None
    low = value.lower()
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(%|x\b)?", value)
    if not m:
        return None, None
    number = float(m.group(1).replace(",", ""))
    if m.group(2) == "%":
        number /= 100
    if "roas" in low or m.group(2) in ("%", "x"):
        return "roas", number
    if "cpa" in low or re.search(r"[$€£]", value) or "cost" in low:
        return "cpa", number
    return None, number


def parse_days(text: str):
    t = (text or "").lower()
    if not t or is_missing(t):
        return None
    if "same day" in t or "same-day" in t or "hour" in t:
        return 0
    m = re.search(r"(\d+)\s*(day|week)", t)
    if m:
        return int(m.group(1)) * (7 if m.group(2) == "week" else 1)
    return None


def parse_bullets(block: str) -> list[str]:
    items = []
    for line in block.splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if m and not m.group(1).startswith("[") and ":" not in m.group(1)[:40] and not is_missing(m.group(1)):
            items.append(m.group(1).strip())
    return items


class Context:
    def __init__(self):
        self.found = False
        self.account = ""
        self.currency = ""
        self.mode = None
        self.target = None
        self.breakeven = None
        self.econ_source = "MISSING"
        self.tracking = "unknown"
        self.tracking_note = ""
        self.primary_actions: list[str] = []
        self.has_values = None
        self.lag = None
        self.max_budget_change = 0.20
        self.max_target_change = 0.15
        self.limits_source = "this skill's defaults"
        self.protected: list[str] = []
        self.unwanted: list[str] = []
        self.restricted = ""
        self.disclaimers = ""
        self.offer_known = False
        self.prices_known = False
        self.hours = ""
        self.brand_campaigns: list[str] = []


def parse_context(path: str | None) -> Context:
    ctx = Context()
    if not path or not Path(path).exists():
        if path:
            warn(f"context file not found: {path}")
        return ctx
    text = Path(path).read_text(encoding="utf-8")
    ctx.found = True
    m = re.search(r"(?m)^\*\*Account:\*\*\s*(.+)$", text)
    ctx.account = m.group(1).strip() if m else ""
    basics = section(text, "Account basics")
    ctx.currency = field_value(basics, "Currency")
    if is_missing(ctx.currency):
        ctx.currency = ""

    econ = section(text, "Economics")
    tmode, tval = parse_econ(field_value(econ, "Target CPA or target ROAS"))
    bmode, bval = parse_econ(field_value(econ, "Break-even"))
    ctx.mode = tmode or bmode
    if tmode and bmode and tmode != bmode:
        warn("Economics mixes a CPA target and a ROAS break-even; pass --target-* and --breakeven-* explicitly")
    if ctx.mode:
        ctx.target = tval if (tmode or ctx.mode) == ctx.mode else None
        ctx.breakeven = bval if (bmode or ctx.mode) == ctx.mode else None
        ctx.econ_source = "context file"

    conv = section(text, "Conversions")
    problems, lags, values = [], [], []
    rows = 0
    for line in conv.splitlines():
        if not line.strip().startswith("|") or "---" in line or "Conversion action" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0].startswith("["):
            continue
        rows += 1
        name, _measures, primary, value, known, delay = cells[:6]
        if primary.lower().startswith("y"):
            ctx.primary_actions.append(name)
            if not is_missing(known) and known.strip().lower() not in ("none", "no", "none known", "not applicable"):
                problems.append(f"{name}: {known}")
            d = parse_days(delay)
            if d is not None:
                lags.append(d)
            values.append(value)
    if rows and ctx.primary_actions:
        ctx.tracking = "concern" if problems else "ok"
        ctx.tracking_note = "; ".join(problems)
        known_values = [v for v in values if not is_missing(v)]
        ctx.has_values = bool(known_values) if values else None
    ctx.lag = max(lags) if lags else None

    limits = section(text, "Permissions and limits")
    found_limit = False
    for key, pattern in (("max_budget_change", r"max(?:imum)? budget change[^:\n]*:\s*([\d.]+)\s*%"),
                         ("max_target_change", r"max(?:imum)? target change[^:\n]*:\s*([\d.]+)\s*%")):
        mm = re.search(pattern, limits, re.IGNORECASE)
        if mm:
            setattr(ctx, key, float(mm.group(1)) / 100)
            found_limit = True
    if found_limit:
        ctx.limits_source = "context file"

    ctx.protected = parse_bullets(section(text, "Protected terms"))
    ctx.unwanted = parse_bullets(section(text, "Terms we don't want"))
    offer = section(text, "Business and offer")
    r = field_value(offer, "Restricted category")
    ctx.restricted = "" if is_missing(r) or r.lower().startswith("none") else r
    d = field_value(offer, "Required disclaimers")
    ctx.disclaimers = "" if is_missing(d) or d.lower().startswith("none") else d
    ctx.offer_known = not is_missing(field_value(offer, "Approved offers")) or not is_missing(field_value(offer, "Approved proof"))
    ctx.prices_known = not is_missing(field_value(offer, "Prices that may appear"))
    geo = section(text, "Geography and schedule")
    h = field_value(geo, "Hours")
    ctx.hours = "" if is_missing(h) else h
    cmap = section(text, "Campaign map")
    for line in cmap.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and "brand" in cells[2].lower() and not cells[0].startswith("["):
            ctx.brand_campaigns.append(cells[0].lower())
    return ctx


# ---------------------------------------------------------------------------
# Campaign data
# ---------------------------------------------------------------------------

ADDITIVE = ("impressions", "clicks", "cost", "conversions", "conversion_value")


def load_campaigns(paths: list[str]) -> tuple[dict, dict]:
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for path in paths:
        rows = read_csv(path)
        if not rows:
            continue
        daily = "date" in rows[0]
        grouped: dict[str, dict] = {}
        for r in rows:
            key = r.get("campaign_id") or r.get("campaign", "")
            if not key:
                continue
            g = grouped.setdefault(key, {})
            for col, value in r.items():
                if col in ADDITIVE:
                    if value not in ("", None):
                        g[col] = (g.get(col) or 0.0) + (num(value) or 0.0)
                elif daily and ("impression_share" in col or col.endswith("_is")):
                    continue
                elif value not in ("", None) and col not in g:
                    g[col] = value
        if daily:
            warn(f"{path} has daily rows; metrics were summed and impression share columns ignored")
        for key, g in grouped.items():
            target = None
            if g.get("campaign_id") and g["campaign_id"] in by_id:
                target = by_id[g["campaign_id"]]
            elif g.get("campaign") and g["campaign"].lower() in by_name:
                target = by_name[g["campaign"].lower()]
            if target is None:
                target = {}
            for col, value in g.items():
                if col not in target or target[col] in ("", None):
                    target[col] = value
            if target.get("campaign_id"):
                by_id[target["campaign_id"]] = target
            if target.get("campaign"):
                by_name[target["campaign"].lower()] = target
    return by_id, by_name


class Camp:
    """A campaign's numbers for the window, with ratios computed here."""

    def __init__(self, row: dict, days: float):
        self.row = row
        self.name = row.get("campaign", "")
        self.cost = num(row.get("cost")) or 0.0
        self.clicks = num(row.get("clicks")) or 0.0
        self.conv = num(row.get("conversions")) or 0.0
        self.value = num(row.get("conversion_value")) or 0.0
        self.budget = num(row.get("budget"))
        self.shared = str(row.get("budget_shared", "")).lower() == "true"
        self.bid = (row.get("bid_strategy_type") or "").lower()
        self.ctype = (row.get("campaign_type") or "").lower()
        self.lost_budget = num(row.get("search_budget_lost_is"))
        self.lost_rank = num(row.get("search_rank_lost_is"))
        self.days = days
        status = " ".join(str(row.get(c, "")) for c in row if "primary_status" in c).lower()
        self.learning = "learning" in status
        self.constrained = "budget_constrained" in status
        self.cpc = self.cost / self.clicks if self.clicks else None
        self.cpa = self.cost / self.conv if self.conv else None
        self.roas = self.value / self.cost if self.cost else None
        self.conv_30 = self.conv * 30 / days if days else None
        self.use = (self.cost / days) / self.budget if (days and self.budget) else None
        target_cols = [c for c in row if re.search(r"target_cpa(_target_cpa)?$|target_cpa_micros$", c)]
        roas_cols = [c for c in row if re.search(r"target_roas(_target_roas)?$", c)]
        self.own_target_cpa = next((num(row[c]) for c in target_cols if num(row[c])), None)
        self.own_target_roas = next((num(row[c]) for c in roas_cols if num(row[c])), None)
        self.opt_score = next((num(row[c]) for c in row if c.endswith("optimization_score") and num(row[c]) is not None), None)
        self.search_partners_on = str(row.get("campaign_network_settings_target_search_network", "")).lower() == "true"
        self.display_on = str(row.get("campaign_network_settings_target_content_network", "")).lower() == "true"


# ---------------------------------------------------------------------------
# Judging helpers
# ---------------------------------------------------------------------------

class Judge:
    def __init__(self, ctx: Context, args):
        self.ctx = ctx
        self.args = args
        self.mode = ctx.mode or "cpa"
        self.T = ctx.target
        self.B = ctx.breakeven
        self.be_note = ""
        self.limit_name = "break-even"
        self.loss = "loss"
        if self.B is None and self.T is not None:
            self.B = self.T
            self.limit_name = "target"
            self.be_note = " (break-even MISSING, so the target is the limit)"
            self.loss = "results that miss your target"
        self.sym = {"USD": "$", "CAD": "CA$", "AUD": "A$", "EUR": "€", "GBP": "£", "NZD": "NZ$"}.get(
            ctx.currency.upper()[:3], (ctx.currency.upper()[:3] + " ") if ctx.currency else "$")

    # Formatting
    def money(self, x) -> str:
        if x is None:
            return "MISSING"
        return f"{self.sym}{x:,.2f}"

    def eff_text(self, x) -> str:
        if x is None:
            return "MISSING"
        return self.money(x) if self.mode == "cpa" else f"{x:.2f}"

    @staticmethod
    def pct(x) -> str:
        if x is None:
            return "MISSING"
        v = abs(x) * 100
        return f"{v:.1f}%" if v < 10 else f"{v:.0f}%"

    def metric(self) -> str:
        return "CPA" if self.mode == "cpa" else "ROAS"

    # Comparisons: "better" means lower CPA or higher ROAS.
    def better_or_equal(self, x, limit) -> bool:
        return x <= limit + 1e-9 if self.mode == "cpa" else x >= limit - 1e-9

    def worse(self, x, limit) -> bool:
        return not self.better_or_equal(x, limit)

    def gap(self, x, limit) -> str:
        """'40% above break-even' style text."""
        if self.mode == "cpa":
            word = "above" if x > limit else "below"
            return f"{self.pct((x - limit) / limit)} {word}"
        word = "below" if x < limit else "above"
        return f"{self.pct((limit - x) / limit)} {word}"

    def econ_ready(self) -> bool:
        return self.T is not None or self.B is not None

    def value_of(self, c: Camp):
        return c.cpa if self.mode == "cpa" else c.roas

    def status(self, c: Camp) -> dict:
        """Efficiency of a campaign against target and break-even, with a 95% range."""
        out = {"state": "", "text": "", "confident": False}
        if c.clicks <= 0:
            out.update(state="no_clicks", text="no clicks in the window")
            return out
        if c.conv <= 0:
            if self.mode == "cpa" and self.B and c.cpc:
                be_cvr = c.cpc / self.B
                upper = zero_conv_upper(c.clicks)
                if upper is not None and upper < be_cvr:
                    out.update(state="zero_losing", confident=True,
                               text=f"0 conversions in {c.clicks:.0f} clicks ({self.money(c.cost)}); the data rules out converting at break-even")
                    return out
            out.update(state="zero_unclear", text=f"0 conversions in {c.clicks:.0f} clicks ({self.money(c.cost)}), too few to judge")
            return out
        value = self.value_of(c)
        lo, hi = wilson(c.conv, c.clicks)
        vpc = c.value / c.conv if c.conv else 0
        if self.mode == "cpa":
            best = c.cpc / hi if hi else None
            worst = c.cpc / lo if lo else None
        else:
            best = (hi * c.clicks * vpc / c.cost) if c.cost else None
            worst = (lo * c.clicks * vpc / c.cost) if c.cost else None
        out["range"] = (best, worst)
        label = f"{self.metric()} {self.eff_text(value)} on {c.conv:g} conversions"
        if self.B is not None and self.worse(value, self.B):
            out.update(state="above_be", text=f"{label}, {self.gap(value, self.B)} {self.limit_name} {self.eff_text(self.B)}{self.be_note}")
            out["confident"] = best is not None and self.worse(best, self.B)
        elif self.T is not None and self.worse(value, self.T):
            out.update(state="between", text=f"{label}, above target {self.eff_text(self.T)} but within break-even {self.eff_text(self.B)}"
                       if self.mode == "cpa" else f"{label}, below target {self.eff_text(self.T)} but within break-even {self.eff_text(self.B)}")
        elif self.T is not None:
            out.update(state="good", text=f"{label}, {'at or under' if self.mode == 'cpa' else 'at or over'} target {self.eff_text(self.T)}")
            out["confident"] = worst is not None and self.B is not None and self.better_or_equal(worst, self.B)
        else:
            out.update(state="no_target", text=f"{label}; target MISSING")
        return out

    def budget_state(self, c: Camp):
        thr, use_thr = self.args.budget_lost_threshold, self.args.budget_use_threshold
        parts = []
        if c.lost_budget is not None:
            parts.append(f"lost {self.pct(c.lost_budget)} of impression share to budget")
        if c.use is not None:
            parts.append(f"spent {self.pct(c.use)} of its daily budget on average")
        text = " and ".join(parts)
        if c.lost_budget is not None and c.lost_budget >= thr:
            return "limited", text
        if c.constrained:
            return "limited", (text + "; Google marks it budget-constrained").strip("; ")
        if c.use is not None and c.use >= use_thr:
            return "limited", text
        if parts:
            return "not_limited", text
        return "unknown", "no impression share or budget data"

    def estimate(self, r: dict) -> dict:
        bc, pc = num(r.get("base_cost")), num(r.get("potential_cost"))
        bv, pv = num(r.get("base_conversions")), num(r.get("potential_conversions"))
        bval, pval = num(r.get("base_conversion_value")), num(r.get("potential_conversion_value"))
        out = {"text": "", "marginal": None, "extra_cost": None, "no_gain": False}
        if bc is None or pc is None:
            return out
        dc = pc - bc
        out["extra_cost"] = dc
        if self.mode == "cpa" and bv is not None and pv is not None:
            dconv = pv - bv
            if dconv > 0:
                out["marginal"] = dc / dconv
                out["text"] = (f"Google's estimate: {'+' if dc >= 0 else '-'}{self.money(abs(dc))} cost for "
                               f"+{dconv:.1f} conversions ({self.money(out['marginal'])} per extra conversion)")
            elif dc > 0:
                out["no_gain"] = True
                out["text"] = f"Google's estimate: +{self.money(dc)} cost with no extra conversions"
        elif self.mode == "roas" and bval is not None and pval is not None and dc > 0:
            out["marginal"] = (pval - bval) / dc
            out["text"] = (f"Google's estimate: +{self.money(dc)} cost for +{self.money(pval - bval)} value "
                           f"(ROAS {out['marginal']:.2f} on the extra spend)")
        return out

    def capped(self, current, proposed, limit):
        if current is None or proposed is None or current <= 0:
            return proposed, False
        hi, lo = current * (1 + limit), current * (1 - limit)
        if proposed > hi:
            return round(hi, 2), True
        if proposed < lo:
            return round(lo, 2), True
        return round(proposed, 2), False


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, rec: dict, kind: str):
        self.rec = rec
        self.kind = kind
        self.verdict = "hold"
        self.reason = ""
        self.route = "hold"
        self.changes: list[dict] = []
        self.steps: list[str] = []
        self.test: dict = {}
        self.estimate = ""
        self.review_on = ""
        self.sequence = ""
        self.reviewed = ""

    def set(self, verdict: str, reason: str, route: str = ""):
        self.verdict = verdict
        self.reason = reason
        self.route = route or {"accept": "interface", "reject": "dismiss", "test": "experiment", "hold": "hold"}[verdict]
        return self


def resolve_kind(rec: dict) -> str:
    t = (rec.get("type") or "").strip().upper()
    if t in TYPE_TO_KIND:
        return TYPE_TO_KIND[t]
    name = (rec.get("name") or rec.get("type") or "").lower().replace("_", " ")
    for pattern, kind in UI_PATTERNS:
        if re.search(pattern, name):
            return kind
    return "other"


class Triage:
    def __init__(self, ctx: Context, judge: Judge, args, by_id, by_name, keywords, negatives, ads):
        self.ctx, self.j, self.args = ctx, judge, args
        self.by_id, self.by_name = by_id, by_name
        self.keywords, self.negatives, self.ads = keywords, negatives, ads
        self.today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
        self.lag = args.conversion_lag if args.conversion_lag is not None else (ctx.lag or 0)
        self.max_budget = args.max_budget_change if args.max_budget_change is not None else ctx.max_budget_change
        self.max_target = args.max_target_change if args.max_target_change is not None else ctx.max_target_change
        self.counter = 0
        self.account = self._account_camp()

    def _account_camp(self):
        rows = list({id(v): v for v in list(self.by_id.values()) + list(self.by_name.values())}.values())
        if not rows:
            return None
        total = {k: sum(num(r.get(k)) or 0.0 for r in rows) for k in ADDITIVE}
        total["campaign"] = "All campaigns"
        return Camp(total, self.args.days)

    def camp(self, rec: dict):
        row = None
        if rec.get("campaign_id") and rec["campaign_id"] in self.by_id:
            row = self.by_id[rec["campaign_id"]]
        elif rec.get("campaign") and rec["campaign"].lower() in self.by_name:
            row = self.by_name[rec["campaign"].lower()]
        return Camp(row, self.args.days) if row else None

    def review(self, kind: str) -> str:
        days = REVIEW_DAYS.get(kind, 14) + (self.lag if kind in BIDDING_KINDS else 0)
        return (self.today + dt.timedelta(days=days)).isoformat()

    def change(self, res: Result, entry: dict, evidence: str, effect: str):
        self.counter += 1
        entry = {"id": f"c{self.counter}", **entry, "reason": res.reason, "evidence": evidence,
                 "expected_effect": effect, "source_recommendation": res.rec.get("rec_id", "")}
        res.changes.append(entry)
        res.route = "change_set"

    def evidence(self, c: Camp | None, extra: str = "") -> str:
        window = self.args.window or f"last {self.args.days:g} days"
        if not c:
            return f"{extra} ({window})".strip()
        base = (f"{self.j.money(c.cost)} cost, {c.clicks:.0f} clicks, {c.conv:g} conversions"
                + (f", {self.j.money(c.value)} value" if self.j.mode == "roas" else ""))
        return f"{base}{'; ' + extra if extra else ''} ({window})"

    def exp_type_for(self, c: Camp | None, default: str) -> str:
        if c is not None and c.ctype == "performance_max" and default.startswith("Custom"):
            return "Performance Max optimization experiment (where offered for this setting)"
        if c is not None and c.ctype == "shopping" and default.startswith("Custom"):
            return "Staged change (custom experiments don't support Shopping)"
        return default

    def test_plan(self, res: Result, c: Camp | None, exp_type: str, change_text: str, success: str, extra_steps=None):
        exp_type = self.exp_type_for(c, exp_type)
        conv_per_day = (c.conv / self.args.days) if (c and self.args.days) else 0.0
        split = 0.5
        need = self.args.min_test_conversions
        eval_days = EVAL_DAYS
        if conv_per_day > 0:
            eval_days = max(EVAL_DAYS, math.ceil(need / (conv_per_day * split)))
        capped = eval_days > MAX_EVAL_DAYS
        eval_days = min(eval_days, MAX_EVAL_DAYS)
        total = SETTLE_DAYS + eval_days + self.lag
        per_arm = conv_per_day * split * eval_days
        mode = "network" if exp_type.startswith("Network") else ("staged" if exp_type.startswith("Staged") else "experiment")
        arms = 2 if mode == "experiment" else 1
        if mode != "experiment" and conv_per_day > 0:
            eval_days = min(MAX_EVAL_DAYS, max(EVAL_DAYS, math.ceil(need / conv_per_day)))
            capped = need / conv_per_day > MAX_EVAL_DAYS
            total = SETTLE_DAYS + eval_days + self.lag
            per_arm = conv_per_day * eval_days
        ratio = math.exp(2.8 * math.sqrt(2 / per_arm)) if (per_arm > 0 and arms == 2) else None
        guard = (f"{self.j.metric()} in the trial arm stays {'at or under' if self.j.mode == 'cpa' else 'at or over'} "
                 f"{self.j.limit_name} {self.j.eff_text(self.j.B)}{self.j.be_note}" if self.j.B is not None else "break-even MISSING: add it before starting")
        res.test = {
            "type": exp_type, "change": change_text, "split": "50%", "duration_days": total,
            "settle_days": SETTLE_DAYS, "eval_days": eval_days, "lag_days": self.lag,
            "per_arm_conversions": round(per_arm, 1), "detectable_ratio": ratio, "mode": mode,
            "success": success, "guardrail": guard, "low_volume": capped or (per_arm < need),
            "end_on": (self.today + dt.timedelta(days=total)).isoformat(), "extra_steps": extra_steps or [],
        }
        res.review_on = res.test["end_on"]

    def success_text(self) -> str:
        if self.j.T is None:
            return "target MISSING: set the success threshold before starting"
        if self.j.mode == "cpa":
            return (f"the trial arm gets more conversions than the original at a CPA at or under target "
                    f"{self.j.eff_text(self.j.T)}")
        return (f"the trial arm earns more conversion value than the original at a ROAS at or over target "
                f"{self.j.eff_text(self.j.T)}")

    # --- kind handlers -----------------------------------------------------

    def run(self, rec: dict) -> Result:
        kind = resolve_kind(rec)
        res = Result(rec, kind)
        c = self.camp(rec)
        est = self.j.estimate(rec)
        res.estimate = est["text"]
        handler = getattr(self, f"k_{kind}", self.k_other)
        handler(res, c, est)
        if res.verdict == "accept" and not res.review_on:
            res.review_on = self.review(kind)
        return res

    def common_gates(self, res: Result, c: Camp | None, need_econ=True, need_camp=True, tracking=False) -> bool:
        """Return True when a hold or reject was set and the handler should stop."""
        if need_camp and c is None:
            res.set("hold", "No performance data for this campaign in the pull. Pull campaign data for the same window, then re-run.")
            return True
        if need_econ and not self.j.econ_ready():
            res.set("hold", "The Economics section has no target or break-even (MISSING). Add them, then re-run.")
            return True
        if tracking and self.ctx.tracking == "concern":
            res.set("hold", f"Known tracking problem on a primary conversion ({self.ctx.tracking_note}). "
                            "Fix it first: this change leans on conversion data.")
            return True
        if c is not None and c.learning and KINDS[res.kind][2]:
            res.set("hold", "The bid strategy is still learning. Judge this after learning ends, so the numbers mean something.")
            return True
        return False

    def k_raise_budget(self, res, c, est):
        if self.common_gates(res, c):
            return
        st, (bs, bs_text) = self.j.status(c), self.j.budget_state(c)
        cur = num(res.rec.get("current_budget")) or c.budget
        rec_b = num(res.rec.get("recommended_budget"))
        lead = "Budget-limited, but " if bs == "limited" else ""
        if st["state"] == "above_be":
            return res.set("reject", f"{lead}{st['text']}, so more budget buys more {self.j.loss}.")
        if st["state"] == "zero_losing":
            return res.set("reject", f"{st['text']}. More budget buys more of the same.")
        if st["state"] in ("zero_unclear", "no_clicks"):
            return res.set("reject", f"{st['text'].capitalize()}. Prove the campaign converts before giving it more money.")
        if bs == "not_limited":
            return res.set("reject", f"Not budget-limited: it {bs_text}. A bigger budget would mostly go unused or buy weaker traffic.")
        if est["no_gain"]:
            return res.set("reject", f"{est['text']}.")
        if est["marginal"] is not None and self.j.B is not None and self.j.worse(est["marginal"], self.j.B):
            return res.set("reject", f"{lead}{est['text']}, {self.j.gap(est['marginal'], self.j.B)} {self.j.limit_name} "
                                     f"{self.j.eff_text(self.j.B)}{self.j.be_note}. The extra spend buys {self.j.loss}.")
        between_note = ""
        if st["state"] == "between":
            if est["marginal"] is not None and self.j.better_or_equal(est["marginal"], self.j.T):
                between_note = (f" The average is past target, but Google's estimate puts the extra conversions at "
                                f"{self.j.eff_text(est['marginal'])}, within target.")
            else:
                return res.set("reject", f"{st['text']}. Extra budget usually costs more per conversion than the average, so improve efficiency first.")
        if st["state"] == "no_target":
            return res.set("hold", f"{st['text']}. Add the target to the Economics section, then re-run.")
        if bs == "unknown":
            return res.set("hold", "Can't tell whether it's budget-limited: no impression share or budget data. Pull them, then re-run.")
        if rec_b is None or cur is None:
            res.set("accept", f"Budget-limited ({bs_text}) and {st['text']}. Google's suggested amount wasn't in the data: use it only within your limit of {self.j.pct(self.max_budget)} per step.")
            res.steps = [f"Campaigns, open '{c.name}', Settings, Budget: raise it by no more than {self.j.pct(self.max_budget)}, then Save."]
            return
        step_target = rec_b
        half = ""
        if est["marginal"] is not None and self.j.T is not None and self.j.worse(est["marginal"], self.j.T):
            step_target = cur + (rec_b - cur) / 2
            half = " Google's estimate puts extra conversions above target, so this takes half the suggested increase."
        new, was_capped = self.j.capped(cur, step_target, self.max_budget)
        cap_note = (f" Google suggested {self.j.money(rec_b)}; this step goes to {self.j.money(new)}, the most your "
                    f"{self.j.pct(self.max_budget)} limit allows per batch." if was_capped else "")
        low = "" if (st["confident"] or st["state"] != "good") else f" Volume is low ({c.conv:g} conversions), so the result could be off: review it on time."
        shared = " Shared budget: this changes every campaign that uses it." if c.shared else ""
        res.set("accept", f"Budget-limited ({bs_text}) and {st['text']}.{between_note}{half}{cap_note}{low}{shared}".strip())
        self.change(res, {"action": "set_budget", "campaign": c.name, "from": round(cur, 2), "to": new},
                    self.evidence(c, bs_text + (f"; {est['text']}" if est["text"] else "")),
                    "More conversions at a CPA near the current one" if self.j.mode == "cpa" else "More conversion value at a ROAS near the current one")
        res.steps = [f"Campaigns, open '{c.name}', Settings, Budget: change {self.j.money(cur)} to {self.j.money(new)}, then Save."]

    def k_move_budget(self, res, c, est):
        if self.common_gates(res, c):
            return
        st, (bs, bs_text) = self.j.status(c), self.j.budget_state(c)
        if st["state"] in ("above_be", "zero_losing"):
            return res.set("reject", f"The campaign that would get the money: {st['text']}. Moving budget to it moves money into a loss.")
        if st["state"] != "good":
            return res.set("reject", f"The campaign that would get the money: {st['text']}. Fix efficiency before feeding it more.")
        if bs == "not_limited":
            return res.set("reject", f"The receiving campaign isn't budget-limited ({bs_text}).")
        src_name = res.rec.get("source_campaign", "")
        src = self.by_name.get(src_name.lower()) if src_name else None
        cur = num(res.rec.get("current_budget")) or c.budget
        rec_b = num(res.rec.get("recommended_budget"))
        res.set("accept", f"The receiving campaign is budget-limited ({bs_text}) and {st['text']}. Total spend stays the same.")
        if src and cur and rec_b:
            s = Camp(src, self.args.days)
            if s.use is not None and s.use >= self.args.budget_use_threshold:
                return res.set("reject", f"The campaign that would give up budget ('{s.name}') spent {self.j.pct(s.use)} of its budget on average, so the budget isn't unused.")
            new_to, capped_to = self.j.capped(cur, rec_b, self.max_budget)
            delta = new_to - cur
            if s.budget:
                delta = min(delta, round(s.budget * self.max_budget, 2))
                new_to = round(cur + delta, 2)
            if s.budget and s.budget - delta > 0:
                self.change(res, {"action": "set_budget", "campaign": c.name, "from": round(cur, 2), "to": new_to},
                            self.evidence(c, bs_text), "Same total spend, more of it where conversions are cheaper")
                self.change(res, {"action": "set_budget", "campaign": s.name, "from": round(s.budget, 2), "to": round(s.budget - delta, 2)},
                            self.evidence(s, f"spent {self.j.pct(s.use)} of its daily budget" if s.use is not None else ""),
                            "Releases budget the campaign wasn't spending")
                res.steps = [f"Campaigns, open '{s.name}', Settings, Budget: lower it to {self.j.money(s.budget - delta)}.",
                             f"Open '{c.name}', Settings, Budget: raise it to {self.j.money(new_to)}."]
                return
        res.steps = ["Open the recommendation card, check which campaign gives up budget, and move the amount by hand in each campaign's Budget setting."]

    def k_target_loosen(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        cur = num(res.rec.get("current_target"))
        mult = num(res.rec.get("target_multiplier"))
        new = cur * mult if (cur and mult) else num(res.rec.get("recommended_target"))
        if new is None:
            return res.set("hold", "The suggested new target wasn't in the data. Open the card, note the current and suggested targets, add them, and re-run.")
        txt = self.j.eff_text
        if self.j.B is not None and self.j.worse(new, self.j.B):
            return res.set("reject", f"New target {txt(new)} is {self.j.gap(new, self.j.B)} {self.j.limit_name} {txt(self.j.B)}{self.j.be_note}: "
                                     f"Google would be allowed to buy {self.j.loss}.")
        if self.j.T is not None and self.j.worse(new, self.j.T):
            res.set("test", f"New target {txt(new)} is past your target {txt(self.j.T)} but within break-even {txt(self.j.B)}. "
                            "It may buy more conversions at a worse cost: test it before committing.")
            self.test_plan(res, c, "Custom experiment", f"Bid strategy target changed from {txt(cur)} to {txt(new)}", self.success_text())
            return
        if self.j.T is None:
            return res.set("hold", "Target MISSING in Economics, so a looser target can't be checked. Add it, then re-run.")
        res.set("accept", f"New target {txt(new)} stays within your target {txt(self.j.T)}.")
        if cur:
            to, was_capped = self.j.capped(cur, new, self.max_target)
            if was_capped:
                res.reason += f" Your {self.j.pct(self.max_target)} limit makes this step {txt(to)}; repeat after review if it holds."
            self.change(res, {"action": "set_target", "campaign": c.name, "target_type": self.j.mode, "from": round(cur, 2), "to": to},
                        self.evidence(c, f"Google suggests a target of {txt(new)}"), "More volume while staying within target")
            res.steps = [f"Campaigns, open '{c.name}', Settings, Bidding: change the target {self.j.metric()} from {txt(cur)} to {txt(to)}."]

    def k_target_set(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        rt = num(res.rec.get("recommended_target"))
        txt = self.j.eff_text
        if self.j.mode == "roas" and c.conv_30 is not None and c.conv_30 < ROAS_MIN_CONV_30D:
            return res.set("reject", f"{c.conv_30:.0f} conversions per 30 days. Google's Smart Bidding guidance asks for about "
                                     f"{ROAS_MIN_CONV_30D} with values before a target ROAS.")
        if rt is None:
            return res.set("hold", "The suggested target wasn't in the data. Add it from the card and re-run.")
        if self.j.B is not None and self.j.worse(rt, self.j.B):
            return res.set("reject", f"Suggested target {txt(rt)} is {self.j.gap(rt, self.j.B)} {self.j.limit_name} {txt(self.j.B)}{self.j.be_note}.")
        actual = self.j.value_of(c)
        if self.j.T is not None and self.j.worse(rt, self.j.T):
            res.set("test", f"Suggested target {txt(rt)} is past your target {txt(self.j.T)} (within break-even). Test it first.")
            self.test_plan(res, c, "Custom experiment", f"Add a target {self.j.metric()} of {txt(rt)}", self.success_text())
            return
        if actual is not None and self.j.worse(actual, rt):
            res.set("test", f"Suggested target {txt(rt)} is tighter than the campaign's actual {self.j.metric()} {txt(actual)}. "
                            "It could cut volume: test it.")
            self.test_plan(res, c, "Custom experiment", f"Add a target {self.j.metric()} of {txt(rt)}", self.success_text())
            return
        if self.j.T is None:
            return res.set("hold", "Target MISSING in Economics. Add it, then re-run.")
        res.set("accept", f"Suggested target {txt(rt)} is within your target {txt(self.j.T)} and no tighter than actual "
                          f"{self.j.metric()} {txt(actual)}.")
        own = c.own_target_cpa if self.j.mode == "cpa" else c.own_target_roas
        if own:
            to, _ = self.j.capped(own, rt, self.max_target)
            self.change(res, {"action": "set_target", "campaign": c.name, "target_type": self.j.mode, "from": round(own, 2), "to": to},
                        self.evidence(c), "Bidding aims at a target the business can afford")
        else:
            res.steps = [f"Campaigns, open '{c.name}', Settings, Bidding: keep the strategy and set the optional target {self.j.metric()} to {txt(rt)}."]

    def k_smart_bidding_switch(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        t = (res.rec.get("type") or "").upper()
        if c.bid in CONVERSION_BIDDING:
            return res.set("reject", f"Already bids on conversions ({bid_name(c.bid)}).")
        if c.conv <= 0:
            return res.set("reject", f"No conversions in the window ({c.clicks:.0f} clicks). Smart Bidding has nothing to learn from.")
        value_based = t in VALUE_TYPES or "value" in (res.rec.get("name") or "").lower() or "roas" in (res.rec.get("name") or "").lower()
        if value_based and c.value <= 0:
            return res.set("reject", "No conversion values recorded, so value-based bidding can't work.")
        if value_based and c.conv_30 is not None and c.conv_30 < ROAS_MIN_CONV_30D:
            return res.set("reject", f"{c.conv_30:.0f} conversions per 30 days. Google's guidance asks for about {ROAS_MIN_CONV_30D} with values for target ROAS.")
        rt = num(res.rec.get("recommended_target"))
        if rt is not None and self.j.B is not None and self.j.worse(rt, self.j.B):
            return res.set("reject", f"Google's suggested target {self.j.eff_text(rt)} is {self.j.gap(rt, self.j.B)} {self.j.limit_name} {self.j.eff_text(self.j.B)}{self.j.be_note}.")
        st = self.j.status(c)
        strategy = (res.rec.get("name") or t.replace("_OPT_IN", "").replace("_", " ").lower()).strip()
        res.set("test", f"Switching from {bid_name(c.bid)} changes how the campaign spends. "
                        f"Now: {st['text']}. Test it before switching the whole campaign.")
        target_note = ""
        if self.j.T is not None:
            target_note = f" with a target {self.j.metric()} of {self.j.eff_text(self.j.T if rt is None or self.j.worse(rt, self.j.T) else rt)}"
        self.test_plan(res, c, "Custom experiment", f"Bid strategy: {strategy}{target_note}", self.success_text())

    def k_clicks_bidding(self, res, c, est):
        name = (res.rec.get("name") or "").lower()
        if "impression share" in name:
            cname = (c.name if c else res.rec.get("campaign", "")).lower()
            if "brand" in cname or cname in self.ctx.brand_campaigns:
                return res.set("hold", "Target impression share bids for visibility, not conversions. It can suit brand defense: your call.")
            return res.set("reject", "Target impression share bids for visibility, not conversions. It doesn't fit a non-brand campaign.")
        if self.common_gates(res, c, need_econ=False):
            return
        if c.conv > 0 or self.ctx.primary_actions:
            return res.set("reject", f"Maximize clicks buys the cheapest clicks, not the conversions you track ({c.conv:g} in the window).")
        return res.set("hold", "No conversions tracked. Fix tracking first; if traffic is truly the goal, it's your call.")

    def k_bidding_exploration(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        st = self.j.status(c)
        if st["state"] != "good":
            return res.set("reject", f"{st['text']}. Exploration accepts weaker returns on new searches, which widens the gap.")
        res.set("test", f"{st['text']}. Exploration trades efficiency for new searches: test it.")
        self.test_plan(res, c, "Custom experiment (if offered for this setting)", "Turn on Smart Bidding Exploration", self.success_text())

    def k_broad_match(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        if c.bid not in CONVERSION_BIDDING:
            return res.set("reject", f"The campaign uses {bid_name(c.bid)}. Google pairs broad match "
                                     "with Smart Bidding; without it, broad match buys loose searches at manual bids.")
        st, (bs, bs_text) = self.j.status(c), self.j.budget_state(c)
        req = num(res.rec.get("required_budget"))
        budget_note = ""
        if req and c.budget and req > c.budget:
            budget_note = f" Google says it would also need a budget of {self.j.money(req)} ({self.j.pct((req - c.budget) / c.budget)} more)."
        if st["state"] in ("above_be", "zero_losing", "zero_unclear", "no_clicks", "between"):
            return res.set("reject", f"{st['text']}. Broad match adds looser, usually costlier searches.{budget_note}")
        if bs == "limited":
            return res.set("reject", f"Already budget-limited ({bs_text}); broad match would spread the same budget over looser searches.{budget_note}")
        res.set("test", f"{st['text']}, not budget-limited. Broad match mainly raises reach and spend: test it.{budget_note}")
        self.test_plan(res, c, "Custom experiment", "Keywords switched to broad match in the trial arm", self.success_text(),
                       ["Check the trial arm's search terms weekly and add negatives for anything off-offer."])

    def k_ai_max(self, res, c, est):
        if self.common_gates(res, c, tracking=True):
            return
        if c.bid not in CONVERSION_BIDDING:
            return res.set("reject", f"AI Max relies on Smart Bidding; this campaign uses {bid_name(c.bid)}.")
        st, (bs, bs_text) = self.j.status(c), self.j.budget_state(c)
        if st["state"] in ("above_be", "zero_losing", "zero_unclear", "no_clicks", "between"):
            return res.set("reject", f"{st['text']}. AI Max widens matching and lets Google pick landing pages and write text, which adds spend before efficiency is fixed.")
        if bs == "limited":
            return res.set("reject", f"Budget-limited ({bs_text}). AI Max would spread the same budget over wider matching.")
        extra = ["Before starting, add URL exclusions for pages that don't sell (careers, blog, login, support)."]
        if self.ctx.restricted or self.ctx.disclaimers:
            extra.append("Your context lists a restricted category or required disclaimers: keep text customization and final URL expansion off in the trial, or use text disclaimers.")
        exp = "AI Max experiment"
        if c.shared:
            exp = "Custom experiment (AI Max experiments aren't offered for campaigns with shared budgets)"
            extra.append("Google's AI Max experiment flow excludes shared budgets and portfolio strategies.")
        res.set("test", f"{st['text']}, not budget-limited. AI Max expands matching and spend; independent tests have found worse CPA than exact and phrase, so test it.")
        self.test_plan(res, c, exp, "AI Max on in the trial arm", self.success_text(),
                       extra + ["Review the trial's search terms and landing pages weekly."])

    def k_add_keywords(self, res, c, est):
        kw = (res.rec.get("keyword") or "").strip()
        if not kw:
            return res.set("hold", "The suggested keyword wasn't in the data. Add it from the card and re-run.")
        if not self.keywords:
            return res.set("hold", f"'{kw}': pull the keyword list (and negatives) first, so duplicates and blocking negatives can be checked.")
        if not self.j.econ_ready():
            return res.set("hold", f"'{kw}' adds reach and spend, and the Economics section has no target or break-even (MISSING) to judge the campaign against.")
        words = tokens(kw)
        for term in self.ctx.unwanted:
            if contains_phrase(words, tokens(term)):
                return res.set("reject", f"'{kw}' contains '{term}', listed under Terms we don't want.")
        camp_name = (c.name if c else res.rec.get("campaign", "")).lower()
        group = (res.rec.get("ad_group") or "").lower()
        for k in self.keywords:
            if norm_text(k.get("keyword")) == norm_text(kw) and (k.get("campaign", "").lower() == camp_name or not camp_name):
                return res.set("reject", f"'{kw}' is already in the account as {k.get('match_type', '')} in ad group '{k.get('ad_group', '')}'.")
        for n in self.negatives:
            if n.get("campaign", "").lower() != camp_name:
                continue
            if n.get("ad_group") and n.get("ad_group", "").lower() != group:
                continue
            if negative_blocks(tokens(n.get("keyword", "")), (n.get("match_type") or "broad").lower(), words):
                return res.set("reject", f"The negative '{n.get('keyword')}' ({n.get('match_type')}) blocks '{kw}', so it couldn't serve.")
        if c is not None:
            st = self.j.status(c) if self.j.econ_ready() else {"state": "", "text": ""}
            if st["state"] in ("above_be", "zero_losing"):
                return res.set("reject", f"Campaign: {st['text']}. More keywords add more of the same.")
        match = (res.rec.get("match_type") or "phrase").lower()
        note = ""
        if match not in ("exact", "phrase"):
            note = " Google suggested broad; this adds it as phrase to keep control (test broad separately)."
            match = "phrase"
        if not res.rec.get("ad_group") or not (c or res.rec.get("campaign")):
            res.set("hold", f"'{kw}' passed the checks, but the campaign or ad group name is missing. Add it and re-run.")
            return
        st_txt = f" Campaign: {self.j.status(c)['text']}." if c else " Campaign efficiency not checked (no campaign data)."
        passed, unchecked = ["isn't in the account"], []
        (passed if self.negatives else unchecked).append("isn't blocked by a negative" if self.negatives else "blocking negatives (not pulled)")
        (passed if self.ctx.unwanted else unchecked).append("has no unwanted terms" if self.ctx.unwanted else "unwanted terms (Terms we don't want is MISSING)")
        passed_txt = ", ".join(passed[:-1]) + (", and " if len(passed) > 1 else "") + passed[-1]
        unchecked_txt = f" Not checked: {'; '.join(unchecked)}." if unchecked else ""
        res.set("accept", f"'{kw}' {passed_txt}.{unchecked_txt}{st_txt}{note} Added paused; "
                          "confirm it names something you sell before enabling.")
        terms = res.rec.get("search_terms", "")
        self.change(res, {"action": "add_keyword", "campaign": c.name if c else res.rec.get("campaign"),
                          "ad_group": res.rec.get("ad_group"), "keyword": kw, "match_type": match, "status": "paused"},
                    self.evidence(c, f"Google's suggestion{'; matches searches such as ' + terms if terms else ''}"),
                    "New relevant searches at a CPA near the ad group's")
        res.steps = [f"Campaigns, open '{res.rec.get('ad_group')}' in '{c.name if c else res.rec.get('campaign')}', Keywords, plus button: "
                     f"add {kw} as {match} match, then pause it until you've reviewed it."]

    def k_remove_keywords(self, res, c, est):
        kw = (res.rec.get("keyword") or "").strip()
        if not kw:
            return res.set("hold", "The card's keyword list wasn't in the data. Open the card, list the keywords, and re-run.")
        camp_name = (c.name if c else res.rec.get("campaign", "")).lower()
        group = (res.rec.get("ad_group") or "").lower()
        match = (res.rec.get("match_type") or "").lower()
        rows = [k for k in self.keywords if norm_text(k.get("keyword")) == norm_text(kw)
                and k.get("campaign", "").lower() == camp_name and (not group or k.get("ad_group", "").lower() == group)
                and (not match or (k.get("match_type") or "").lower() == match)]
        if not rows:
            return res.set("hold", f"No performance data for '{kw}' in the keyword pull. Pull keywords for the window, then re-run.")
        k = rows[0]
        imp, conv = num(k.get("impressions")) or 0, num(k.get("conversions")) or 0
        if conv > 0:
            return res.set("reject", f"'{kw}' converted {conv:g} times in the window. Keep it.")
        if imp > 0:
            return res.set("reject", f"'{kw}' served {imp:.0f} impressions in the window. Removing it changes which keyword catches those searches; leave it unless you have a reason.")
        res.set("accept", f"'{kw}' had 0 impressions in the window. Pause it (never delete) so it can come back if needed.")
        self.change(res, {"action": "set_status", "entity": "keyword", "campaign": k.get("campaign"), "ad_group": k.get("ad_group"),
                          "keyword": kw, "match_type": k.get("match_type"), "from": "enabled", "to": "paused"},
                    self.evidence(None, f"'{kw}': 0 impressions"), "Tidier account with no change in traffic")
        res.steps = [f"Keywords, find '{kw}' in '{k.get('ad_group')}', Status: Pause. Don't use the card's Apply button: it removes the keyword."]

    def k_conflicting_negatives(self, res, c, est):
        neg = (res.rec.get("negative_keyword") or "").strip()
        kw = (res.rec.get("keyword") or "").strip()
        if not neg or not kw:
            return res.set("hold", "The card's negative and the keyword it blocks weren't in the data. Add both and re-run.")
        for term in self.ctx.unwanted:
            if contains_phrase(tokens(neg), tokens(term)) or contains_phrase(tokens(term), tokens(neg)):
                return res.set("reject", f"The negative '{neg}' matches '{term}' from Terms we don't want. Keep it; pause the keyword '{kw}' instead.")
        for term in self.ctx.protected:
            if contains_phrase(tokens(kw), tokens(term)):
                res.set("accept", f"The negative '{neg}' blocks '{kw}', which contains the protected term '{term}'. Remove the negative.")
                camp_name = c.name if c else res.rec.get("campaign", "")
                nmatch = (res.rec.get("negative_match_type") or "").lower()
                found = [n for n in self.negatives if n.get("campaign", "").lower() == camp_name.lower()
                         and norm_text(n.get("keyword")) == norm_text(neg) and (not nmatch or (n.get("match_type") or "").lower() == nmatch)]
                where = f"in '{camp_name}'"
                if found and not found[0].get("shared_set"):
                    n = found[0]
                    level = "ad_group" if n.get("ad_group") else "campaign"
                    entry = {"action": "remove_negative", "level": level, "campaign": camp_name, "keyword": neg,
                             "match_type": (n.get("match_type") or nmatch or "broad").lower()}
                    if level == "ad_group":
                        entry["ad_group"] = n.get("ad_group")
                        where = f"in ad group '{n.get('ad_group')}'"
                    self.change(res, entry, self.evidence(None, f"negative '{neg}' blocks protected keyword '{kw}'"),
                                "The protected keyword can serve again")
                    res.steps = [f"Campaigns, open '{camp_name}', Keywords, Negative search keywords: find '{neg}' {where} and remove it."]
                else:
                    res.steps = [f"Find where the negative '{neg}' lives (campaign, ad group, or a negative keyword list) and remove it there. "
                                 "It wasn't in the negatives pull, so it isn't in the change set."]
                return
        return res.set("reject", f"Keep the negative '{neg}': it was most likely added on purpose, and removing it reopens those searches. "
                                 f"'{kw}' can't serve anyway; pause it, or tell me the negative was a mistake.")

    def reach_gate(self, res, c, what: str) -> bool:
        st, (bs, bs_text) = self.j.status(c), self.j.budget_state(c)
        if bs == "limited":
            res.set("reject", f"Budget-limited ({bs_text}). The budget doesn't cover Google Search yet, so {what} would take money from it.")
            return True
        if st["state"] == "no_target":
            res.set("hold", f"{st['text']}. Add the target to the Economics section, then re-run.")
            return True
        if st["state"] != "good":
            res.set("reject", f"{st['text']}. Wider reach on a campaign missing its target widens the gap.")
            return True
        return False

    def k_network_expansion(self, res, c, est):
        if self.common_gates(res, c):
            return
        text = ((res.rec.get("type") or "") + " " + (res.rec.get("name") or "")).lower()
        what = "Display" if "display" in text else ("video partners" if "video" in text else "search partners")
        if self.reach_gate(res, c, f"{what} traffic"):
            return
        st = self.j.status(c)
        res.set("test", f"{st['text']} and not budget-limited. {what.capitalize()} adds reach and spend outside Google Search: test it on this one campaign.")
        self.test_plan(res, c, "Network test (settings change on one campaign, read by network segment)",
                       f"Turn on {what} for '{c.name}' only",
                       f"{what.capitalize()} rows (Segment, Network) reach a {self.j.metric()} at or "
                       f"{'under' if self.j.mode == 'cpa' else 'over'} target {self.j.eff_text(self.j.T)}" if self.j.T is not None else "target MISSING",
                       ["If the Experiments page offers this setting for the campaign, run it as a custom experiment instead."])

    def k_audience_expansion(self, res, c, est):
        if self.common_gates(res, c):
            return
        if self.reach_gate(res, c, "new audiences"):
            return
        st = self.j.status(c)
        res.set("test", f"{st['text']} and not budget-limited. Audience expansion adds reach and spend: test it.")
        self.test_plan(res, c, "Custom experiment (where offered for this campaign type)", "Audience or optimized targeting expansion on", self.success_text())

    def k_url_expansion(self, res, c, est):
        if self.ctx.restricted or self.ctx.disclaimers:
            return res.set("reject", "Your context lists a restricted category or required disclaimers. Final URL expansion lets Google send clicks to any page and write text for it.")
        if self.common_gates(res, c):
            return
        st = self.j.status(c)
        if st["state"] != "good":
            return res.set("reject", f"{st['text']}. Fix efficiency before letting Google choose landing pages.")
        res.set("test", f"{st['text']}. URL expansion sends traffic to pages Google picks: test it with URL exclusions set.")
        self.test_plan(res, c, "Performance Max optimization experiment (Final URL expansion)", "Final URL expansion on", self.success_text(),
                       ["Add URL exclusions for pages that don't sell before starting."])

    def k_pmax_adopt(self, res, c, est):
        if self.common_gates(res, None, tracking=True, need_camp=False):
            return
        a = self.account
        if a is None:
            return res.set("hold", "No campaign data in the pull to judge the account. Pull it, then re-run.")
        st = self.j.status(a)
        if st["state"] in ("above_be", "zero_losing", "zero_unclear", "no_clicks"):
            return res.set("reject", f"Account: {st['text']}. A new automated campaign adds spend before the basics work.")
        t = (res.rec.get("type") or "").upper()
        exp = "Performance Max upgrade experiment" if ("MIGRATE" in t or "UPGRADE" in t or "upgrade" in (res.rec.get("name") or "").lower()) else "Performance Max uplift experiment"
        note = ""
        if "DYNAMIC_SEARCH_ADS" in t:
            note = " Google is moving Dynamic Search Ads into AI Max for Search from February 2027, so compare that route too."
        res.set("test", f"Account: {st['text']}. Performance Max needs its own budget and can take brand and Search traffic: test the gain first.{note}")
        self.test_plan(res, a, exp, "Add or upgrade to Performance Max", self.success_text().replace("the trial arm", "the account with Performance Max"),
                       ["Watch brand campaign conversions: a drop there means Performance Max is taking traffic you already had."])

    def k_new_customers(self, res, c, est):
        return res.set("hold", "Bids more for new customers. It needs a value for a new customer (or a reason to pay more for one) that the context file doesn't hold. Give that, then test it.")

    def k_shopping_expand(self, res, c, est):
        if c is not None and self.j.econ_ready():
            st = self.j.status(c)
            if st["state"] in ("above_be", "zero_losing"):
                return res.set("reject", f"{st['text']}. More products won't fix a campaign that's losing money.")
        return res.set("hold", "Adds products to Shopping. Accept only for products you're happy to sell at break-even: which products are these?")

    def k_ads_improve(self, res, c, est):
        t = (res.rec.get("type") or "").upper()
        group = res.rec.get("ad_group", "")
        if group and self.ads:
            good = [a for a in self.ads if a.get("ad_group", "").lower() == group.lower()
                    and (a.get("ad_status") or "enabled").lower() == "enabled"
                    and (a.get("ad_strength") or "").lower() in ("good", "excellent")]
            if len(good) >= 2 and "RESPONSIVE" in t:
                return res.set("reject", f"Ad group '{group}' already has {len(good)} enabled responsive search ads rated Good or Excellent, which is what Google recommends.")
        if not self.ctx.offer_known:
            return res.set("hold", "Needs approved offers and proof points to write new copy (Business and offer is MISSING). Never use Google's suggested text unchecked.")
        res.set("accept", "Better ads cost nothing extra. Write the new text from your approved offers and proof, not Google's suggested wording.", "copy")
        if "PERFORMANCE_MAX" in t or "DEMAND_GEN" in t or "asset group" in (res.rec.get("name") or "").lower():
            res.steps = ["Write the missing headlines, descriptions, and images from approved claims.",
                         "Campaigns, open the asset group, Edit: add them, then Save. Ad Strength updates in a few days."]
        else:
            res.steps = ["Write a new responsive search ad from approved claims (a copy skill or by hand).",
                         "Add it as an add_rsa change (created paused) through google-ads-apply-changes, or in Ads, plus button.",
                         "Enable it after review, keeping the existing ad running beside it."]

    def k_assets_add(self, res, c, est):
        text = ((res.rec.get("type") or "") + " " + (res.rec.get("name") or "")).lower()
        if "lead form" in text or "lead_form" in text:
            return res.set("hold", "Lead form leads never visit your site. Accept only if your team can receive and follow up form leads quickly: your call.")
        if "price" in text and not self.ctx.prices_known:
            return res.set("hold", "Price assets need approved prices (Prices that may appear in ads is MISSING).")
        if not self.ctx.offer_known and ("sitelink" in text or "callout" in text or "snippet" in text):
            return res.set("hold", "Needs approved offers or proof to write the asset text (Business and offer is MISSING).")
        extra = ""
        if "call" in text and "callout" not in text:
            extra = f" Set the asset schedule to your hours ({self.ctx.hours or 'MISSING in Geography and schedule'})."
        res.set("accept", f"Assets add room and options at no extra cost. Write the text from approved facts, not Google's suggestions.{extra}")
        res.steps = ["Write the asset text from approved offers and proof, with the landing page URLs you choose.",
                     "Campaigns, open the campaign, Assets, plus button: add the assets at campaign level, then Save.",
                     "A connector that creates assets (Google's official server can) still needs them linked to the campaign in the interface."]

    def k_auto_content(self, res, c, est):
        text = ((res.rec.get("type") or "") + " " + (res.rec.get("name") or "")).lower()
        if self.ctx.restricted or self.ctx.disclaimers:
            return res.set("reject", "Google would write or pick content you can't review before it shows, and your context lists a restricted category or required disclaimers.")
        if "text customi" in text:
            return res.set("test", "Text customization lets Google write ad text from your site. Test it as part of an AI Max experiment, then read every generated asset.", "experiment")
        res.set("accept", "Low risk: Google pulls images or links from your own site. Review what it picked in the asset report once a month and remove anything off-brand.")
        res.steps = ["Campaigns, open the campaign, Settings, Asset automation (or Assets): turn this on.",
                     "Once a month, check the generated assets and remove anything you don't want."]

    def k_measurement(self, res, c, est):
        text = ((res.rec.get("type") or "") + " " + (res.rec.get("name") or "")).lower()
        if "store visit" in text or "firebase" in text or "in-app" in text:
            return res.set("hold", "Only applies if you have physical stores or an app. Your call.")
        if "enhanced conversions" in text and self.ctx.restricted:
            return res.set("hold", f"Enhanced conversions sends hashed customer data to Google. Your account is in a restricted category ({self.ctx.restricted}): check your legal and consent requirements first.")
        reason = "Better measurement changes no spend and makes every other verdict more reliable. You or your site owner make this change, not an agent."
        if "data-driven" in text or "attribution" in text:
            reason += " Conversion counts will shift and bidding re-learns: log the date with the change log."
        res.set("accept", reason)
        if "data-driven" in text or "attribution" in text:
            res.steps = ["Goals, Conversions, Summary: open each primary conversion action, Edit settings, Attribution model: Data-driven, Save.",
                         "Log the change and its date: conversion counts shift from here on."]
        elif "auto-tagging" in text:
            res.steps = ["Admin, Account settings, Auto-tagging: tick Tag the URL that people click through from my ad, Save."]
        elif "enhanced conversions" in text:
            res.steps = ["Goals, Settings (or Conversions, Settings): turn on enhanced conversions and accept the customer data terms if you agree to them.",
                         "Follow the setup Google shows for your tag (Google tag, Tag Manager, or Data Manager), with whoever manages the site.",
                         "After a few days, check the conversion action's diagnostics for enhanced conversions coverage."]
        else:
            res.steps = ["Goals, Conversions: open the recommendation card for the exact steps for your site.",
                         "Make the change with whoever manages the site's tags, then confirm the conversion action shows recent conversions.",
                         "Log the change and its date."]

    def k_audience_data(self, res, c, est):
        res.set("accept", "Lists and reporting segments don't change who sees the ads or what you spend. You handle customer data uploads yourself under Google's terms.")
        res.steps = ["Tools, Shared library, Audience manager: refresh or add the list, or add segments in Observation mode only."]

    def k_ad_rotation(self, res, c, est):
        res.set("accept", "Optimized rotation changes no spend or targeting. Skip it only if you're running a manual ad test with even rotation.")
        res.steps = ["Campaigns, open the campaign, Settings, Ad rotation: Optimize."]

    def k_shopping_fix(self, res, c, est):
        res.set("accept", "Feed and Merchant Center fixes repair products that can't show. They change no bids or budgets.")
        res.steps = ["Open Merchant Center, Products, Needs attention: fix the listed products or attributes at the source feed."]

    def k_repair(self, res, c, est):
        res.set("accept", "This fixes something broken or disapproved. Repairs don't raise spend on their own.")
        res.steps = ["Open the recommendation card to see the affected items, fix each one, and check its status updates."]

    def k_retired(self, res, c, est):
        res.set("reject", "Retired feature: Enhanced CPC (ended March 2025), expanded text ads, Smart Shopping, and Dynamic Search Ads creation are gone or going. Dismiss it.")

    def k_other(self, res, c, est):
        label = res.rec.get("type") or res.rec.get("name") or "unknown"
        res.set("hold", f"'{label}' isn't in the rule table. Judge it with the general rules (does it raise spend, can the account afford it, can it be tested) and record the verdict as an override.")


# ---------------------------------------------------------------------------
# Overrides, sequencing, auto-apply, output
# ---------------------------------------------------------------------------

def apply_overrides(results: list[Result], path: str | None) -> None:
    if not path:
        return
    by_id = {r.rec.get("rec_id"): r for r in results}
    for row in read_csv(path):
        rid, verdict = row.get("rec_id", ""), (row.get("verdict") or "").strip().lower()
        reason, who = (row.get("reason") or "").strip(), (row.get("decided_by") or "").strip()
        res = by_id.get(rid)
        if not res:
            warn(f"override for unknown rec_id {rid}")
            continue
        if verdict not in VERDICT_RANK or not reason:
            warn(f"override for {rid} needs a verdict (accept, reject, test, hold) and a reason; skipped")
            continue
        if VERDICT_RANK[verdict] > VERDICT_RANK[res.verdict] and who.lower() in ("", "review", "claude", "agent"):
            warn(f"override for {rid} makes {res.verdict} into {verdict}; only the person can do that (set decided_by to their name); skipped")
            continue
        if verdict != "accept":
            res.changes = []
        res.reviewed = f"{verdict} by {who or 'review'}: {reason}"
        res.set(verdict, f"{reason} (was {res.verdict}: {res.reason})" if verdict != res.verdict else reason)
        if verdict == "accept" and not res.changes:
            res.route = "interface"


def sequence(results: list[Result], today: dt.date) -> None:
    per_campaign: dict[str, list[Result]] = {}
    for r in results:
        group = KINDS[r.kind][2]
        if group and r.verdict in ("accept", "test"):
            key = (r.rec.get("campaign") or r.rec.get("campaign_id") or "").lower()
            per_campaign.setdefault(key, []).append(r)
    for key, items in per_campaign.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda r: (0 if r.verdict == "accept" else 1, GROUP_ORDER[KINDS[r.kind][2]]))
        prev = items[0]
        prev_end = dt.date.fromisoformat(prev.review_on) if prev.review_on else today + dt.timedelta(days=14)
        for r in items[1:]:
            r.sequence = (f"Start after '{KINDS[prev.kind][0]}' on this campaign settles: not before {prev_end.isoformat()}. "
                          "Two changes at once make both unreadable, and only one experiment runs per campaign at a time.")
            if r.verdict == "accept" and r.changes:
                r.changes = []
                r.route = "interface"
                r.sequence += " It's left out of this change set; add it to a later batch."
            length = r.test.get("duration_days") if r.test else REVIEW_DAYS.get(r.kind, 14)
            if r.test:
                r.test["end_on"] = (prev_end + dt.timedelta(days=length)).isoformat()
            r.review_on = (prev_end + dt.timedelta(days=length)).isoformat()
            prev, prev_end = r, prev_end + dt.timedelta(days=length)


ADVICE_KEEP = {"OPTIMIZE_AD_ROTATION"}


def auto_apply_section(j: Judge, subs_path: str | None, history_path: str | None) -> list[str]:
    lines = ["## Auto-apply", ""]
    known = False
    if subs_path:
        rows = read_csv(subs_path)
        tcol = next((c for c in (rows[0] if rows else {}) if c.endswith("type") or c == "name"), None)
        scol = next((c for c in (rows[0] if rows else {}) if c.endswith("status")), None)
        enabled, paused, unknown = [], [], []
        for r in rows:
            t = (r.get(tcol) or "").strip()
            s = (r.get(scol) or "").strip().upper()
            if not t:
                continue
            if t.upper() in ("UNKNOWN", "UNSPECIFIED"):
                unknown.append(t)
            elif s in ("ENABLED", "ON", "TRUE", "YES"):
                enabled.append(t)
            else:
                paused.append(t)
        known = True
        if enabled:
            lines.append(f"**Auto-apply is on for {len(enabled)} type(s).** Google applies these without asking:")
            lines.append("")
            lines.append("| Type | What it can change | Advice |")
            lines.append("|---|---|---|")
            for t in enabled:
                kind = TYPE_TO_KIND.get(t.upper().replace(" ", "_")) or resolve_kind({"name": t})
                label, spend, _ = KINDS[kind]
                keep = t.upper() in ADVICE_KEEP or kind == "ad_rotation"
                advice = "Can stay on: it changes no spend, bids, keywords, targeting, or ad text." if keep else (
                    f"Turn off. {'It raises spend. ' if spend == 'yes' else ''}It skips the review this triage exists for.")
                lines.append(f"| {t} | {label} | {advice} |")
            lines.append("")
        else:
            lines.append("The API reports no auto-apply types turned on.")
            lines.append("")
        if unknown:
            lines.append(f"{len(unknown)} subscription(s) came back as UNKNOWN (a type this API version can't name). Check them in the interface.")
            lines.append("")
    if history_path:
        rows = read_csv(history_path)
        def tool(r):
            return (r.get("client_type") or r.get("tool") or "").lower()
        auto = [r for r in rows if "subscription" in tool(r) or "auto-apply" in tool(r) or "auto apply" in tool(r)]
        manual = [r for r in rows if "recommendation" in tool(r) and r not in auto]
        if auto:
            kinds: dict[str, int] = {}
            for r in auto:
                k = r.get("change_resource_type") or "other"
                kinds[k] = kinds.get(k, 0) + 1
            dates = sorted(r.get("change_date_time", "")[:10] for r in auto if r.get("change_date_time"))
            span = f" between {dates[0]} and {dates[-1]}" if dates else ""
            lines.append(f"**Change history shows {len(auto)} change(s) made by auto-apply{span}:** "
                         + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(kinds.items())) + ". Auto-apply is on, whatever the settings page says.")
            lines.append("")
        if manual:
            lines.append(f"Change history also shows {len(manual)} change(s) where someone clicked Apply on a recommendation.")
            lines.append("")
        if not auto and not manual:
            lines.append("Change history (last 30 days at most) shows no changes from recommendations.")
            lines.append("")
        known = True
    if not known:
        lines.append("**Unknown.** No auto-apply settings or change history were available. Check it in the interface (steps below).")
        lines.append("")
    lines.append("The API can't see every auto-apply type. Open **Campaigns, Recommendations, Auto-apply settings** and confirm these are off too: "
                 + ", ".join(UI_ONLY_AUTO_APPLY) + ".")
    lines.append("")
    lines.append("To turn one off: Recommendations, Auto-apply settings, Manage tab, uncheck it, Save. The History tab lists what auto-apply changed.")
    lines.append("")
    return lines


def score_section(j: Judge, account_score, camps: list[Camp]) -> list[str]:
    lines = ["## Optimization score", ""]
    if account_score is not None:
        s = account_score if account_score <= 1 else account_score / 100
        lines.append(f"Account optimization score: {s * 100:.0f}%.")
    scored = [c for c in camps if c.opt_score is not None]
    if scored:
        lines.append("Campaign scores: " + ", ".join(f"{c.name} {c.opt_score * 100 if c.opt_score <= 1 else c.opt_score:.0f}%" for c in scored) + ".")
    if account_score is None and not scored:
        lines.append("Score not pulled (MISSING).")
    lines.append("")
    lines.append("Optimization score measures how much of Google's own advice the account has adopted, not how well it performs. "
                 "Google calculates it from its open recommendations, and applying or dismissing them changes it. Google says Quality Score "
                 "doesn't use it. A money-losing account can score high, and a profitable one low. Dismissing the rejects above raises the "
                 "score without changing results, so don't manage to the number.")
    lines.append("")
    return lines


def md_escape(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def write_outputs(results: list[Result], j: Judge, t: Triage, args, ctx: Context, skipped: int) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["n", "rec_id", "type", "name", "kind", "campaign", "ad_group", "raises_spend", "verdict", "reason", "google_estimate",
            "route", "review_on", "sequence", "reviewed", "uplift"]
    with open(out_dir / "triage.csv", "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(cols)
        for i, r in enumerate(results, 1):
            w.writerow([i, r.rec.get("rec_id"), r.rec.get("type"), r.rec.get("name"), r.kind, r.rec.get("campaign"), r.rec.get("ad_group"),
                        KINDS[r.kind][1], r.verdict, r.reason, r.estimate, r.route, r.review_on, r.sequence, r.reviewed,
                        r.rec.get("uplift", "")])

    counts = {v: sum(1 for r in results if r.verdict == v) for v in ("accept", "reject", "test", "hold")}
    spend = [r for r in results if KINDS[r.kind][1] == "yes"]
    spend_acc = [r for r in spend if r.verdict == "accept"]
    L: list[str] = ["# Google Ads recommendations triage", ""]
    L.append(f"- **Account:** {ctx.account or 'MISSING'}")
    L.append(f"- **Window:** {args.window or 'MISSING'} ({args.days:g} days)")
    if j.econ_ready():
        L.append(f"- **Judged against:** target {j.metric()} {j.eff_text(j.T)}, break-even {j.eff_text(ctx.breakeven) if ctx.breakeven is not None else 'MISSING'} ({ctx.econ_source})")
    else:
        L.append("- **Judged against:** Economics MISSING (target and break-even unknown)")
    L.append(f"- **Limits per batch:** budget {j.pct(t.max_budget)}, target {j.pct(t.max_target)} ({ctx.limits_source})")
    L.append(f"- **Conversion tracking:** {ctx.tracking}{(': ' + ctx.tracking_note) if ctx.tracking_note else ''}; conversion delay used: {t.lag} day{'' if t.lag == 1 else 's'}")
    L.append("")
    dismissed_note = f" ({skipped} dismissed ones skipped)" if skipped else ""
    L.append(f"**{len(results)} open recommendations**{dismissed_note}: {counts['accept']} accept, {counts['reject']} reject, "
             f"{counts['test']} test, {counts['hold']} hold. **{len(spend)} of {len(results)} mainly raise spend**; {len(spend_acc)} of those are accepted.")
    L.append("")
    L.append("## Triage table")
    L.append("")
    L.append("| # | Recommendation | Campaign | Raises spend | Verdict | Reason |")
    L.append("|---|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        label = label_of(r.rec)
        reason = r.reason + (f" {r.estimate}." if r.estimate and r.estimate not in r.reason else "") + (f" {r.sequence}" if r.sequence else "")
        L.append(f"| {i} | {md_escape(label)} | {md_escape(r.rec.get('campaign') or 'account')} | {KINDS[r.kind][1]} | **{r.verdict}** | {md_escape(reason)} |")
    L.append("")

    acc = [(i, r) for i, r in enumerate(results, 1) if r.verdict == "accept"]
    L.append("## Accept")
    L.append("")
    if not acc:
        L.append("Nothing to accept.")
    else:
        n_changes = sum(len(r.changes) for _, r in acc)
        if n_changes and args.changes_out:
            L.append(f"**Change set:** `{args.changes_out}` holds {n_changes} change(s). Hand it to google-ads-apply-changes, which validates it, "
                     "shows a preview, and applies only what you approve. Don't use Apply on Google's cards for these: the change set keeps the "
                     "amounts inside your limits and logs the reason.")
            L.append("")
        L.append("If google-ads-apply-changes isn't installed, or for items outside the change set, make each change in the Google Ads interface:")
        L.append("")
        for i, r in acc:
            label = label_of(r.rec)
            L.append(f"**{i}. {md_escape(label)}** ({r.rec.get('campaign') or 'account'}), review on {r.review_on}{'. ' + r.sequence if r.sequence else ''}")
            for k, s in enumerate(r.steps or ["Open the recommendation card and make the change by hand (not with Apply), then note it in the change log."], 1):
                L.append(f"   {k}. {s}")
            L.append("")
    L.append("")
    rej = [(i, r) for i, r in enumerate(results, 1) if r.verdict == "reject"]
    L.append("## Reject: how to dismiss")
    L.append("")
    if not rej:
        L.append("Nothing to reject.")
    else:
        L.append("Dismiss these yourself. Nothing here dismisses them for you.")
        L.append("")
        L.append("1. Go to **Campaigns, Recommendations**.")
        L.append("2. Find each card below (switch to the table view to see many at once and select several).")
        L.append("3. Click **Dismiss** (or the three-dot menu, then Dismiss) and pick the closest reason.")
        L.append("4. A dismissed recommendation can come back later if Google thinks it's relevant again. Re-run this triage when it does.")
        L.append("")
        for i, r in rej:
            L.append(f"- {i}. {md_escape(label_of(r.rec))} ({r.rec.get('campaign') or 'account'})")
    L.append("")
    tests = [(i, r) for i, r in enumerate(results, 1) if r.verdict == "test"]
    L.append("## Test: experiments")
    L.append("")
    if not tests:
        L.append("Nothing to test.")
    for i, r in tests:
        p = r.test
        L.append(f"**{i}. {md_escape(label_of(r.rec))}** ({r.rec.get('campaign') or 'account'})")
        if r.sequence:
            L.append(f"   {r.sequence}")
        if not p:
            L.append("   Set it up as part of the related experiment above.")
            L.append("")
            continue
        L.append(f"- **Type:** {p['type']}")
        if p["mode"] == "experiment":
            L.append(f"- **Change in the trial arm:** {p['change']}")
            L.append(f"- **Split:** {p['split']} of traffic and budget")
        else:
            L.append(f"- **Change:** {p['change']} (the whole campaign; no split)")
        L.append(f"- **Duration:** {p['duration_days']} days ({p['settle_days']} to settle, {p['eval_days']} to measure, {p['lag_days']} for conversion delay), ending about {p['end_on']}")
        L.append(f"- **Success metric:** {p['success']}")
        L.append(f"- **Guardrail:** {p['guardrail'] if p['mode'] == 'experiment' else p['guardrail'].replace('in the trial arm', 'for the campaign')}")
        ratio = p["detectable_ratio"]
        if p["mode"] == "experiment" and ratio is not None:
            L.append(f"- **Expected volume:** about {p['per_arm_conversions']:g} conversions per arm while measuring. At that volume only a gap of about "
                     f"{ratio:.1f} times between the arms would be clear; smaller gaps are directional, so lean on the guardrail and the trend.")
        elif p["mode"] != "experiment" and p["per_arm_conversions"] > 0:
            L.append(f"- **Expected volume:** about {p['per_arm_conversions']:g} conversions for the campaign while measuring. Without a control group, "
                     "seasonality and other changes can move the numbers too, so read it as directional.")
        else:
            L.append("- **Expected volume:** no conversions in the window, so the result can't be read on conversions")
        if p["low_volume"]:
            L.append("- **Low volume:** fewer conversions than this skill's minimum even at the longest window. Treat the result as directional.")
        L.append("- **Setup:**")
        if p["type"].startswith("AI Max"):
            setup = ["Campaigns, Experiments, plus button, Campaign features and settings, AI Max for Search campaigns, Continue.",
                     "Select the campaign, Done, then finish on the Create an AI Max experiment page."]
        elif p["type"].startswith("Performance Max"):
            setup = ["Campaigns, Experiments, plus button: pick the Performance Max experiment type named above.",
                     "Follow the setup panel: choose the campaigns and budget, and leave the split at 50%."]
        elif p["mode"] == "network":
            setup = [f"Campaigns, open '{r.rec.get('campaign')}', Settings, Networks: turn the network on. Note the date.",
                     "At the end date, open the Campaigns table, Segment, Network, and compare the new network's rows with Google Search.",
                     "If the new network's CPA misses the success metric, turn it off again."]
        elif p["mode"] == "staged":
            setup = [f"Make the change on '{r.rec.get('campaign')}' and note the date.",
                     "At the end date, compare the campaign with the same number of days before the change (metrics.py compare)."]
        else:
            setup = ["Campaigns, Experiments, plus button, Custom. Choose the campaign and the variable to test, as named above.",
                     "Set the split to 50% (for Search, a cookie-based split shows each person one version)."]
        if p["mode"] == "experiment":
            setup += [f"Set the success metric to {'Conversions' if j.mode == 'cpa' else 'Conv. value'} and the duration to {p['duration_days']} days.",
                      "Leave **Apply experiment changes if the trial wins** unchecked. You decide after reading the result."]
            setup += p["extra_steps"]
            setup.append("Don't change the original campaign while the test runs.")
        else:
            setup.append(f"Leave it for {p['duration_days']} days without other changes to this campaign.")
            setup += p["extra_steps"]
        for k, s in enumerate(setup, 1):
            L.append(f"   {k}. {s}")
        L.append("")
    holds = [(i, r) for i, r in enumerate(results, 1) if r.verdict == "hold"]
    L.append("## Hold: needs an answer first")
    L.append("")
    if not holds:
        L.append("Nothing on hold.")
    for i, r in holds:
        L.append(f"- {i}. {md_escape(label_of(r.rec))} ({r.rec.get('campaign') or 'account'}): {r.reason} Leave the card open (don't apply or dismiss) until then.")
    L.append("")
    L += auto_apply_section(j, args.subscriptions, args.change_history)
    camps = [Camp(row, args.days) for row in {id(v): v for v in list(t.by_id.values()) + list(t.by_name.values())}.values()]
    L += score_section(j, args.optimization_score, camps)
    if warnings:
        L.append("## Data notes from the script")
        L.append("")
        for w_ in warnings:
            L.append(f"- {w_}")
        L.append("")
    (out_dir / "triage.md").write_text("\n".join(L), encoding="utf-8")

    if args.changes_out:
        entries = [c for r in results if r.verdict == "accept" for c in r.changes]
        batch = {"name": f"{t.today.isoformat()} recommendations triage", "account_id": "", "account_name": ctx.account,
                 "created": t.today.isoformat(), "approved_by": "", "approved_at": "", "changes": entries}
        m = re.search(r"\(([\d-]{10,12})\)", ctx.account or "")
        if m:
            batch["account_id"] = m.group(1)
            batch["account_name"] = ctx.account.split("(")[0].strip()
        Path(args.changes_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.changes_out).write_text(json.dumps(batch, indent=2), encoding="utf-8")

    print(f"recommendations: {len(results)} (dismissed skipped: {skipped})", file=sys.stderr)
    print("verdicts: " + ", ".join(f"{k} {v}" for k, v in counts.items()), file=sys.stderr)
    print(f"mainly raise spend: {len(spend)}, of which accepted: {len(spend_acc)}", file=sys.stderr)
    print(f"change set entries: {sum(len(r.changes) for r in results if r.verdict == 'accept')}", file=sys.stderr)
    print(f"wrote {out_dir / 'triage.csv'} and {out_dir / 'triage.md'}" + (f" and {args.changes_out}" if args.changes_out else ""), file=sys.stderr)
    for w_ in warnings:
        print(f"note: {w_}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recommendations", required=True)
    p.add_argument("--campaigns", nargs="+", required=True)
    p.add_argument("--context")
    p.add_argument("--days", type=float, required=True, help="length of the data window in days")
    p.add_argument("--window", default="", help="the window as text, for evidence lines")
    p.add_argument("--keywords")
    p.add_argument("--negatives", nargs="*", default=[])
    p.add_argument("--ads")
    p.add_argument("--subscriptions")
    p.add_argument("--change-history")
    p.add_argument("--optimization-score", type=float)
    p.add_argument("--overrides")
    p.add_argument("--target-cpa", type=float)
    p.add_argument("--breakeven-cpa", type=float)
    p.add_argument("--target-roas", type=float)
    p.add_argument("--breakeven-roas", type=float)
    p.add_argument("--conversion-lag", type=int)
    p.add_argument("--today")
    p.add_argument("--max-budget-change", type=float)
    p.add_argument("--max-target-change", type=float)
    p.add_argument("--budget-lost-threshold", type=float, default=0.10)
    p.add_argument("--budget-use-threshold", type=float, default=0.90)
    p.add_argument("--min-test-conversions", type=float, default=30)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--changes-out")
    args = p.parse_args()

    ctx = parse_context(args.context)
    if args.target_cpa or args.breakeven_cpa:
        ctx.mode, ctx.target, ctx.breakeven, ctx.econ_source = "cpa", args.target_cpa, args.breakeven_cpa, "command line"
    elif args.target_roas or args.breakeven_roas:
        ctx.mode, ctx.target, ctx.breakeven, ctx.econ_source = "roas", args.target_roas, args.breakeven_roas, "command line"
    if not ctx.mode and (ctx.target is None and ctx.breakeven is None):
        warn("no target or break-even found; spend-raising and bidding items will be held")
    j = Judge(ctx, args)

    by_id, by_name = load_campaigns(args.campaigns)
    keywords = [r for r in read_csv(args.keywords) if (r.get("is_negative") or "").lower() != "true"] if args.keywords else []
    negatives = []
    for path in args.negatives:
        negatives += [r for r in read_csv(path) if (r.get("is_negative") or "true").lower() == "true"]
    if args.keywords:
        negatives += [r for r in read_csv(args.keywords) if (r.get("is_negative") or "").lower() == "true"]
    ads = read_csv(args.ads) if args.ads else []
    recs = read_csv(args.recommendations)
    skipped = sum(1 for r in recs if (r.get("dismissed") or "").lower() == "true")
    recs = [r for r in recs if (r.get("dismissed") or "").lower() != "true"]

    t = Triage(ctx, j, args, by_id, by_name, keywords, negatives, ads)
    results = [t.run(r) for r in recs]
    apply_overrides(results, args.overrides)
    sequence(results, t.today)
    order = {"accept": 0, "test": 1, "reject": 2, "hold": 3}
    results.sort(key=lambda r: (order[r.verdict], (r.rec.get("campaign") or "").lower()))
    write_outputs(results, j, t, args, ctx, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
