#!/usr/bin/env python3
"""Check a new Google Ads Search campaign build before anyone approves it.

Reads a build spec (see references/build-spec.md) and reports:

Errors (exit code 1) block the build:
  - a campaign name that already exists in the account (an Editor import
    would edit that campaign instead of creating a new one)
  - anything not created paused, missing fields, invalid values
  - retired or removed features: Enhanced CPC, broad match modifier, expanded
    text ads, call-only ads, Dynamic Search Ads, Smart campaigns, the old
    campaign-level broad match setting, campaign language targeting on Search
  - text over Google's limits (headlines 30, descriptions 90, paths 15,
    sitelink text 25, sitelink descriptions 35, callouts 25), wide
    characters counted double
  - counts outside Google's limits (3 to 15 headlines, 2 to 4 descriptions,
    no more than 3 responsive search ads per ad group)
  - ad text that makes a claim (numbers, prices, guarantees, ratings, "free",
    "best", and similar) without a source, or with a number its source
    doesn't contain
  - search volumes with no source, or that don't match the keyword data file
  - negatives that would block a planned keyword, duplicate keywords
  - a conversion-based bid strategy without working conversion tracking
  - a missing AI Max decision or EU political ads declaration

Warnings (shown to the person, who decides):
  - search partners, Display, or "Presence or interest" turned on
  - broad match at launch, fewer than 2 ads per ad group, thin assets
  - negatives touching protected terms, keywords already live elsewhere
  - copy that uses words the context file says to avoid
  - likely disapprovals: repeated punctuation, emoji, all caps, phone numbers,
    exclamation marks in headlines

Usage:
  python3 validate_build.py BUILD.json
      [--context .agents/google-ads-context.md]
      [--existing FILE ...]      campaign list, normalized CSV, connector JSON,
                                 or a Google Ads Editor export
      [--keyword-data FILE.csv]  output of keyword_list.py
      [--today YYYY-MM-DD] [--json]

Standard library only. render_plan.py and build_editor_files.py import it.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

HEADLINE_MAX, DESCRIPTION_MAX, PATH_MAX = 30, 90, 15
SITELINK_TEXT_MAX, SITELINK_DESC_MAX, CALLOUT_MAX = 25, 35, 25
KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 80, 10
MIN_HEADLINES, MAX_HEADLINES, MIN_DESCRIPTIONS, MAX_DESCRIPTIONS = 3, 15, 2, 4
MAX_ENABLED_RSAS, RECOMMENDED_RSAS = 3, 2
SITELINKS_TO_SHOW, SITELINKS_FOR_AD_STRENGTH, SITELINKS_MAX = 2, 6, 20
CALLOUTS_SUGGESTED = 4
KEYWORDS_PER_AD_GROUP_WARN = 20
NEGATIVES_PER_CAMPAIGN = 10000
DAYS_PER_MONTH = 30.4  # Google: monthly spend stays under 30.4 times the average daily budget
MAX_DAY_MULTIPLIER = 2  # Google: a single day can spend up to twice the average daily budget

BID_STRATEGIES = {
    "manual_cpc": "Manual CPC",
    "maximize_clicks": "Maximize clicks",
    "maximize_conversions": "Maximize conversions",
    "target_cpa": "Target CPA",
    "maximize_conversion_value": "Maximize conversion value",
    "target_roas": "Target ROAS",
}
CONVERSION_BASED = {"maximize_conversions", "target_cpa", "maximize_conversion_value", "target_roas"}
RETIRED_STRATEGIES = {"enhanced_cpc", "ecpc", "manual_cpc_enhanced", "enhanced cpc"}
RETIRED_AD_TYPES = {"expanded_text_ad", "expanded_text", "eta", "text_ad", "call_only", "call_only_ad",
                    "dynamic_search_ad", "dsa"}
RSA_TYPES = {"", "rsa", "responsive_search_ad", "responsive search ad"}
RETIRED_CAMPAIGN_KEYS = {
    "enhanced_cpc": "Enhanced CPC ended in March 2025",
    "broad_match_setting": "the campaign-level broad match setting can't be created since August 3, 2026",
    "campaign_broad_match": "the campaign-level broad match setting can't be created since August 3, 2026",
    "dynamic_search_ads": "new Dynamic Search Ads are being replaced by AI Max",
    "dsa": "new Dynamic Search Ads are being replaced by AI Max",
    "call_only": "call-only ads can't be created since February 2026; use a call asset",
}
MATCH_TYPES = {"exact", "phrase", "broad"}
KEYWORD_SOURCES = {"seed", "site", "keyword_tool", "planner_export", "account_history", "web", "context"}
VOLUME_SOURCES = {"keyword_tool", "planner_export"}
NEGATIVE_SOURCES = {"terms_we_dont_want", "person", "structure"}
SOURCE_TYPES = {"context", "person", "page"}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

KEYWORD_SYMBOLS = set("!@%^*=;~`<>?\\|{},")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
REPEAT_PUNCT_RE = re.compile(r"([!?.,])\1")
NUMBER_RE = re.compile(r"\d[\d,.]*")
ACRONYM_OK = {"USA", "UK", "EU", "FAQ", "HVAC", "SEO", "CRM", "API", "AI", "PPC", "ROI", "B2B", "SaaS", "CPA",
              "LLC", "NYC", "IRS", "DIY", "24/7"}

# Words that make a line a claim that needs a source. Digits and currency symbols count too.
CLAIM_WORDS = [
    "guarantee", "guaranteed", "guarantees", "warranty", "warranties", "certified", "certification",
    "licensed", "license", "insured", "bonded", "accredited", "award", "awards", "award-winning",
    "rated", "rating", "ratings", "review", "reviews", "stars", "best", "top", "leading", "trusted",
    "official", "only", "lowest", "cheapest", "fastest", "fast", "quick", "instant", "free", "discount",
    "discounts", "save", "savings", "sale", "deal", "deals", "offer", "offers", "promo", "coupon",
    "same-day", "next-day", "emergency", "experienced", "expert", "experts", "family-owned",
    "locally owned", "satisfaction", "refund", "money-back", "risk-free", "no obligation", "financing",
    "price match", "number one",
]
CLAIM_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(w).replace(r"\-", "[- ]?").replace(r"\ ", "[- ]?") for w in CLAIM_WORDS)
    + r")(?![\w-])|#1|\d|[$€£¥%]",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- helpers

def width(text: str) -> int:
    """Characters as Google counts them: wide and full-width characters count double."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def tokens(text: str) -> list[str]:
    t = str(text).strip().lower()
    if t.startswith("-"):
        t = t[1:]
    t = t.strip('[]"')
    return [w for w in re.split(r"\s+", t) if w]


def negative_blocks(neg: list[str], match: str, query: list[str]) -> bool:
    """Whether a negative keyword blocks a keyword or query. Negatives don't match close variants."""
    if not neg or not query:
        return False
    if match == "exact":
        return neg == query
    if match == "phrase":
        n = len(neg)
        return any(query[i:i + n] == neg for i in range(len(query) - n + 1))
    return set(neg) <= set(query)


def num(value):
    if value in (None, "", "MISSING"):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def text_of(item) -> str:
    if isinstance(item, dict):
        return str(item.get("text", "")).strip()
    return str(item or "").strip()


def source_of(item) -> str:
    return str(item.get("source", "") or "").strip() if isinstance(item, dict) else ""


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in NUMBER_RE.findall(text):
        n = m.replace(",", "").rstrip(".")
        if n:
            out.add(n)
    return out


def is_url(value: str) -> bool:
    return str(value or "").startswith(("https://", "http://"))


def host(url: str) -> str:
    m = re.match(r"https?://([^/?#]+)", str(url or ""))
    return m.group(1).lower().removeprefix("www.") if m else ""


def load_spec(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def campaign_of(spec: dict) -> dict:
    return spec.get("campaign") or {}


def ads_of(group: dict) -> list[dict]:
    return group.get("ads") or []


def ai_max_of(camp: dict) -> dict:
    value = camp.get("ai_max")
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- context file

def section(text: str, name: str) -> str:
    m = re.search(rf"(?ms)^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)", text)
    return m.group(1) if m else ""


def bullets(block: str) -> list[str]:
    out = []
    for line in block.splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if m and not m.group(1).startswith("[") and m.group(1).upper() != "MISSING":
            out.append(m.group(1).strip())
    return out


def field(block: str, label: str) -> str:
    m = re.search(rf"(?im)^\s*[-*]\s*{re.escape(label)}[^:\n]*:\s*(.*)$", block)
    value = m.group(1).strip() if m else ""
    return "" if value.startswith("[") or value.upper().startswith("MISSING") else value


def split_list(value: str) -> list[str]:
    return [v.strip().strip('"') for v in re.split(r"[;,]", value) if v.strip()]


def parse_context(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    economics = section(text, "Economics")
    target = field(economics, "Target CPA or target ROAS")
    target_cpa = None
    if target and "roas" not in target.lower() and "%" not in target:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", target)
        target_cpa = float(m.group(0).replace(",", "")) if m else None
    voice = section(text, "Brand voice and copy rules")
    comp = section(text, "Competitor policy")
    return {
        "protected": bullets(section(text, "Protected terms")),
        "unwanted": bullets(section(text, "Terms we don't want")),
        "avoid": split_list(field(voice, "Words and phrases to avoid")),
        "competitors": split_list(field(comp, "Main competitors")),
        "bid_on_competitors": field(comp, "Bid on competitor names").lower(),
        "name_competitors": field(comp, "Name competitors in ad copy").lower(),
        "target_cpa": target_cpa,
        "approver": field(section(text, "Permissions and limits"), "Approver"),
        "loaded": True,
    }


# ---------------------------------------------------------------- existing account data

ALIASES = {
    "campaign": ["campaign", "campaign name", "campaign.name", "campaign_name"],
    "campaign_status": ["campaign status", "campaign_status", "campaign.status", "campaign state"],
    "keyword": ["keyword", "keyword text", "ad_group_criterion.keyword.text"],
    "match_type": ["criterion type", "match type", "match_type", "ad_group_criterion.keyword.match_type"],
    "is_negative": ["is_negative", "ad_group_criterion.negative"],
    "keyword_status": ["keyword_status", "keyword status", "ad_group_criterion.status", "status"],
}


def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def flatten(row, prefix: str = "") -> dict:
    out = {}
    if isinstance(row, dict):
        for k, v in row.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(flatten(v, key + "."))
            else:
                out[key] = v
    return out


def read_rows(path: str) -> list[dict]:
    """Rows from a CSV or TSV (UTF-8 or UTF-16), a connector JSON result, or a plain list of names."""
    raw = Path(path).read_bytes()
    text = decode(raw)
    if path.lower().endswith(".json"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("results") or data.get("rows") or data.get("data") or []
        return [{k.lower(): v for k, v in flatten(r).items()} for r in data if isinstance(r, dict)]
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines[:50]):
        cells = [c.strip().strip('"').lower() for c in re.split(r"[\t,]", line)]
        if any(c in ALIASES["campaign"] for c in cells):
            start = i
            break
    if start is None:  # a plain list of campaign names, one per line
        return [{"campaign": line.strip()} for line in lines if line.strip()]
    header_line = lines[start]
    delimiter = "\t" if header_line.count("\t") >= header_line.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])), delimiter=delimiter)
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]


def pick(row: dict, name: str) -> str:
    for alias in ALIASES[name]:
        if alias in row and row[alias] not in (None, ""):
            return str(row[alias]).strip()
    return ""


def load_existing(paths: list[str]) -> dict:
    campaigns: dict[str, dict] = {}
    keywords: list[dict] = []
    for path in paths:
        for row in read_rows(path):
            name = pick(row, "campaign")
            if not name:
                continue
            status = pick(row, "campaign_status").lower()
            entry = campaigns.setdefault(norm(name), {"name": name, "status": ""})
            if status and not entry["status"]:
                entry["status"] = status
            kw, match = pick(row, "keyword"), pick(row, "match_type").lower()
            negative = pick(row, "is_negative").lower() in ("true", "1", "yes") or match.startswith(("negative", "campaign negative"))
            kw_status = pick(row, "keyword_status").lower()
            if kw and not negative:
                m = next((w for w in MATCH_TYPES if w in match), "broad")
                keywords.append({"campaign": name, "keyword": norm(kw.strip('[]"')), "match_type": m,
                                 "status": kw_status, "campaign_status": status})
    return {"campaigns": campaigns, "keywords": keywords}


def load_keyword_data(path: str) -> dict:
    rows = read_rows_plain(path)
    return {norm(r.get("keyword", "")): r for r in rows if r.get("keyword")}


def read_rows_plain(path: str) -> list[dict]:
    text = decode(Path(path).read_bytes())
    first = text.splitlines()[0] if text else ""
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(text), delimiter=delimiter)]


# ---------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, where: str, message: str):
        self.items.append({"level": level, "where": where, "message": message})

    def error(self, where: str, message: str):
        self.add("error", where, message)

    def warn(self, where: str, message: str):
        self.add("warning", where, message)

    def errors(self):
        return [i for i in self.items if i["level"] == "error"]

    def warnings(self):
        return [i for i in self.items if i["level"] == "warning"]


# ---------------------------------------------------------------- checks

def lint_text(report: Report, where: str, label: str, text: str, headline: bool):
    if REPEAT_PUNCT_RE.search(text):
        report.warn(where, f"{label} repeats punctuation ('{text}'), which Google's editorial policy disallows")
    if EMOJI_RE.search(text):
        report.warn(where, f"{label} contains an emoji or symbol character ('{text}')")
    if headline and "!" in text:
        report.warn(where, f"{label} has an exclamation mark ('{text}'); headlines with one are often disapproved")
    caps = [w for w in re.findall(r"[A-Za-z]{3,}", text) if w.isupper() and w not in ACRONYM_OK]
    if caps:
        report.warn(where, f"{label} has all-caps words {caps} ('{text}'); gimmicky capitalization gets disapproved")
    if PHONE_RE.search(text):
        report.warn(where, f"{label} looks like it contains a phone number ('{text}'); use a call asset instead")


def check_claim(report: Report, spec: dict, where: str, label: str, item, ctx: dict):
    """A line that makes a claim needs a source, and its numbers must appear in that source."""
    text = text_of(item)
    sources = spec.get("sources") or {}
    sid = source_of(item)
    found = [m.group(0).lower() for m in CLAIM_RE.finditer(text)]
    for word in ctx.get("avoid", []):
        if word and re.search(rf"(?<!\w){re.escape(word.lower())}(?!\w)", text.lower()):
            report.warn(where, f"{label} uses '{word}', which the context file lists under words to avoid")
    if ctx.get("name_competitors", "").startswith("no"):
        for comp in ctx.get("competitors", []):
            if comp and re.search(rf"(?<!\w){re.escape(comp.lower())}(?!\w)", text.lower()):
                report.warn(where, f"{label} names competitor '{comp}'; the context file says not to name competitors in ads")
    if sid:
        if sid not in sources:
            report.error(where, f"{label} cites source '{sid}', which isn't in sources")
            return
        src = sources[sid]
        missing = sorted(numbers_in(text) - numbers_in(str(src.get("text", ""))))
        if missing:
            report.error(where, f"{label} has {', '.join(missing)}, which source {sid} doesn't contain: '{text}'")
    elif found:
        words = sorted({"a number" if w.isdigit() else w for w in found})
        report.error(where, f"{label} makes a claim ({', '.join(words)[:60]}) with no source: '{text}'. "
                     "Cite an approved offer or proof point, or reword it.")


def check_keyword_text(report: Report, where: str, text: str):
    clean = text.strip()
    if clean != clean.strip('[]"') or clean.startswith("-"):
        report.error(where, f"write keywords without brackets, quotes, or a minus sign; put the match type in match_type: '{clean}'")
        clean = clean.strip('[]"-')
    if len(clean) > KEYWORD_MAX_CHARS:
        report.error(where, f"keyword is {len(clean)} characters, over {KEYWORD_MAX_CHARS}: '{clean}'")
    if len(clean.split()) > KEYWORD_MAX_WORDS:
        report.error(where, f"keyword has more than {KEYWORD_MAX_WORDS} words: '{clean}'")
    bad = sorted(set(clean) & KEYWORD_SYMBOLS)
    if bad:
        report.warn(where, f"keyword contains symbols Google may reject {bad}: '{clean}'")
    if clean.startswith("+") or " +" in clean:
        report.error(where, f"'+' broad match modifier is retired; use phrase or exact: '{clean}'")


def check_sources(report: Report, spec: dict, today: dt.date):
    for sid, src in (spec.get("sources") or {}).items():
        where = f"source {sid}"
        if not isinstance(src, dict):
            report.error(where, "must be an object with type, where, and text")
            continue
        if src.get("type") not in SOURCE_TYPES:
            report.error(where, f"type must be one of {sorted(SOURCE_TYPES)}")
        if not str(src.get("text", "")).strip():
            report.error(where, "has no text; copy the approved wording")
        if src.get("type") == "page" and src.get("confirmed") is not True:
            report.warn(where, f"seen on {src.get('where', 'a page')} but not confirmed by the person; "
                        "confirm it before approval (the Editor builder refuses unconfirmed sources)")
        expires = str(src.get("expires", "") or "")
        if expires:
            try:
                if dt.date.fromisoformat(expires) < today:
                    report.error(where, f"expired on {expires}; don't use it in ads")
            except ValueError:
                report.error(where, f"expires must be YYYY-MM-DD, not '{expires}'")


def used_sources(spec: dict) -> set[str]:
    out = set()
    for group in spec.get("ad_groups") or []:
        for ad in ads_of(group):
            for item in (ad.get("headlines") or []) + (ad.get("descriptions") or []):
                if source_of(item):
                    out.add(source_of(item))
    for item in (spec.get("sitelinks") or []) + (spec.get("callouts") or []):
        if source_of(item):
            out.add(source_of(item))
    return out


def unconfirmed_sources(spec: dict) -> list[str]:
    sources = spec.get("sources") or {}
    return sorted(s for s in used_sources(spec)
                  if s in sources and sources[s].get("type") == "page" and sources[s].get("confirmed") is not True)


def check_campaign(report: Report, spec: dict, ctx: dict, existing: dict | None, today: dt.date):
    camp = campaign_of(spec)
    where = "campaign"
    name = str(camp.get("name", "")).strip()
    if not name:
        report.error(where, "has no name")
    if str(camp.get("type", "search")).lower() != "search":
        kind = str(camp.get("type")).lower()
        report.error(where, f"type '{kind}' isn't covered; this skill builds Search campaigns only"
                     + (" (Smart campaigns can't be created since August 2026)" if "smart" in kind else ""))
    status = str(camp.get("status", "paused")).lower()
    if status != "paused":
        report.error(where, f"status is '{status}'; new campaigns are created paused")
    for key, why in RETIRED_CAMPAIGN_KEYS.items():
        if camp.get(key):
            report.error(where, f"'{key}' is set, but {why}")
    if camp.get("languages") or camp.get("language"):
        report.error(where, "has language targeting; Google removed campaign language targeting from Search in "
                     "late September 2026 and rejects it. Write the ads in the customers' language instead.")

    # Name collisions with the account.
    if existing is None:
        report.warn(where, "no --existing file given; the name wasn't checked against the account's campaigns")
    elif name:
        hit = existing["campaigns"].get(norm(name))
        if hit and hit["status"] != "removed":
            report.error(where, f"'{name}' already exists in the account ({hit['status'] or 'status unknown'}); an Editor "
                         "import would change that campaign instead of creating a new one. Pick a new name.")
        elif hit:
            report.warn(where, f"a removed campaign is named '{name}'; a fresh name avoids confusion in reports")
        loose = re.sub(r"[\W_]+", "", name.lower())
        for key, entry in existing["campaigns"].items():
            if key != norm(name) and re.sub(r"[\W_]+", "", key) == loose:
                report.warn(where, f"'{name}' differs from existing campaign '{entry['name']}' only in spacing or punctuation")

    # Budget and bidding.
    budget = num(camp.get("daily_budget"))
    if budget is None or budget <= 0:
        report.error(where, "daily_budget must be a number above zero")
    monthly = num(camp.get("monthly_budget"))
    if monthly and budget:
        expected = round(monthly / DAYS_PER_MONTH, 2)
        if abs(expected - budget) > 0.011:
            report.error(where, f"daily_budget {budget:g} doesn't match monthly_budget {monthly:g}; Google spends up to "
                         f"{DAYS_PER_MONTH} times the daily budget a month, so the daily budget is {expected:.2f}")
    strategy = str(camp.get("bid_strategy", "")).lower()
    goals = camp.get("conversion_goals") or {}
    conv = num(goals.get("conversions_30d"))
    if strategy in RETIRED_STRATEGIES:
        report.error(where, "Enhanced CPC ended in March 2025; choose another bid strategy")
    elif strategy == "target_impression_share":
        report.error(where, "Target impression share isn't built by this skill; choose another strategy or set it by hand after import")
    elif strategy not in BID_STRATEGIES:
        report.error(where, f"bid_strategy must be one of {sorted(BID_STRATEGIES)}")
    if strategy in CONVERSION_BASED:
        if goals.get("tracking_ready") is not True:
            report.error(where, f"{BID_STRATEGIES[strategy]} needs working conversion tracking (conversion_goals.tracking_ready "
                         "is not true). Fix tracking first, or use Manual CPC or Maximize clicks with a limit until then.")
        if not goals.get("primary"):
            report.error(where, "conversion_goals.primary is empty; name the conversion actions the campaign should bid for")
    if strategy == "target_cpa":
        target = num(camp.get("target_cpa"))
        if target is None or target <= 0:
            report.error(where, "target_cpa must be a number above zero")
        if not str(camp.get("target_source", "")).strip():
            report.error(where, "target_cpa needs target_source: where the number came from (Google recommends the last "
                         "30 days' average CPA, adjusted for conversion delay)")
        if conv is None or conv < 30:
            report.warn(where, f"Target CPA with {'unknown' if conv is None else f'{conv:g}'} conversions in 30 days; Google "
                        "recommends judging it over 30 days with at least 30 conversions. Maximize conversions with no "
                        "target is the usual start.")
    if strategy == "target_roas":
        target = num(camp.get("target_roas"))
        if target is None or target <= 0:
            report.error(where, "target_roas must be a ratio above zero (4 means 400%)")
        elif target > 100:
            report.warn(where, f"target_roas {target:g} looks like a percentage; write it as a ratio (4 means 400%)")
        if not str(camp.get("target_source", "")).strip():
            report.error(where, "target_roas needs target_source: where the number came from")
        if conv is None or conv < 15:
            report.error(where, f"Target ROAS needs at least 15 conversions in the past 30 days in Search (Google); "
                         f"conversions_30d is {'MISSING' if conv is None else f'{conv:g}'}")
    if strategy == "maximize_conversion_value" and goals.get("has_values") is not True:
        report.error(where, "Maximize conversion value needs real conversion values (conversion_goals.has_values)")
    if strategy == "maximize_clicks" and num(camp.get("max_cpc_limit")) is None:
        report.warn(where, "Maximize clicks without a Maximum CPC bid limit can buy expensive clicks; set max_cpc_limit")
    if strategy == "manual_cpc":
        for group in spec.get("ad_groups") or []:
            if num(group.get("max_cpc")) is None:
                report.error(f"ad group '{group.get('name', '')}'", "Manual CPC needs a default max_cpc on every ad group")
    if budget and ctx.get("target_cpa") and budget < ctx["target_cpa"]:
        report.warn(where, f"daily budget {budget:g} is below the context's target CPA {ctx['target_cpa']:g}; the campaign "
                    "can't buy one conversion a day at target")

    # Networks.
    nets = camp.get("networks") or {}
    if nets.get("google_search", True) is not True:
        report.error(where, "networks.google_search must be true for a Search campaign")
    for key, label in (("search_partners", "Search partners"), ("display", "the Display Network")):
        if nets.get(key):
            if not str(nets.get("reason", "")).strip():
                report.error(where, f"{label} is on with no networks.reason; it's off by default in this skill")
            else:
                report.warn(where, f"{label} is on ({nets['reason']}); test it separately once Search alone works")

    # Locations.
    option = str(camp.get("location_option", "presence")).lower()
    if option not in ("presence", "presence_or_interest"):
        report.error(where, "location_option must be presence or presence_or_interest")
    elif option == "presence_or_interest":
        if not str(camp.get("location_option_reason", "")).strip():
            report.error(where, "Presence or interest needs location_option_reason; this skill uses Presence by default")
        else:
            report.warn(where, "location option is Presence or interest; ads can show to people outside the area")
    locations = camp.get("locations") or []
    if not locations:
        report.error(where, "no locations; Editor would target every country. List the real markets.")
    for i, loc in enumerate(locations, 1):
        if not isinstance(loc, dict):
            report.error(where, f"location {i} must be an object")
            continue
        if loc.get("radius") not in (None, ""):
            if num(loc.get("radius")) is None or num(loc.get("radius")) <= 0:
                report.error(where, f"location {i}: radius must be a number above zero")
            if str(loc.get("unit", "mi")).lower() not in ("mi", "km"):
                report.error(where, f"location {i}: unit must be mi or km")
            lat, lng = num(loc.get("lat")), num(loc.get("lng"))
            if lat is None or lng is None:
                report.warn(where, f"location {i}: radius without lat and lng; it becomes a by-hand step in Editor")
            elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
                report.error(where, f"location {i}: lat or lng out of range")
        elif not str(loc.get("name", "")).strip():
            report.error(where, f"location {i} needs a name (as Editor shows it) or a radius")
    for i, loc in enumerate(camp.get("excluded_locations") or [], 1):
        if not str((loc or {}).get("name", "")).strip():
            report.error(where, f"excluded location {i} needs a name")

    # Schedule and dates.
    for i, block in enumerate(camp.get("ad_schedule") or [], 1):
        days = block.get("days") or []
        bad = [d for d in days if d not in DAYS]
        if not days or bad:
            report.error(where, f"ad_schedule {i}: days must be English day names {DAYS}")
        times = []
        for key in ("start", "end"):
            value = str(block.get(key, ""))
            m = re.fullmatch(r"(\d{2}):(\d{2})", value)
            if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59 or (int(m.group(1)) == 24 and m.group(2) != "00"):
                report.error(where, f"ad_schedule {i}: {key} must be HH:MM on a 24-hour clock, not '{value}'")
                continue
            if int(m.group(2)) % 15:
                report.warn(where, f"ad_schedule {i}: {key} {value} isn't on a 15-minute step")
            times.append(int(m.group(1)) * 60 + int(m.group(2)))
        if len(times) == 2 and times[0] >= times[1]:
            report.error(where, f"ad_schedule {i}: start must be before end")
    for key in ("start_date", "end_date"):
        value = str(camp.get(key, "") or "")
        if value:
            try:
                day = dt.date.fromisoformat(value)
                if day < today:
                    report.error(where, f"{key} {value} is in the past; Editor needs today or later")
            except ValueError:
                report.error(where, f"{key} must be YYYY-MM-DD, not '{value}'")

    # AI Max and declarations.
    ai = camp.get("ai_max")
    if not isinstance(ai, dict) or not isinstance(ai.get("enabled"), bool):
        report.error(where, "ai_max.enabled must be true or false. New Search campaigns start with AI Max on, so the "
                     "build must record the decision.")
    else:
        tc, fue = ai.get("text_customization", False), ai.get("final_url_expansion", False)
        if not ai["enabled"] and (tc or fue):
            report.error(where, "text customization and final URL expansion need AI Max on")
        if fue and not tc:
            report.error(where, "final URL expansion needs text customization on")
        if ai["enabled"]:
            report.warn(where, "AI Max is on: it needs conversion-based Smart Bidding, weekly search term reviews, and a "
                        "budget that isn't limited" + (". Final URL expansion is on, so pins are ignored and traffic can "
                                                        "land on pages you didn't pick." if fue else "."))
            if strategy not in CONVERSION_BASED:
                report.warn(where, "AI Max works with conversion-based Smart Bidding; this campaign uses "
                            f"{BID_STRATEGIES.get(strategy, strategy)}")
    if str(camp.get("eu_political_ads", "")).lower() not in ("no", "yes"):
        report.error(where, "eu_political_ads must be 'no' or 'yes'. Google requires the declaration on every new "
                     "campaign; ask the person.")
    elif str(camp.get("eu_political_ads")).lower() == "yes":
        report.warn(where, "declared as containing EU political ads; those campaigns don't serve in the EU")


def check_build(spec: dict, ctx: dict | None = None, existing: dict | None = None,
                keyword_data: dict | None = None, today: dt.date | None = None) -> Report:
    ctx = ctx or {"protected": [], "unwanted": [], "avoid": [], "competitors": []}
    today = today or dt.date.today()
    report = Report()
    for key in ("name", "account_id"):
        if not str(spec.get(key, "")).strip():
            report.warn("build", f"has no {key}")
    check_sources(report, spec, today)
    check_campaign(report, spec, ctx, existing, today)
    camp = campaign_of(spec)
    strategy = str(camp.get("bid_strategy", "")).lower()
    groups = spec.get("ad_groups") or []
    if not groups:
        report.error("campaign", "has no ad groups")

    # Keywords across the campaign.
    planned: list[tuple[str, dict, dict]] = []
    seen_kw: dict[tuple, str] = {}
    seen_order: dict[tuple, tuple] = {}
    group_names: dict[str, int] = {}
    all_final_urls: set[str] = set()
    hosts: set[str] = set()
    for gi, group in enumerate(groups, 1):
        gname = str(group.get("name", "")).strip()
        where = f"ad group '{gname or gi}'"
        if not gname:
            report.error(where, "has no name")
        group_names[norm(gname)] = group_names.get(norm(gname), 0) + 1
        if str(group.get("status", "paused")).lower() != "paused":
            report.error(where, "isn't paused; new ad groups are created paused")
        kws = group.get("keywords") or []
        if not kws:
            report.error(where, "has no keywords")
        if len(kws) > KEYWORDS_PER_AD_GROUP_WARN:
            report.warn(where, f"has {len(kws)} keywords; if one ad can't answer all of them, split it by theme")
        for kw in kws:
            text = str(kw.get("text", ""))
            match = str(kw.get("match_type", "")).lower()
            kwhere = f"{where} keyword '{text}'"
            check_keyword_text(report, kwhere, text)
            if match not in MATCH_TYPES:
                report.error(kwhere, "match_type must be exact, phrase, or broad")
            if str(kw.get("status", "paused")).lower() != "paused":
                report.error(kwhere, "isn't paused; new keywords are created paused")
            src = str(kw.get("source", "")).lower()
            if src not in KEYWORD_SOURCES:
                report.warn(kwhere, f"source should be one of {sorted(KEYWORD_SOURCES)}")
            volume = kw.get("avg_monthly_searches")
            if volume not in (None, "", "MISSING"):
                if src not in VOLUME_SOURCES or not str(kw.get("volume_source", "")).strip():
                    report.error(kwhere, "has a search volume without volume_source from a keyword tool or Keyword Planner "
                                 "export; never estimate volumes. Use MISSING.")
                if keyword_data is not None:
                    row = keyword_data.get(norm(text))
                    if row is None:
                        report.error(kwhere, "has a search volume but isn't in the keyword data file")
                    elif str(row.get("avg_monthly_searches", "")).strip() != str(volume).strip():
                        report.error(kwhere, f"volume '{volume}' doesn't match the keyword data file "
                                     f"('{row.get('avg_monthly_searches', '')}')")
            if match == "broad":
                if strategy in CONVERSION_BASED:
                    report.warn(kwhere, "broad match at launch; practitioners add broad once the campaign has steady "
                                "conversions, Smart Bidding, and a tight negative list")
                else:
                    report.warn(kwhere, f"broad match with {BID_STRATEGIES.get(strategy, strategy)}; Google calls Smart "
                                "Bidding critical for broad match")
            key = (norm(text), match)
            if key in seen_kw:
                report.error(kwhere, f"duplicates the same keyword in {seen_kw[key]}")
            seen_kw.setdefault(key, where)
            okey = (tuple(sorted(tokens(text))), match)
            prev = seen_order.get(okey)
            if prev and prev[1] != norm(text):
                report.warn(kwhere, f"has the same words as '{prev[1]}' in {prev[0]} in another order; Google treats "
                            "these as duplicates")
            seen_order.setdefault(okey, (where, norm(text)))
            planned.append((text, kw, group))
            if existing:
                for ek in existing["keywords"]:
                    live = ek["status"] in ("", "enabled", "active") and ek["campaign_status"] in ("", "enabled", "active")
                    if live and ek["keyword"] == norm(text) and ek["match_type"] == match:
                        report.warn(kwhere, f"is already live in campaign '{ek['campaign']}'; the two campaigns would "
                                    "compete for the same searches")
                        break
        if group.get("final_url") and not is_url(group.get("final_url")):
            report.error(where, f"final_url must start with https://: '{group.get('final_url')}'")

        # Responsive search ads.
        ads = ads_of(group)
        if not ads:
            report.error(where, "has no responsive search ads")
        elif len(ads) < RECOMMENDED_RSAS:
            report.warn(where, f"has {len(ads)} ad; Google recommends at least {RECOMMENDED_RSAS} per ad group")
        if len(ads) > MAX_ENABLED_RSAS:
            report.error(where, f"has {len(ads)} ads; Google allows {MAX_ENABLED_RSAS} enabled responsive search ads per ad group")
        heads_by_ad = []
        for ai_, ad in enumerate(ads, 1):
            awhere = f"{where} ad {ai_}"
            kind = str(ad.get("type", "")).lower()
            if kind in RETIRED_AD_TYPES:
                report.error(awhere, f"'{kind}' can't be created any more; use a responsive search ad")
            elif kind not in RSA_TYPES:
                report.error(awhere, f"type '{kind}' isn't supported; this skill builds responsive search ads")
            if str(ad.get("status", "paused")).lower() != "paused":
                report.error(awhere, "isn't paused; new ads are created paused")
            heads = [h for h in ad.get("headlines") or [] if text_of(h)]
            descs = [d for d in ad.get("descriptions") or [] if text_of(d)]
            if not MIN_HEADLINES <= len(heads) <= MAX_HEADLINES:
                report.error(awhere, f"needs {MIN_HEADLINES} to {MAX_HEADLINES} headlines, has {len(heads)}")
            if not MIN_DESCRIPTIONS <= len(descs) <= MAX_DESCRIPTIONS:
                report.error(awhere, f"needs {MIN_DESCRIPTIONS} to {MAX_DESCRIPTIONS} descriptions, has {len(descs)}")
            if len(heads) < MAX_HEADLINES or len(descs) < MAX_DESCRIPTIONS:
                report.warn(awhere, f"has {len(heads)} headlines and {len(descs)} descriptions; Google's Ad Strength guidance "
                            f"is to provide up to {MAX_HEADLINES} and {MAX_DESCRIPTIONS}")
            for label, items, limit, is_head in (("headline", heads, HEADLINE_MAX, True),
                                                 ("description", descs, DESCRIPTION_MAX, False)):
                seen = set()
                for i, item in enumerate(items, 1):
                    t = text_of(item)
                    if width(t) > limit:
                        report.error(awhere, f"{label} {i} is {width(t)} characters, over {limit}: '{t}'")
                    if t.lower() in seen:
                        report.error(awhere, f"duplicate {label}: '{t}'")
                    seen.add(t.lower())
                    lint_text(report, awhere, f"{label} {i}", t, is_head)
                    check_claim(report, spec, awhere, f"{label} {i}", item, ctx)
                    if isinstance(item, dict) and item.get("pin"):
                        report.warn(awhere, f"{label} {i} is pinned; pins limit Ad Strength and are set by hand in Editor")
            for key in ("path1", "path2"):
                value = str(ad.get(key, "") or "")
                if width(value) > PATH_MAX:
                    report.error(awhere, f"{key} is {width(value)} characters, over {PATH_MAX}: '{value}'")
            url = str(ad.get("final_url") or group.get("final_url") or "")
            if not url:
                report.error(awhere, "has no final_url")
            elif not is_url(url):
                report.error(awhere, f"final_url must be a full URL starting with https://: '{url}'")
            else:
                all_final_urls.add(url.rstrip("/"))
                hosts.add(host(url))
            kw_texts = [norm(k.get("text", "")) for k in kws]
            if kw_texts and not any(k and k in norm(text_of(h)) for h in heads for k in kw_texts):
                report.warn(awhere, "no headline contains one of the ad group's keywords whole; Google's Ad Strength "
                            "guidance is to put a keyword entirely in a headline")
            heads_by_ad.append({text_of(h).lower() for h in heads})
        for i in range(len(heads_by_ad)):
            for j in range(i + 1, len(heads_by_ad)):
                a, b = heads_by_ad[i], heads_by_ad[j]
                if a and b and len(a & b) * 2 > min(len(a), len(b)):
                    report.warn(where, f"ads {i + 1} and {j + 1} share most of their headlines, so they test little")

        for neg in group.get("negatives") or []:
            check_negative(report, f"{where} negative '{neg.get('keyword', '')}'", neg, "ad_group", group,
                           groups=groups, ctx=ctx)
    for gname, count in group_names.items():
        if gname and count > 1:
            report.error("campaign", f"ad group name '{gname}' is used {count} times")

    negs = spec.get("negatives") or []
    total_negs = len(negs) + sum(len(g.get("negatives") or []) for g in groups)
    if total_negs > NEGATIVES_PER_CAMPAIGN:
        report.error("campaign", f"{total_negs} negatives, over Google's {NEGATIVES_PER_CAMPAIGN} per campaign")
    seen_neg = set()
    for neg in negs:
        key = (norm(neg.get("keyword", "")), str(neg.get("match_type", "")).lower())
        nwhere = f"campaign negative '{neg.get('keyword', '')}'"
        if key in seen_neg:
            report.error(nwhere, "is listed twice")
        seen_neg.add(key)
        check_negative(report, nwhere, neg, "campaign", None, groups=groups, ctx=ctx)

    # Sitelinks and callouts.
    sitelinks = spec.get("sitelinks") or []
    if len(sitelinks) < SITELINKS_TO_SHOW:
        report.error("sitelinks", f"{len(sitelinks)} sitelinks; at least {SITELINKS_TO_SHOW} are needed for any to show")
    elif len(sitelinks) < SITELINKS_FOR_AD_STRENGTH:
        report.warn("sitelinks", f"{len(sitelinks)} sitelinks; Google says {SITELINKS_FOR_AD_STRENGTH} or more improve Ad Strength")
    if len(sitelinks) > SITELINKS_MAX:
        report.warn("sitelinks", f"{len(sitelinks)} sitelinks; Google suggests no more than {SITELINKS_MAX} per level")
    seen_links = set()
    for i, link in enumerate(sitelinks, 1):
        swhere = f"sitelink {i}"
        t = text_of(link)
        if not t:
            report.error(swhere, "has no text")
        if width(t) > SITELINK_TEXT_MAX:
            report.error(swhere, f"text is {width(t)} characters, over {SITELINK_TEXT_MAX}: '{t}'")
        if t.lower() in seen_links:
            report.error(swhere, f"duplicate sitelink text '{t}'")
        seen_links.add(t.lower())
        d1, d2 = str(link.get("description1", "") or ""), str(link.get("description2", "") or "")
        if bool(d1) != bool(d2):
            report.error(swhere, "fill both description lines or neither")
        for label, d in (("description 1", d1), ("description 2", d2)):
            if width(d) > SITELINK_DESC_MAX:
                report.error(swhere, f"{label} is {width(d)} characters, over {SITELINK_DESC_MAX}: '{d}'")
            if d:
                lint_text(report, swhere, label, d, False)
                check_claim(report, spec, swhere, label, {"text": d, "source": source_of(link)}, ctx)
        lint_text(report, swhere, "text", t, True)
        check_claim(report, spec, swhere, "text", link, ctx)
        url = str(link.get("final_url", ""))
        if not is_url(url):
            report.error(swhere, f"final_url must start with https://: '{url}'")
        else:
            hosts.add(host(url))
            if all_final_urls and {url.rstrip("/")} == all_final_urls:
                report.warn(swhere, "points to the same page as every ad; sitelinks work best on other pages")
    callouts = spec.get("callouts") or []
    if len(callouts) < CALLOUTS_SUGGESTED:
        report.warn("callouts", f"{len(callouts)} callouts; at least {CALLOUTS_SUGGESTED} lets several show at once")
    seen_callouts = set()
    for i, item in enumerate(callouts, 1):
        t = text_of(item)
        cwhere = f"callout {i}"
        if width(t) > CALLOUT_MAX:
            report.error(cwhere, f"is {width(t)} characters, over {CALLOUT_MAX}: '{t}'")
        if t.lower() in seen_callouts:
            report.error(cwhere, f"duplicate callout '{t}'")
        seen_callouts.add(t.lower())
        lint_text(report, cwhere, "text", t, True)
        check_claim(report, spec, cwhere, "text", item, ctx)
    if len({h for h in hosts if h}) > 1:
        report.warn("campaign", f"final URLs use more than one domain: {sorted(h for h in hosts if h)}")
    if ctx.get("bid_on_competitors", "").startswith("no"):
        for text, _kw, group in planned:
            for comp in ctx.get("competitors", []):
                if comp and comp.lower() in norm(text):
                    report.warn(f"ad group '{group.get('name', '')}' keyword '{text}'",
                                f"contains competitor '{comp}'; the context file says not to bid on competitor names")
    return report


def words(text: str) -> set[str]:
    return set(re.findall(r"[\w'-]+", str(text).lower()))


def check_negative(report: Report, where: str, neg: dict, level: str, group: dict | None, groups, ctx):
    text = str(neg.get("keyword", ""))
    match = str(neg.get("match_type", "")).lower()
    if not text.strip():
        report.error(where, "has no keyword")
        return
    if match not in MATCH_TYPES:
        report.error(where, "match_type must be exact, phrase, or broad")
    check_keyword_text(report, where, text)
    src = str(neg.get("source", "")).lower()
    if src not in NEGATIVE_SOURCES:
        report.error(where, f"source must be one of {sorted(NEGATIVE_SOURCES)}; starting negatives come from the "
                     "context's Terms we don't want, the person, or routing between ad groups")
    if src == "terms_we_dont_want" and ctx.get("loaded"):
        if not words(text) & set().union(*[words(u) for u in ctx.get("unwanted", [])] or [set()]):
            report.warn(where, "source says Terms we don't want, but no listed term shares a word with it")
    neg_tokens = tokens(text)
    scope = groups if level == "campaign" else [group]
    for g in scope:
        for kw in g.get("keywords") or []:
            if negative_blocks(neg_tokens, match, tokens(kw.get("text", ""))):
                report.error(where, f"would block planned keyword '{kw.get('text')}' in ad group '{g.get('name', '')}'")
    for term in ctx.get("protected", []):
        if negative_blocks(neg_tokens, match, tokens(term)) or set(neg_tokens) & set(tokens(term)):
            report.warn(where, f"touches protected term '{term}'")


# ---------------------------------------------------------------- summaries shared with the other scripts

def counts(spec: dict) -> dict:
    groups = spec.get("ad_groups") or []
    kws = [k for g in groups for k in g.get("keywords") or []]
    ads = [a for g in groups for a in ads_of(g)]
    out = {
        "ad_groups": len(groups),
        "keywords": len(kws),
        "keywords_exact": sum(1 for k in kws if str(k.get("match_type")).lower() == "exact"),
        "keywords_phrase": sum(1 for k in kws if str(k.get("match_type")).lower() == "phrase"),
        "keywords_broad": sum(1 for k in kws if str(k.get("match_type")).lower() == "broad"),
        "keywords_with_volume": sum(1 for k in kws if k.get("avg_monthly_searches") not in (None, "", "MISSING")),
        "campaign_negatives": len(spec.get("negatives") or []),
        "ad_group_negatives": sum(len(g.get("negatives") or []) for g in groups),
        "responsive_search_ads": len(ads),
        "headlines": sum(len([h for h in a.get("headlines") or [] if text_of(h)]) for a in ads),
        "descriptions": sum(len([d for d in a.get("descriptions") or [] if text_of(d)]) for a in ads),
        "sitelinks": len(spec.get("sitelinks") or []),
        "callouts": len(spec.get("callouts") or []),
        "locations": len(campaign_of(spec).get("locations") or []),
        "excluded_locations": len(campaign_of(spec).get("excluded_locations") or []),
    }
    return out


def budget_math(spec: dict, ctx: dict | None = None) -> dict:
    camp = campaign_of(spec)
    daily = num(camp.get("daily_budget"))
    out = {"daily_budget": daily, "monthly_cap": None, "max_single_day": None,
           "conversions_per_day_at_target": None, "clicks_per_day": None}
    if daily:
        out["monthly_cap"] = round(daily * DAYS_PER_MONTH, 2)
        out["max_single_day"] = round(daily * MAX_DAY_MULTIPLIER, 2)
        target = num(camp.get("target_cpa")) or (ctx or {}).get("target_cpa")
        if target:
            out["conversions_per_day_at_target"] = round(daily / target, 2)
            out["target_cpa_used"] = target
        cpc = num(camp.get("expected_cpc"))
        if cpc:
            out["clicks_per_day"] = round(daily / cpc, 1)
            out["expected_cpc"] = cpc
    return out


def by_hand_steps(spec: dict, written: set[str] | None = None) -> list[str]:
    """Settings Editor files can't set reliably. The person does these in Editor before posting."""
    written = written or set()
    camp = campaign_of(spec)
    name = camp.get("name", "")
    ai = ai_max_of(camp)
    steps = []
    if ai.get("enabled") is False:
        verb = "Check that AI Max shows Off" if "ai_max" in written else "Turn AI Max off"
        steps.append(f"{verb} for '{name}' (campaign settings). New Search campaigns start with AI Max on. "
                     "Text customization and Final URL expansion should be off too.")
    elif ai.get("enabled") is True:
        steps.append(f"Check AI Max is on for '{name}', with Text customization "
                     f"{'on' if ai.get('text_customization') else 'off'} and Final URL expansion "
                     f"{'on' if ai.get('final_url_expansion') else 'off'}. Add URL exclusions for pages that "
                     "shouldn't get ad traffic.")
    option = "Presence or interest" if str(camp.get("location_option", "presence")).lower() == "presence_or_interest" else "Presence"
    if "location_option" in written:
        steps.append(f"Check that Location options > Target shows {option}.")
    else:
        steps.append(f"Set Location options > Target to {option} (people in or regularly in your locations). "
                     "Google's default is Presence or interest.")
    eu = str(camp.get("eu_political_ads", "")).lower()
    if eu == "no" and "eu_political_ads" not in written:
        steps.append("Set EU political ads to: this campaign doesn't have EU political ads (the declaration Google "
                     "requires on new campaigns).")
    elif eu == "yes":
        steps.append("Set EU political ads to: has EU political ads. It won't serve in the EU.")
    for loc in camp.get("excluded_locations") or []:
        steps.append(f"Exclude location '{loc.get('name')}' (Locations tab, add as excluded).")
    for loc in camp.get("locations") or []:
        if loc.get("radius") not in (None, "") and (num(loc.get("lat")) is None or num(loc.get("lng")) is None):
            steps.append(f"Add a {loc.get('radius')} {loc.get('unit', 'mi')} radius around {loc.get('label') or 'the address'} "
                         "(Locations tab, radius).")
    for group in spec.get("ad_groups") or []:
        for i, ad in enumerate(ads_of(group), 1):
            for kind, items in (("Headline", ad.get("headlines") or []), ("Description", ad.get("descriptions") or [])):
                for item in items:
                    if isinstance(item, dict) and item.get("pin"):
                        steps.append(f"Pin '{text_of(item)}' to {kind} position {item['pin']} in ad {i} of "
                                     f"'{group.get('name')}'.")
    for shared in camp.get("shared_negative_lists") or []:
        steps.append(f"Attach the shared negative keyword list '{shared}' to '{name}' (Shared library).")
    goals = camp.get("conversion_goals") or {}
    if goals.get("primary"):
        steps.append(f"Check the conversion goals: the campaign should bid for {', '.join(goals['primary'])}. New "
                     "campaigns use the account's default goals; change them in Google Ads after posting if they differ.")
    return steps


# ---------------------------------------------------------------- command line

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build")
    parser.add_argument("--context")
    parser.add_argument("--existing", nargs="*", default=None)
    parser.add_argument("--keyword-data")
    parser.add_argument("--today")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    spec = load_spec(args.build)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = {"protected": [], "unwanted": [], "avoid": [], "competitors": []}
    notes = []
    if args.context:
        if Path(args.context).exists():
            ctx = parse_context(args.context)
        else:
            notes.append(f"context file not found: {args.context}; protected terms and copy rules weren't checked")
    existing = load_existing(args.existing) if args.existing else None
    keyword_data = load_keyword_data(args.keyword_data) if args.keyword_data else None
    report = check_build(spec, ctx, existing, keyword_data, today)
    for n in notes:
        report.warn("-", n)
    c = counts(spec)
    money = budget_math(spec, ctx)

    if args.json:
        print(json.dumps({"errors": report.errors(), "warnings": report.warnings(), "counts": c, "budget": money,
                          "by_hand": by_hand_steps(spec), "unconfirmed_sources": unconfirmed_sources(spec)}, indent=2))
    else:
        camp = campaign_of(spec)
        print(f"Build: {spec.get('name', args.build)}")
        print(f"Creates 1 new Search campaign '{camp.get('name', '')}' with {c['ad_groups']} ad groups, "
              f"{c['keywords']} keywords ({c['keywords_exact']} exact, {c['keywords_phrase']} phrase, "
              f"{c['keywords_broad']} broad), {c['campaign_negatives'] + c['ad_group_negatives']} negatives, "
              f"{c['responsive_search_ads']} responsive search ads, {c['sitelinks']} sitelinks, {c['callouts']} callouts. "
              "All paused.")
        if existing is not None:
            print(f"Checked against {len(existing['campaigns'])} existing campaigns and {len(existing['keywords'])} keywords.")
        print(f"\nErrors: {len(report.errors())}")
        for item in report.errors():
            print(f"  [{item['where']}] {item['message']}")
        print(f"\nWarnings: {len(report.warnings())}")
        for item in report.warnings():
            print(f"  [{item['where']}] {item['message']}")
    return 1 if report.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
