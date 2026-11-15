#!/usr/bin/env python3
"""Advertiser-side checks for AI Max for Search and Performance Max.

Every number in a review comes from this script or from metrics.py, never
from the model's arithmetic. Inputs are CSVs written by normalize.py (GAQL
results or Google Ads exports). Column names are matched loosely, so both
GAQL-named files and web interface downloads work.

Commands:
  channels    Where the spend went, by channel and network, per campaign.
                review.py channels channels.csv [--target-cpa 80] [--target-roas 4]
  terms       Search terms split into brand, competitor, irrelevant, and other,
              plus overlap with your exact-match keywords and AI Max match sources.
                review.py terms pmax_terms.csv aimax_terms.csv --campaigns campaigns.csv
                    --keywords keywords.csv --brand "acme,akme" --context .agents/google-ads-context.md
                    [--labels labels.csv] [--totals campaign_perf.csv] [--target-cpa 80]
                    [--window 2026-10-18:2026-11-14] [--candidates candidates.csv]
  landing     Where final URL expansion sent people, and how those pages convert.
                review.py landing landing_pages.csv --advertiser-urls ads.csv [--target-cpa 80]
  placements  Performance Max placements that look like apps or low-quality sites.
                review.py placements placements.csv [--extra-tlds co.uk,ca]
  assets      Asset counts per asset group against Google's published minimums.
                review.py assets asset_group_assets.csv [--groups asset_groups.csv]
  conversions Which conversion actions each campaign's conversions come from.
                review.py conversions conversions_by_action.csv [--actions conversion_actions.csv]
                    [--low-value "Page view,Newsletter signup"]
  budget      Budget, bid strategy, campaign target, and results against your economics.
                review.py budget --settings campaigns.csv --performance campaign_perf.csv --days 28
                    [--target-cpa 80 --breakeven-cpa 120] [--target-roas 4 --breakeven-roas 2.5]
  timing      Waiting periods, learning status, and window problems before judging.
                review.py timing --window 2026-10-18:2026-11-14 [--events events.csv]
                    [--campaigns campaigns.csv] [--lag 7] [--today 2026-11-15]

Add --markdown for a Markdown table and --out FILE to save the main table.
Commands with a per-row list take --detail FILE. Notes go to stderr.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import sys
from collections import OrderedDict
from pathlib import Path

# Logical field -> column names normalize.py can produce (GAQL and web exports).
COLUMNS = {
    "campaign": ["campaign"],
    "campaign_type": ["campaign_type"],
    "search_term": ["search_term", "campaign_search_term_view_search_term",
                    "ai_max_search_term_ad_combination_view_search_term"],
    "match_source": ["segments_search_term_match_source", "search_term_match_source", "source"],
    "network": ["network", "segments_ad_network_type", "channel"],
    "url": ["expanded_landing_page_view_expanded_final_url", "expanded_landing_page", "landing_page",
            "final_url_expansion_asset_view_final_url", "ai_max_search_term_ad_combination_view_landing_page",
            "expanded_final_url", "final_url"],
    "selected_by": ["selected_by"],
    "placement": ["performance_max_placement_view_placement", "performance_max_placement", "placement"],
    "placement_type": ["performance_max_placement_view_placement_type", "performance_max_placement_type",
                       "placement_type"],
    "display_name": ["performance_max_placement_view_display_name", "display_name"],
    "target_url": ["performance_max_placement_view_target_url", "target_url"],
    "asset_group": ["asset_group_name", "asset_group"],
    "field_type": ["asset_group_asset_field_type", "campaign_asset_field_type", "field_type", "asset_type"],
    "asset_status": ["asset_group_asset_status", "campaign_asset_status", "asset_status", "status"],
    "asset_text": ["asset_text_asset_text", "asset"],
    "asset_source": ["asset_group_asset_source", "added_by", "source"],
    "ad_strength": ["asset_group_ad_strength", "ad_strength"],
    "conversion_action": ["conversion_action"],
    "primary_for_goal": ["conversion_action_primary_for_goal", "primary_for_goal", "action_optimization"],
    "bid_strategy": ["bid_strategy_type"],
    "budget": ["budget"],
    "budget_shared": ["budget_shared"],
    "status_reasons": ["campaign_primary_status_reasons", "primary_status_reasons"],
    "primary_status": ["campaign_primary_status", "primary_status"],
    "ai_max": ["campaign_ai_max_setting_enable_ai_max"],
    "search_theme": ["asset_group_signal_search_theme_text", "search_theme", "search_themes"],
    "keyword": ["keyword"],
    "match_type": ["match_type"],
    "is_negative": ["is_negative"],
    "keyword_status": ["keyword_status"],
}
TARGET_CPA_COLUMNS = ["campaign_target_cpa_target_cpa", "campaign_maximize_conversions_target_cpa"]
TARGET_ROAS_COLUMNS = ["campaign_target_roas_target_roas", "campaign_maximize_conversion_value_target_roas"]
METRICS = ["impressions", "clicks", "cost", "conversions", "conversion_value", "all_conversions"]

NETWORK_NAMES = {
    "search": "Google Search", "google search": "Google Search", "google_search": "Google Search",
    "search_partners": "Search partners", "search partners": "Search partners",
    "content": "Display", "display network": "Display", "display": "Display", "google display network": "Display",
    "youtube": "YouTube", "youtube videos": "YouTube", "google_tv": "Google TV", "google tv": "Google TV",
    "gmail": "Gmail", "discover": "Discover", "discover feed": "Discover", "maps": "Maps", "google maps": "Maps",
    "mixed": "Cross-network (not split)", "cross-network": "Cross-network (not split)",
    "google_owned_channels": "Google owned channels (historical)",
}
SOURCE_NAMES = {
    "advertiser_provided_keyword": "your keywords", "ai_max_broad_match": "AI Max broad match",
    "ai_max_keywordless": "AI Max keywordless", "performance_max": "Performance Max",
    "dynamic_search_ads": "Dynamic Search Ads", "vertical_ads_data_feed": "vertical ads data feed",
}
CHANNEL_DATA_START = "2025-06-01"   # Performance Max channel data exists only from this date
BIDDING_CHANGE_DATE = "2026-08-17"  # budget-limited tCPA/tROAS spend toward target from this date

WAIT_DAYS = {  # event: (days, adds conversion lag, basis)
    "ai_max_enabled": (14, False, "Google: about two weeks after turning on AI Max"),
    "assets_changed": (21, False, "Google: two to three weeks before replacing Performance Max assets"),
    "target_changed": (14, True, "Google Smart Bidding guidance: two weeks, ending one conversion delay back"),
    "bid_strategy_changed": (14, True, "Google Smart Bidding guidance: two weeks, ending one conversion delay back"),
    "conversion_goal_changed": (14, True, "default here: goal changes retrain bidding"),
    "budget_changed": (7, False, "default here, as in the change log; Google: one to two conversion cycles after a raise"),
    "url_expansion_changed": (14, False, "default here; Google: settings take 24 to 48 hours to apply"),
    "negatives_added": (14, False, "default here"),
    "brand_exclusion_changed": (14, False, "default here"),
    "campaign_launched": (14, True, "default here"),
    "status_changed": (7, False, "default here"),
    "other": (14, False, "default here"),
}
CHANGE_LOG_ACTIONS = {
    "set_target": "target_changed", "set_bid_strategy": "bid_strategy_changed", "enable_ai_max": "ai_max_enabled",
    "add_assets": "assets_changed", "set_budget": "budget_changed", "add_negative": "negatives_added",
    "remove_negative": "negatives_added", "set_status": "status_changed", "add_keyword": "other",
    "add_rsa": "other", "set_keyword_bid": "target_changed", "other": "other",
}

# Asset group minimums and recommendations from Google's Performance Max specs (checked November 2026).
ASSET_RULES = OrderedDict([
    ("HEADLINE", ("headlines", 3, 11)),
    ("LONG_HEADLINE", ("long_headlines", 1, 2)),
    ("DESCRIPTION", ("descriptions", 2, 4)),
    ("MARKETING_IMAGE", ("landscape_images", 1, 4)),
    ("SQUARE_MARKETING_IMAGE", ("square_images", 1, 4)),
    ("PORTRAIT_MARKETING_IMAGE", ("portrait_images", 0, 2)),
    ("LOGO", ("logos", 1, 1)),
    ("LANDSCAPE_LOGO", ("landscape_logos", 0, 1)),
    ("YOUTUBE_VIDEO", ("videos", 0, 3)),
    ("BUSINESS_NAME", ("business_name", 1, 1)),
])
CAMPAIGN_LEVEL_OK = {"LOGO", "LANDSCAPE_LOGO", "BUSINESS_NAME"}  # brand guidelines move these to the campaign

DEFAULT_REVIEW_PATTERNS = ["career", "careers", "jobs", "job", "hiring", "blog", "news", "press", "login",
                           "signin", "sign-in", "account", "privacy", "terms", "cookie", "legal", "investor",
                           "sitemap", "search", "cart", "checkout", "404"]
DEFAULT_SAFE_TLDS = ["com", "org", "net", "edu", "gov"]
DEFAULT_SPAM_WORDS = ["free", "game", "games", "apk", "mod", "hack", "cheat", "coupon", "prize", "lottery",
                      "casino", "wallpaper", "horoscope", "quiz", "download", "torrent", "crack", "vpn"]
NOT_ACTIONABLE = ["google owned & operated", "google owned and operated", "anonymous.google",
                  "video no longer available"]

notes: list[str] = []
MISSING_METRICS: set[str] = set()
DEPENDS = {  # metric missing from the input -> output columns that become MISSING
    "impressions": {"impressions", "impression_share"},
    "clicks": {"clicks", "click_share", "cvr", "disclosed_clicks", "disclosed_share", "verdict", "vs_your_pages"},
    "cost": {"cost", "cost_share", "cpa", "roas", "avg_daily_cost", "spend_vs_budget", "actual_cpa", "actual_roas",
             "disclosed_cost", "verdict", "vs_your_target", "vs_breakeven"},
    "conversions": {"conversions", "conv_share", "cpa", "cvr", "actual_cpa", "verdict", "vs_your_pages",
                    "vs_your_target", "vs_breakeven", "low_value_share"},
}


def note(message: str) -> None:
    if message not in notes:
        notes.append(message)


# ---------- helpers ----------

def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def find_col(rows: list[dict], logical: str, extra: list[str] | None = None) -> str | None:
    if not rows:
        return None
    keys = set(rows[0].keys())
    for name in (extra or []) + COLUMNS.get(logical, []):
        if name in keys:
            return name
    return None


def need_col(rows: list[dict], logical: str, path: str) -> str:
    col = find_col(rows, logical)
    if not col:
        sys.exit(f"{path}: no column for {logical}. Expected one of: {', '.join(COLUMNS[logical])}")
    return col


def num(value) -> float:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def div(a: float, b: float):
    return a / b if b else None


def money(v) -> str:
    return "" if v is None else f"{v:.2f}"


def count(v) -> str:
    return "" if v is None else f"{v:.0f}"


def conv(v) -> str:
    if v is None:
        return ""
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def pct(v) -> str:
    return "" if v is None else f"{v * 100:.1f}%"


def ratio(v) -> str:
    return "" if v is None else f"{v:.2f}"


def plural(n: float, word: str) -> str:
    return f"{n:g} {word}" + ("" if n == 1 else "s")


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def norm_text(text: str) -> str:
    return " ".join(tokens(text))


def phrase_in(term_tokens: list[str], phrase: str) -> bool:
    p = tokens(phrase)
    if not p:
        return False
    n = len(p)
    if any(term_tokens[i:i + n] == p for i in range(len(term_tokens) - n + 1)):
        return True
    joined = "".join(p)
    return len(p) > 1 and joined in term_tokens


def negative_blocks(neg: list[str], match: str, query: list[str]) -> bool:
    """Whether a negative keyword blocks a query. Negatives don't match close variants."""
    if not neg or not query:
        return False
    if match == "exact":
        return neg == query
    if match == "phrase":
        n = len(neg)
        return any(query[i:i + n] == neg for i in range(len(query) - n + 1))
    return set(neg) <= set(query)


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in re.split(r"[,\n;]", value) if v.strip()]


def zero_conv_upper(clicks: float, confidence: float = 0.95):
    if clicks <= 0:
        return None
    return 1 - (1 - confidence) ** (1 / clicks)


def cvr_upper(conversions: float, clicks: float):
    """One-sided 95% upper bound on the conversion rate: exact for zero conversions (as metrics.py),
    Wilson score bound otherwise."""
    if clicks <= 0:
        return None
    if conversions <= 0:
        return zero_conv_upper(clicks)
    z, n = 1.645, clicks
    p = min(conversions / n, 1.0)
    centre = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return min((centre + spread) / (1 + z * z / n), 1.0)


def verdict(agg: dict, target_cpa: float | None, target_roas: float | None) -> str:
    """Call a row worse than target only when the data rules out converting at the rate the target needs."""
    if target_cpa:
        clicks, cost, convs = agg.get("clicks", 0), agg.get("cost", 0), agg.get("conversions", 0)
        if clicks <= 0:
            return "no clicks"
        breakeven = (cost / clicks) / target_cpa  # conversion rate needed to hit the target at this CPC
        upper = cvr_upper(convs, clicks)
        if convs == 0:
            if upper is not None and upper < breakeven:
                return "underperforming (data rules out target)"
            return "not enough data"
        if cost / convs <= target_cpa:
            return "within target CPA"
        if upper is not None and upper < breakeven:
            return "above target CPA (data rules out target)"
        return "above target CPA (not conclusive yet)"
    if target_roas:
        roas = div(agg.get("conversion_value", 0), agg.get("cost", 0))
        if roas is None:
            return "no cost"
        return "at or above target ROAS" if roas >= target_roas else "below target ROAS"
    return ""


def add_metrics(agg: dict, row: dict) -> None:
    for m in METRICS:
        agg[m] = agg.get(m, 0.0) + num(row.get(m))


def window_parts(window: str | None) -> tuple[str, str]:
    if not window:
        return "", ""
    start, _, end = window.partition(":")
    return start.strip(), end.strip()


def track_missing(rows: list[dict], path: str, metrics=("impressions", "clicks", "cost", "conversions")) -> None:
    """Metrics absent from an input are MISSING in the output, never zero."""
    if not rows:
        return
    for m in metrics:
        if m not in rows[0]:
            MISSING_METRICS.add(m)
            note(f"{path} has no {m} column: {m} and everything computed from it is MISSING")


def mask(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    cols: set[str] = set()
    for m in MISSING_METRICS:
        cols |= DEPENDS.get(m, set())
    idx = {i for i, h in enumerate(header) if h in cols}
    if not idx:
        return rows
    return [["MISSING" if i in idx else cell for i, cell in enumerate(r)] for r in rows]


def emit(header: list[str], rows: list[list[str]], markdown: bool, out: str | None, title: str = "") -> None:
    rows = mask(header, rows)
    if markdown:
        lines = ([f"**{title}**", ""] if title else []) + ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        text = "\n".join(lines) + "\n\n"
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        writer.writerows(rows)
        text = buffer.getvalue()
    if out:
        with open(out, "w", newline="", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def write_detail(path: str | None, header: list[str], rows: list[list[str]]) -> None:
    if not path:
        return
    rows = mask(header, rows)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)", file=sys.stderr)


def campaign_types(paths: list[str]) -> dict[str, str]:
    types: dict[str, str] = {}
    for path in paths:
        if not path:
            continue
        rows = read_csv(path)
        c, t = find_col(rows, "campaign"), find_col(rows, "campaign_type")
        if c and t:
            for r in rows:
                if r.get(c) and r.get(t):
                    types[r[c].strip()] = r[t].strip().lower()
    return types


def ai_max_flags(paths: list[str]) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for path in paths:
        if not path:
            continue
        rows = read_csv(path)
        c, a = find_col(rows, "campaign"), find_col(rows, "ai_max")
        if c and a:
            for r in rows:
                flags[(r.get(c) or "").strip()] = (r.get(a) or "").strip().lower() == "true"
    return flags


def kind(campaign_type: str) -> str:
    t = (campaign_type or "").lower().replace(" ", "_")
    if "performance_max" in t or t == "pmax":
        return "pmax"
    if "search" in t:
        return "search"
    return "unknown"


def parse_context(path: str | None) -> dict:
    ctx = {"unwanted": [], "competitors": [], "protected": []}
    if not path or not Path(path).exists():
        if path:
            note(f"context file not found: {path}")
        return ctx
    text = Path(path).read_text(encoding="utf-8")

    def bullets(section: str) -> list[str]:
        m = re.search(rf"(?ms)^##\s+{re.escape(section)}\s*$(.*?)(?=^##\s|\Z)", text)
        items = []
        if m:
            for line in m.group(1).splitlines():
                b = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
                if b and not b.group(1).startswith("[") and ":" not in b.group(1) and "MISSING" not in b.group(1):
                    items.extend(split_list(b.group(1)))
        return items

    ctx["unwanted"] = bullets("Terms we don't want")
    ctx["protected"] = bullets("Protected terms")
    m = re.search(r"(?im)^\s*[-*]\s*Main competitors\s*:\s*(.+)$", text)
    if m and "MISSING" not in m.group(1) and not m.group(1).strip().startswith("["):
        ctx["competitors"] = split_list(m.group(1))
    return ctx


# ---------- channels ----------

def cmd_channels(args) -> None:
    rows = read_csv(args.file)
    track_missing(rows, args.file)
    c = need_col(rows, "campaign", args.file)
    n = need_col(rows, "network", args.file)
    types = campaign_types([args.file, args.campaigns])
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    totals: dict[str, dict] = {}
    unknown = set()
    dates = [r.get("date", "") for r in rows if r.get("date")]
    for r in rows:
        camp = r.get(c, "").strip()
        raw = (r.get(n) or "").strip().lower()
        name = NETWORK_NAMES.get(raw)
        if not name:
            name = raw or "(blank)"
            unknown.add(raw)
        key = (camp, name) if not args.by_type else (kind(types.get(camp, "")), name)
        add_metrics(groups.setdefault(key, {}), r)
        add_metrics(totals.setdefault(key[0], {}), r)
    has_value = any(t.get("conversion_value", 0) for t in totals.values())
    header = ["campaign" if not args.by_type else "campaign_type", "network", "impressions", "clicks", "cost",
              "cost_share", "conversions", "conv_share", "cpa"] + (["conversion_value", "roas"] if has_value else []) + ["verdict"]

    def line(camp: str, name: str, agg: dict, t: dict) -> list[str]:
        cells = [camp, name, count(agg["impressions"]), count(agg["clicks"]), money(agg["cost"]),
                 pct(div(agg["cost"], t["cost"])), conv(agg["conversions"]), pct(div(agg["conversions"], t["conversions"])),
                 money(div(agg["cost"], agg["conversions"]))]
        if has_value:
            cells += [money(agg["conversion_value"]), ratio(div(agg["conversion_value"], agg["cost"]))]
        return cells + [verdict(agg, args.target_cpa, args.target_roas)]

    out = []
    for camp in sorted(totals):
        t = totals[camp]
        for (c2, name), agg in sorted(groups.items(), key=lambda kv: -kv[1].get("cost", 0)):
            if c2 == camp:
                out.append(line(camp, name, agg, t))
        out.append(line(camp, "ALL", t, t))
        mixed = groups.get((camp, NETWORK_NAMES["mixed"]))
        if mixed and t["cost"]:
            note(f"{camp}: {pct(div(mixed['cost'], t['cost']))} of cost is reported as cross-network (not split by channel)")
    emit(header, out, args.markdown, args.out, "Spend by channel and network")
    if unknown - {""}:
        note(f"network values not recognized (shown as-is): {', '.join(sorted(unknown - {''}))}")
    if dates and min(dates) < CHANNEL_DATA_START:
        note(f"rows before {CHANNEL_DATA_START} exist; Performance Max channel splits only exist from that date")
    if not dates:
        note("no date column: can't check the June 1, 2025 channel data start or split the window at changes")


# ---------- terms ----------

def cmd_terms(args) -> None:
    ctx = parse_context(args.context)
    brand = split_list(args.brand)
    competitors = split_list(args.competitors) or ctx["competitors"]
    unwanted = split_list(args.unwanted) + ctx["unwanted"]
    protected = ctx["protected"] + split_list(args.protected)
    brand_campaigns = {b.lower() for b in split_list(args.brand_campaigns)}
    if not brand:
        note("no --brand terms given: brand traffic can't be measured. Pass the brand name and misspellings.")
    labels: dict[str, tuple[str, str]] = {}
    if args.labels:
        for r in read_csv(args.labels):
            term = norm_text(r.get("search_term", ""))
            label = (r.get("label") or "").strip().lower()
            if term and label:
                labels[term] = (label, (r.get("reason") or "").strip())
    types = campaign_types(list(args.files) + [args.campaigns])
    ai_max = ai_max_flags([args.campaigns])
    if not ai_max:
        note("no AI Max setting in --campaigns: AI Max is assumed on only where terms show an AI Max match source")

    # Exact-match positive keywords in Search campaigns, for overlap.
    exact: dict[str, set] = {}
    positives: dict[str, set] = {}
    if args.keywords:
        krows = read_csv(args.keywords)
        kc, kk, km = find_col(krows, "campaign"), need_col(krows, "keyword", args.keywords), need_col(krows, "match_type", args.keywords)
        neg, ks = find_col(krows, "is_negative"), find_col(krows, "keyword_status")
        for r in krows:
            if neg and (r.get(neg) or "").lower() == "true":
                continue
            if ks and (r.get(ks) or "").lower() in ("removed", "paused"):
                continue
            kcamp = (r.get(kc) or "").strip() if kc else ""
            positives.setdefault(norm_text(r.get(kk, "")), set()).add((kcamp, (r.get(km) or "").lower()))
            if (r.get(km) or "").lower() == "exact":
                exact.setdefault(norm_text(r.get(kk, "")), set()).add(kcamp)
    else:
        note("no --keywords file: overlap with your exact-match keywords wasn't checked")

    # Read and merge term rows, refusing inputs that double count.
    seen_campaigns: dict[str, str] = {}
    terms: "OrderedDict[tuple, dict]" = OrderedDict()
    for path in args.files:
        rows = read_csv(path)
        if not rows:
            note(f"{path}: no rows")
            continue
        if any(k.startswith("ai_max_search_term_ad_combination_view") for k in rows[0]) and len(args.files) > 1:
            sys.exit(f"{path}: the AI Max search term and ad combination view overlaps the search terms views. "
                     "Don't sum them; review it on its own.")
        track_missing(rows, path)
        c, s = need_col(rows, "campaign", path), need_col(rows, "search_term", path)
        src = find_col(rows, "match_source") or find_col(rows, "search_term_match_type", ["search_term_match_type"])
        file_campaigns = {r.get(c, "").strip() for r in rows}
        for camp in file_campaigns:
            if camp in seen_campaigns and seen_campaigns[camp] != path:
                sys.exit(f"campaign '{camp}' appears in {seen_campaigns[camp]} and {path}; that double counts. "
                         "Use one search terms source per campaign.")
            seen_campaigns[camp] = path
        for r in rows:
            camp = r.get(c, "").strip()
            source = (r.get(src) or "").strip().lower() if src else ""
            key = (camp, norm_text(r.get(s, "")), source)
            agg = terms.setdefault(key, {"display": r.get(s, "").strip()})
            add_metrics(agg, r)
            if source.replace(" ", "_").startswith("ai_max"):
                ai_max.setdefault(camp, True)  # AI Max matched this term, so AI Max is on

    start, end = window_parts(args.window)
    window_text = f"{start} to {end}" if start else "the review window"
    detail, candidates = [], []
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for (camp, term, source), agg in terms.items():
        ttok = term.split()
        ctype = kind(types.get(camp, ""))
        label, reason = labels.get(term, ("", ""))
        matched = ""
        if label in ("brand", "competitor", "irrelevant", "relevant"):
            cls = "other" if label == "relevant" else label
            matched = f"label: {reason}" if reason else "label"
        else:
            cls = "other"
            for b in brand:
                if phrase_in(ttok, b):
                    cls, matched = "brand", b
                    break
                btok = tokens(b)
                if len(btok) == 1 and len(btok[0]) >= 5 and any(t.startswith(btok[0]) for t in ttok):
                    cls, matched = "brand", f"{b} (as part of a word)"
                    break
            if cls == "other":
                for comp in competitors:
                    if phrase_in(ttok, comp):
                        cls, matched = "competitor", comp
                        break
            if cls == "other":
                for u in unwanted:
                    if phrase_in(ttok, u):
                        cls, matched = "irrelevant", u
                        break
        overlap = sorted(c for c in exact.get(term, set()) if c != camp)
        overlap_text = "; ".join(overlap)
        if cls == "brand" and camp.lower() in brand_campaigns:
            cls = "brand (brand campaign)"
        detail.append([camp, ctype, source, agg["display"], cls, matched, overlap_text, count(agg["impressions"]),
                       count(agg["clicks"]), money(agg["cost"]), conv(agg["conversions"]), money(agg["conversion_value"])])
        gkey_parts = []
        for b in [x.strip() for x in args.by.split(",") if x.strip()]:
            gkey_parts.append(camp if b == "campaign" else SOURCE_NAMES.get(source, source or "(none)")
                              if b == "source" else ctype)
        gkey = tuple(gkey_parts)
        buckets = [cls, "ALL disclosed terms"] + ([] if cls.startswith("brand") else ["ALL except brand"])
        for bucket in buckets:
            add_metrics(groups.setdefault(gkey + (bucket,), {"terms": 0}), agg)
            groups[gkey + (bucket,)]["terms"] += 1
        if overlap:
            add_metrics(groups.setdefault(gkey + ("identical to an exact keyword elsewhere",), {"terms": 0}), agg)
            groups[gkey + ("identical to an exact keyword elsewhere",)]["terms"] += 1

        # Exclusion candidates.
        route, suggestion, smatch = "", "", ""
        brand_text = agg["display"].lower() if matched.startswith("label") else matched.split(" (")[0].lower()
        if cls == "brand" and ctype == "pmax":
            route, suggestion, smatch = ("manual: brand exclusion (brand list) on this Performance Max campaign",
                                         brand_text, "")
        elif cls == "brand" and ctype == "search":
            suggestion, smatch = brand_text, "phrase"
            if ai_max.get(camp):
                route = ("manual: brand exclusion (brand list) on this AI Max campaign, or change set add_negative "
                         "if brand searches belong in a separate brand campaign")
            else:
                route = ("change set: add_negative at campaign level, if brand searches belong in a separate brand "
                         "campaign (brand exclusions need AI Max on)")
        elif cls == "irrelevant" or (cls == "competitor" and args.no_competitor_bidding):
            suggestion = (matched if matched and not matched.startswith("label") else agg["display"]).lower()
            smatch = "phrase" if matched and not matched.startswith("label") else "exact"
            if agg["conversions"] > 0:
                route = "do not exclude yet: it converted; ask the person"
            elif ctype == "pmax":
                route = "manual: Performance Max campaign negative keyword or negative keyword list"
            elif ctype == "search":
                route = "change set: add_negative at campaign level"
            else:
                route = "check the campaign type first"
            if route.startswith(("manual", "change set")) and any(
                    phrase_in(tokens(p), suggestion) or phrase_in(tokens(suggestion), p) for p in protected):
                route = "blocked: touches a protected term in the account context"
        elif cls == "other" and args.target_cpa and agg["conversions"] == 0 and agg["clicks"] > 0:
            v = verdict(agg, args.target_cpa, None)
            if v.startswith("underperforming"):
                route, suggestion, smatch = "review relevance with the person before excluding", agg["display"], "exact"
        if route:
            evidence = (f"{plural(agg['clicks'], 'click')}, {money(agg['cost'])} cost, "
                        f"{plural(round(agg['conversions'], 2), 'conversion')}, {window_text}")
            candidates.append([camp, ctype, source, agg["display"], cls, route, suggestion, smatch, count(agg["clicks"]),
                               money(agg["cost"]), conv(agg["conversions"]), verdict(agg, args.target_cpa, None), evidence])

    # Summary with shares inside each group.
    group_totals = {k[:-1]: v for k, v in groups.items() if k[-1] == "ALL disclosed terms"}
    order = ["brand", "brand (brand campaign)", "competitor", "irrelevant", "other",
             "identical to an exact keyword elsewhere", "ALL except brand", "ALL disclosed terms"]
    header = [b.strip() for b in args.by.split(",") if b.strip()] + [
        "class", "terms", "clicks", "cost", "cost_share", "conversions", "conv_share", "cpa", "cvr"]
    out = []
    for key in sorted(groups, key=lambda k: (k[:-1], order.index(k[-1]) if k[-1] in order else 99)):
        agg, tot = groups[key], group_totals.get(key[:-1], {})
        out.append(list(key[:-1]) + [key[-1], str(agg["terms"]), count(agg["clicks"]), money(agg["cost"]),
                   pct(div(agg["cost"], tot.get("cost", 0))), conv(agg["conversions"]),
                   pct(div(agg["conversions"], tot.get("conversions", 0))), money(div(agg["cost"], agg["conversions"])),
                   pct(div(agg["conversions"], agg["clicks"]))])
    emit(header, out, args.markdown, args.out, "Search terms by class")

    # How each campaign's disclosed traffic splits by match source (your keywords vs. AI Max vs. Performance Max).
    by_source: "OrderedDict[tuple, dict]" = OrderedDict()
    camp_tot: dict[str, dict] = {}
    for (camp, _term, source), agg in terms.items():
        add_metrics(by_source.setdefault((camp, source or "(none)"), {"terms": 0}), agg)
        by_source[(camp, source or "(none)")]["terms"] += 1
        add_metrics(camp_tot.setdefault(camp, {}), agg)
    if any(s != "(none)" for _c, s in by_source):
        srows = []
        for (camp, source), agg in sorted(by_source.items(), key=lambda kv: (kv[0][0], -kv[1]["cost"])):
            t = camp_tot[camp]
            srows.append([camp, SOURCE_NAMES.get(source, source), str(agg["terms"]), count(agg["clicks"]), money(agg["cost"]),
                          pct(div(agg["cost"], t["cost"])), conv(agg["conversions"]), pct(div(agg["conversions"], t["conversions"])),
                          money(div(agg["cost"], agg["conversions"])), pct(div(agg["conversions"], agg["clicks"])),
                          verdict(agg, args.target_cpa, None)])
        emit(["campaign", "match_source", "terms", "clicks", "cost", "cost_share", "conversions", "conv_share", "cpa",
              "cvr", "verdict"], srows, args.markdown, None, "Disclosed search terms by match source")

    # Proposed exclusions, grouped so one negative or brand exclusion shows everything it would cover.
    if candidates:
        # Each proposed exclusion is checked against every disclosed term in its campaign, so the evidence shows
        # everything it would block, including terms that converted.
        grouped: "OrderedDict[tuple, None]" = OrderedDict((tuple(c[0:1] + c[5:8]), None) for c in candidates)
        grows = []
        for (camp, route, text, match) in grouped:
            g = {"terms": 0, "clicks": 0.0, "cost": 0.0, "conversions": 0.0}
            converting = []
            for (tcamp, term, _source), agg in terms.items():
                if tcamp != camp:
                    continue
                ttok = term.split()
                if "brand exclusion" in route:
                    btok = tokens(text)
                    hit = phrase_in(ttok, text) or (len(btok) == 1 and len(btok[0]) >= 5
                                                    and any(t.startswith(btok[0]) for t in ttok))
                else:
                    hit = negative_blocks(tokens(text), match, ttok)
                if not hit:
                    continue
                g["terms"] += 1
                for m in ("clicks", "cost", "conversions"):
                    g[m] += agg[m]
                if agg["conversions"] > 0:
                    converting.append(f"{agg['display']} ({conv(agg['conversions'])})")
            warn = "" if "brand exclusion" in route or not converting else "; ".join(converting[:5])
            grows.append([camp, route, text, match or "", str(g["terms"]), count(g["clicks"]), money(g["cost"]),
                          conv(g["conversions"]), warn,
                          f"{plural(g['terms'], 'search term')}, {plural(g['clicks'], 'click')}, {money(g['cost'])} cost, "
                          f"{plural(round(g['conversions'], 2), 'conversion')}, {window_text}"])
        emit(["campaign", "route", "exclude", "match_type", "terms", "clicks", "cost", "conversions",
              "would_block_converting", "evidence"], grows, args.markdown, None, "Proposed exclusions (grouped)")

    # Performance Max search themes that repeat a Search keyword.
    if args.search_themes:
        th = read_csv(args.search_themes)
        tcol = need_col(th, "search_theme", args.search_themes)
        tc, tg = find_col(th, "campaign"), find_col(th, "asset_group")
        trows_out = []
        for r in th:
            theme = norm_text(r.get(tcol, ""))
            hits = sorted(positives.get(theme, set()))
            if not theme or not hits:
                continue
            exact_hit = any(m == "exact" for _c, m in hits)
            trows_out.append([(r.get(tc) or "").strip() if tc else "", (r.get(tg) or "").strip() if tg else "",
                              r.get(tcol, "").strip(), "; ".join(f"{c} ({m})" for c, m in hits),
                              "exact keyword wins identical searches" if exact_hit
                              else "phrase or broad keyword shares priority with this theme"])
        emit(["campaign", "asset_group", "search_theme", "same_keyword_in", "priority"], trows_out, args.markdown, None,
             "Search themes that repeat a Search keyword")
        if not args.keywords:
            note("--search-themes needs --keywords to compare against")

    # Disclosed share against campaign totals.
    if args.totals:
        trows = read_csv(args.totals)
        tc = need_col(trows, "campaign", args.totals)
        tot: dict[str, dict] = {}
        for r in trows:
            add_metrics(tot.setdefault(r.get(tc, "").strip(), {}), r)
        disclosed: dict[str, dict] = {}
        for (camp, _t, _s), agg in terms.items():
            add_metrics(disclosed.setdefault(camp, {}), agg)
        cov = []
        for camp in sorted(disclosed):
            t, d = tot.get(camp), disclosed[camp]
            if not t:
                cov.append([camp, "", count(d["clicks"]), "", "", "MISSING (campaign not in totals file)"])
                continue
            cov.append([camp, count(t["clicks"]), count(d["clicks"]), pct(div(d["clicks"], t["clicks"])),
                        money(t["cost"]), money(d["cost"])])
        emit(["campaign", "total_clicks", "disclosed_clicks", "disclosed_share", "total_cost", "disclosed_cost"],
             cov, args.markdown, None, "How much of each campaign's traffic the terms report shows")
    else:
        note("no --totals file: shares are of disclosed terms only, not of all campaign traffic")

    write_detail(args.detail, ["campaign", "campaign_kind", "match_source", "search_term", "class", "matched",
                               "exact_keyword_in", "impressions", "clicks", "cost", "conversions", "conversion_value"], detail)
    write_detail(args.candidates, ["campaign", "campaign_kind", "match_source", "search_term", "class", "route",
                                   "suggested_text", "suggested_match_type", "clicks", "cost", "conversions", "verdict",
                                   "evidence"], candidates)
    if exact:
        note("exact overlap compares normalized text only; close variants Google treats as the same aren't counted, "
             "so the overlap is a lower bound")


# ---------- landing ----------

def norm_url(url: str) -> str:
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = re.split(r"[?#]", u)[0]
    return u.rstrip("/")


def cmd_landing(args) -> None:
    rows = read_csv(args.file)
    track_missing(rows, args.file, ("clicks", "cost", "conversions"))
    u = need_col(rows, "url", args.file)
    sel = find_col(rows, "selected_by")
    ccol = None if args.all_campaigns else find_col(rows, "campaign")
    advertiser: dict[str, set] = {}  # campaign ("" = any campaign) -> normalized advertiser URLs
    for path in args.advertiser_urls or []:
        text = Path(path).read_text(encoding="utf-8-sig")
        if path.endswith(".csv"):
            arows = list(csv.DictReader(io.StringIO(text)))
            col = find_col(arows, "url", ["final_url", "asset_group_final_urls", "final_urls"])
            acol = find_col(arows, "campaign") if ccol else None
            for r in arows:
                for part in re.split(r"\s+", (r.get(col) or "") if col else ""):
                    if part.startswith("http"):
                        advertiser.setdefault((r.get(acol) or "").strip() if acol else "", set()).add(norm_url(part))
        else:
            advertiser.setdefault("", set()).update(norm_url(x) for x in text.splitlines() if x.strip().startswith("http"))
    if not advertiser and not sel:
        note("no advertiser final URLs and no 'Selected by' column: pages can't be split into yours vs. expanded")
    patterns = split_list(args.review_patterns) if args.review_patterns else DEFAULT_REVIEW_PATTERNS
    pages: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in rows:
        url = (r.get(u) or "").strip()
        if not url:
            continue
        camp = (r.get(ccol) or "").strip() if ccol else "all campaigns"
        agg = pages.setdefault((camp, norm_url(url)), {"url": url, "selected": set()})
        add_metrics(agg, r)
        if sel and r.get(sel):
            agg["selected"].add(r[sel].strip().lower())
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for (camp, key), agg in pages.items():
        known = advertiser.get(camp, set()) | advertiser.get("", set())
        if agg["selected"]:
            group = ("expanded by Google" if any("ai" in x or "google" in x or "expan" in x for x in agg["selected"])
                     else "advertiser-provided")
        elif known:
            group = "advertiser-provided" if key in known else "expanded by Google"
        else:
            group = "unknown"
        path = "/" + key.split("/", 1)[1] if "/" in key else "/"
        ptoks = set(re.split(r"[/._?=&-]+", path.lower()))
        agg.update(group=group, flags=[x for x in patterns if x.lower() in ptoks])
        for gname in [group] + (["pages matching review patterns"] if agg["flags"] else []) + ["ALL"]:
            g = groups.setdefault((camp, gname), {"pages": 0})
            g["pages"] += 1
            add_metrics(g, agg)
    header = ["campaign", "group", "pages", "clicks", "click_share", "cost", "cost_share", "conversions", "conv_share",
              "cvr", "cpa", "verdict"]
    order = ["advertiser-provided", "expanded by Google", "unknown", "pages matching review patterns", "ALL"]
    out = []
    for (camp, gname), g in sorted(groups.items(), key=lambda kv: (kv[0][0], order.index(kv[0][1]))):
        t = groups[(camp, "ALL")]
        out.append([camp, gname, str(g["pages"]), count(g["clicks"]), pct(div(g["clicks"], t["clicks"])), money(g["cost"]),
                    pct(div(g["cost"], t["cost"])), conv(g["conversions"]), pct(div(g["conversions"], t["conversions"])),
                    pct(div(g["conversions"], g["clicks"])), money(div(g["cost"], g["conversions"])),
                    verdict(g, args.target_cpa, args.target_roas)])
    emit(header, out, args.markdown, args.out, "Landing pages: yours vs. expanded by Google")
    # Each page is compared with the same campaign's advertiser-provided pages.
    detail = []
    for (camp, key), agg in sorted(pages.items(), key=lambda kv: (kv[0][0], -kv[1].get("cost", 0))):
        base = groups.get((camp, "advertiser-provided"))
        base_cvr = div(base["conversions"], base["clicks"]) if base else None
        cvr = div(agg["conversions"], agg["clicks"])
        compare = ""
        if base_cvr is not None and agg["group"] != "advertiser-provided" and agg["clicks"] > 0:
            upper = cvr_upper(agg["conversions"], agg["clicks"])
            if cvr is not None and cvr >= base_cvr:
                compare = "converts at or above your pages"
            elif upper is not None and upper < base_cvr:
                compare = "below your pages (data rules out their rate)"
            else:
                compare = "below your pages (not conclusive yet)" if agg["conversions"] else "not enough data"
        detail.append([camp, agg["url"], agg["group"], "; ".join(agg["flags"]), count(agg["clicks"]), money(agg["cost"]),
                       conv(agg["conversions"]), pct(cvr), money(div(agg["cost"], agg["conversions"])), compare,
                       verdict(agg, args.target_cpa, args.target_roas)])
    dheader = ["campaign", "url", "group", "review_flags", "clicks", "cost", "conversions", "cvr", "cpa", "vs_your_pages",
               "verdict"]
    if args.markdown:
        top = sorted(detail, key=lambda d: -num(d[5]))[:args.top]
        emit(dheader, top, True, None, f"Top {len(top)} landing pages by cost")
    write_detail(args.detail, dheader, detail)
    if u == "final_url_expansion_asset_view_final_url":
        note("this file has one row per asset and URL; one ad shows several assets, so clicks summed by URL can count "
             "the same click more than once. Use it to see which URLs were used, not to total their traffic")
    note("open the top expanded pages before judging them: a URL doesn't say what the page offers")


# ---------- placements ----------

def placement_flags(placement: str, ptype: str, name: str, safe_tlds: list[str], spam: list[str]) -> list[str]:
    """Review prompts for one placement. The method (flag apps, unusual domain endings, generated-looking
    domains, and clickbait video titles) follows Nils Rooijmans' Performance Max placement exclusion
    suggestions script, which has no license; this is our own code and our own default lists."""
    flags: list[str] = []
    p, t, nm = placement.lower(), ptype.lower().replace(" ", "_"), (name or placement or "").strip()
    if "app" in t or p.startswith(("mobileapp::", "mobileappcategory::")):
        return ["mobile app"]
    if "video" in t or "youtube" in t:
        if re.search(r"[!?]{2,}", nm):
            flags.append("repeated !! or ?? in title")
        if re.search(r"(\b[A-Z]{3,}\b\W+){2,}\b[A-Z]{3,}\b", nm):
            flags.append("run of all-caps words in title")
        if re.search(r"[$€£]\s?\d", nm):
            flags.append("money amount in title")
        if re.search(r"\b(kids?|children|nursery|cartoons?)\b", nm, re.IGNORECASE):
            flags.append("children's content signal in title")
        return flags
    domain = re.sub(r"^https?://", "", p).split("/")[0]
    domain = re.sub(r"^www\.", "", domain)
    if not domain or "." not in domain:
        return flags
    if domain.startswith("xn--") or ".xn--" in domain:
        flags.append("punycode domain")
    labels = domain.split(".")
    if not any(domain.endswith("." + tld) or domain == tld for tld in safe_tlds):
        flags.append(f"domain ending .{labels[-1]} not in safe list")
    host = ".".join(labels[:-1]) if len(labels) > 1 else domain
    if host.replace("xn--", "").count("-") >= 2:
        flags.append("two or more hyphens")
    if re.search(r"\d{3,}", host):
        flags.append("run of three or more digits")
    if re.search(r"(.)\1{3,}", host):
        flags.append("same character four or more times")
    if max((len(x) for x in labels), default=0) > 30:
        flags.append("very long domain name")
    words = [w for w in spam if re.search(rf"(^|[^a-z]){re.escape(w)}", host)]
    if words:
        flags.append("spam word: " + ", ".join(words))
    return flags


def cmd_placements(args) -> None:
    rows = read_csv(args.file)
    pcol = need_col(rows, "placement", args.file)
    tcol, ncol = find_col(rows, "placement_type"), find_col(rows, "display_name")
    ccol = find_col(rows, "campaign")
    safe = [t.lower().lstrip(".") for t in (split_list(args.safe_tlds) or DEFAULT_SAFE_TLDS) + split_list(args.extra_tlds)]
    spam = split_list(args.spam_words) if args.spam_words else DEFAULT_SPAM_WORDS
    places: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in rows:
        key = ((r.get(ccol) or "").strip() if ccol else "", (r.get(pcol) or "").strip(),
               (r.get(tcol) or "").strip() if tcol else "", (r.get(ncol) or "").strip() if ncol else "")
        if not key[1]:
            continue
        add_metrics(places.setdefault(key, {}), r)
    if rows and "cost" not in rows[0]:
        note("placement reports carry impressions only; cost, clicks, and conversions per placement are MISSING")
    by_type: dict[str, dict] = {}
    total_impr = sum(a["impressions"] for a in places.values())
    detail = []
    for (camp, placement, ptype, name), agg in sorted(places.items(), key=lambda kv: -kv[1]["impressions"]):
        if agg["impressions"] < args.min_impressions:
            continue
        label = ptype or ("mobile app" if placement.lower().startswith("mobileapp::") else "website")
        lower = (placement + " " + name).lower()
        actionable = not any(x in lower for x in NOT_ACTIONABLE)
        flags = placement_flags(placement, label, name, safe, spam) if actionable else ["not excludable (Google grouping)"]
        bucket = label.lower() if actionable else "not excludable (Google groupings)"
        g = by_type.setdefault(bucket, {"placements": 0, "impressions": 0.0, "flagged": 0, "flagged_impr": 0.0})
        g["placements"] += 1
        g["impressions"] += agg["impressions"]
        if flags and actionable:
            g["flagged"] += 1
            g["flagged_impr"] += agg["impressions"]
            detail.append([camp, placement, label, name, count(agg["impressions"]), pct(div(agg["impressions"], total_impr)),
                           "; ".join(flags)])
    header = ["placement_type", "placements", "impressions", "impression_share", "flagged", "flagged_impressions",
              "flagged_share_of_all"]
    out = [[t, str(g["placements"]), count(g["impressions"]), pct(div(g["impressions"], total_impr)), str(g["flagged"]),
            count(g["flagged_impr"]), pct(div(g["flagged_impr"], total_impr))] for t, g in sorted(by_type.items())]
    emit(header, out, args.markdown, args.out, "Performance Max placements")
    dheader = ["campaign", "placement", "placement_type", "display_name", "impressions", "impression_share", "reasons"]
    if args.markdown and detail:
        emit(dheader, detail[:args.top], True, None, f"Top {min(args.top, len(detail))} flagged placements by impressions")
    write_detail(args.detail, dheader, detail)
    note("flags are review prompts, not verdicts: open each placement before excluding it")


# ---------- assets ----------

def field_kind(value: str) -> str:
    s = (value or "").strip().lower().replace(" ", "_")
    if not s:
        return "OTHER"
    if "long" in s and "headline" in s:
        return "LONG_HEADLINE"
    if "headline" in s:
        return "HEADLINE"
    if "description" in s:
        return "DESCRIPTION"
    if "business" in s:
        return "BUSINESS_NAME"
    if "logo" in s:
        return "LANDSCAPE_LOGO" if ("landscape" in s or "horizontal" in s) else "LOGO"
    if "portrait" in s or "vertical" in s:
        return "PORTRAIT_MARKETING_IMAGE"
    if "square" in s:
        return "SQUARE_MARKETING_IMAGE"
    if "image" in s:
        if s in ("image",):
            note("an export lists images without orientation; landscape and square counts may be off")
        return "MARKETING_IMAGE"
    if "video" in s:
        return "YOUTUBE_VIDEO"
    return "OTHER"


def cmd_assets(args) -> None:
    rows = read_csv(args.file)
    gcol = need_col(rows, "asset_group", args.file)
    fcol = need_col(rows, "field_type", args.file)
    ccol, scol = find_col(rows, "campaign"), find_col(rows, "asset_status")
    xcol, srccol = find_col(rows, "asset_text"), find_col(rows, "asset_source")
    if srccol == "source" and rows and all((r.get("source") or "").upper() in ("", "PERFORMANCE_MAX") for r in rows):
        srccol = None
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in rows:
        status = (r.get(scol) or "").strip().lower() if scol else ""
        if status in ("removed", "paused", "disabled"):
            continue
        key = ((r.get(ccol) or "").strip() if ccol else "", (r.get(gcol) or "").strip())
        g = groups.setdefault(key, {"counts": {}, "short": None, "google": 0})
        fk = field_kind(r.get(fcol, ""))
        g["counts"][fk] = g["counts"].get(fk, 0) + 1
        if fk == "HEADLINE" and xcol and r.get(xcol):
            g["short"] = bool(g["short"]) or len(r[xcol].strip()) <= 15
        if srccol and re.search(r"automatic|google", (r.get(srccol) or ""), re.IGNORECASE):
            g["google"] += 1
    strength: dict[tuple, str] = {}
    if args.groups:
        grows = read_csv(args.groups)
        gc, gn, ga = find_col(grows, "campaign"), need_col(grows, "asset_group", args.groups), find_col(grows, "ad_strength")
        for r in grows:
            strength[((r.get(gc) or "").strip() if gc else "", (r.get(gn) or "").strip())] = (r.get(ga) or "").strip() if ga else ""
    campaign_level: dict[str, set] = {}
    if args.campaign_assets:
        crows = read_csv(args.campaign_assets)
        cc, cf = need_col(crows, "campaign", args.campaign_assets), need_col(crows, "field_type", args.campaign_assets)
        for r in crows:
            campaign_level.setdefault((r.get(cc) or "").strip(), set()).add(field_kind(r.get(cf, "")))
    header = ["campaign", "asset_group"] + [label for label, _mn, _rec in ASSET_RULES.values()] + [
        "headline_15_or_fewer", "google_ai_assets", "ad_strength", "below_minimum", "below_recommended"]
    out = []
    for key, g in groups.items():
        line, below_min, below_rec = list(key), [], []
        for field, (label, minimum, recommended) in ASSET_RULES.items():
            n = g["counts"].get(field, 0)
            at_campaign = field in CAMPAIGN_LEVEL_OK and field in campaign_level.get(key[0], set())
            line.append(f"{n}" + (" (+campaign)" if at_campaign else ""))
            if n < minimum and not at_campaign:
                below_min.append(f"{label} {n} of {minimum}")
            elif n < recommended and not at_campaign:
                below_rec.append(f"{label} {n} of {recommended}")
        short = "MISSING" if g["short"] is None else ("yes" if g["short"] else "no")
        if short == "no":
            below_min.append("no headline of 15 characters or fewer")
        line += [short, str(g["google"]) if srccol else "MISSING", strength.get(key, "MISSING") or "MISSING",
                 "; ".join(below_min) or "none", "; ".join(below_rec) or "none"]
        out.append(line)
    emit(header, out, args.markdown, args.out, "Asset coverage per asset group")
    if not args.campaign_assets:
        note("no --campaign-assets file: business name and logo may sit at the campaign level under brand guidelines; "
             "check before calling them missing")
    note("video orientation isn't in asset group data; 'videos' counts all videos, and Google recommends all three orientations")


# ---------- conversions ----------

def cmd_conversions(args) -> None:
    rows = read_csv(args.file)
    track_missing(rows, args.file, ("conversions",))
    c, a = need_col(rows, "campaign", args.file), need_col(rows, "conversion_action", args.file)
    primary: dict[str, str] = {}
    if args.actions:
        arows = read_csv(args.actions)
        an, ap = need_col(arows, "conversion_action", args.actions), find_col(arows, "primary_for_goal")
        for r in arows:
            primary[(r.get(an) or "").strip().lower()] = (r.get(ap) or "").strip().lower() if ap else ""
    low = {x.lower() for x in split_list(args.low_value)}
    types = campaign_types([args.campaigns]) if args.campaigns else {}
    data: "OrderedDict[tuple, dict]" = OrderedDict()
    totals: dict[str, dict] = {}
    for r in rows:
        camp, action = r.get(c, "").strip(), r.get(a, "").strip()
        add_metrics(data.setdefault((camp, action), {}), r)
        add_metrics(totals.setdefault(camp, {}), r)
    header = ["campaign", "conversion_action", "conversions", "conv_share", "all_conversions", "conversion_value",
              "primary_for_goal", "low_value", "note"]
    out, summary = [], {}
    for (camp, action), agg in sorted(data.items(), key=lambda kv: (kv[0][0], -kv[1]["conversions"])):
        t = totals[camp]
        p = primary.get(action.lower(), "MISSING" if args.actions else "")
        is_low = action.lower() in low
        flag = ""
        if agg["conversions"] == 0 and agg["all_conversions"] > 0:
            flag = "secondary here: reported, not used for bidding"
        elif is_low and agg["conversions"] > 0:
            flag = "low-value action counted in Conversions"
        out.append([camp, action, conv(agg["conversions"]), pct(div(agg["conversions"], t["conversions"])),
                    conv(agg["all_conversions"]), money(agg["conversion_value"]), p, "yes" if is_low else "", flag])
        s = summary.setdefault(camp, {"low": 0.0, "actions": 0})
        if agg["conversions"] > 0:
            s["actions"] += 1
        if is_low:
            s["low"] += agg["conversions"]
    emit(header, out, args.markdown, args.out, "Conversions by action")
    sheader = ["campaign", "campaign_kind", "conversions", "actions_counted", "low_value_share"]
    srows = [[camp, kind(types.get(camp, "")), conv(totals[camp]["conversions"]), str(s["actions"]),
              pct(div(s["low"], totals[camp]["conversions"])) if low else "MISSING (no --low-value list)"]
             for camp, s in summary.items()]
    emit(sheader, srows, args.markdown, None, "Conversion mix per campaign")
    note("conversions by action can't be paired with cost in one query; pull cost from the campaign query")


# ---------- budget ----------

def cmd_budget(args) -> None:
    settings = read_csv(args.settings)
    c = need_col(settings, "campaign", args.settings)
    perf_rows = read_csv(args.performance)
    track_missing(perf_rows, args.performance, ("cost", "conversions"))
    pc = need_col(perf_rows, "campaign", args.performance)
    perf: dict[str, dict] = {}
    for r in perf_rows:
        add_metrics(perf.setdefault(r.get(pc, "").strip(), {}), r)
    has_value = any(p.get("conversion_value", 0) for p in perf.values())
    cols = {k: find_col(settings, k) for k in ("campaign_type", "bid_strategy", "budget", "budget_shared", "status_reasons")}
    tcpa = next((x for x in TARGET_CPA_COLUMNS if settings and x in settings[0]), None)
    troas = next((x for x in TARGET_ROAS_COLUMNS if settings and x in settings[0]), None)
    if not (tcpa or troas):
        note("no campaign target columns in the settings file: campaign targets are MISSING")
    header = ["campaign", "campaign_kind", "bid_strategy", "daily_budget", "avg_daily_cost", "spend_vs_budget",
              "campaign_target", "actual_cpa", "actual_roas", "vs_your_target", "vs_breakeven", "flags"]
    out = []
    for r in settings:
        camp = r.get(c, "").strip()
        p = perf.get(camp, {})
        ctype = kind(r.get(cols["campaign_type"], "")) if cols["campaign_type"] else "unknown"
        strategy = (r.get(cols["bid_strategy"]) or "").lower() if cols["bid_strategy"] else ""
        budget = num(r.get(cols["budget"])) if cols["budget"] else 0.0
        avg = div(p.get("cost", 0.0), args.days)
        spend_ratio = div(avg, budget) if avg is not None and budget else None
        target = ""
        for col in TARGET_CPA_COLUMNS:
            if r.get(col) and num(r[col]) > 0:
                target = f"CPA {money(num(r[col]))}"
        for col in TARGET_ROAS_COLUMNS:
            if r.get(col) and num(r[col]) > 0:
                target = f"ROAS {ratio(num(r[col]))}"
        cpa = div(p.get("cost", 0.0), p.get("conversions", 0.0))
        roas = div(p.get("conversion_value", 0.0), p.get("cost", 0.0)) if has_value else None
        vs_target, vs_be = "MISSING", "MISSING"
        if args.target_cpa:
            vs_target = "" if cpa is None else ("at or under" if cpa <= args.target_cpa else "over")
        elif args.target_roas:
            vs_target = "" if roas is None else ("at or above" if roas >= args.target_roas else "below")
        if args.breakeven_cpa:
            vs_be = "" if cpa is None else ("profitable side" if cpa <= args.breakeven_cpa else "losing money per conversion")
        elif args.breakeven_roas:
            vs_be = "" if roas is None else ("profitable side" if roas >= args.breakeven_roas else "below break-even")
        flags = []
        reasons = (r.get(cols["status_reasons"]) or "").upper() if cols["status_reasons"] else ""
        limited = "BUDGET_CONSTRAINED" in reasons
        near = spend_ratio is not None and 0.95 <= spend_ratio <= 1.05
        if limited:
            flags.append("limited by budget (Google status)")
        elif near:
            flags.append("spending at or near budget")
        if spend_ratio is not None and spend_ratio > 1.05:
            flags.append("average daily cost above the current budget: the budget probably changed inside the window")
        target_based = bool(target) or strategy.startswith(("target_cpa", "target_roas"))
        if target_based and (limited or near):
            flags.append(f"target-based and budget-limited: spends toward its target since {BIDDING_CHANGE_DATE}")
        if "LEARNING" in reasons:
            flags.append("bid strategy learning (Google status)")
        if cols["budget_shared"] and (r.get(cols["budget_shared"]) or "").lower() == "true":
            flags.append("shared budget: a change affects every campaign on it")
        if not p:
            flags.append("no performance rows for this campaign")
        out.append([camp, ctype, strategy, money(budget) if budget else "MISSING", money(avg), pct(spend_ratio),
                    target or ("none" if strategy else "MISSING"), money(cpa), ratio(roas), vs_target, vs_be,
                    "; ".join(flags)])
    emit(header, out, args.markdown, args.out, "Budget and target context")
    if not (args.target_cpa or args.target_roas):
        note("no business target given: 'vs_your_target' is MISSING. Read it from the account context Economics section")


# ---------- timing ----------

def parse_date(value: str):
    try:
        return dt.date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def cmd_timing(args) -> None:
    start_s, end_s = window_parts(args.window)
    start, end = parse_date(start_s), parse_date(end_s)
    if not (start and end):
        sys.exit("--window must be START:END in YYYY-MM-DD form")
    today = parse_date(args.today) if args.today else dt.date.today()
    events: dict[str, list] = {}
    if args.events:
        erows = read_csv(args.events)
        ec = need_col(erows, "campaign", args.events)
        evcol = next((x for x in ("event", "action") if x in erows[0]), None) if erows else None
        dcol = next((x for x in ("date", "applied_at", "change_date_time", "logged_at") if erows and x in erows[0]), None)
        if not (evcol and dcol):
            sys.exit(f"{args.events}: needs campaign, event (or action), and date (or applied_at) columns")
        for r in erows:
            if "status" in r and r["status"] and r["status"].lower() in ("proposed", "rejected"):
                continue
            ev = (r.get(evcol) or "").strip().lower()
            ev = CHANGE_LOG_ACTIONS.get(ev, ev)
            if ev not in WAIT_DAYS:
                note(f"unknown event '{ev}' treated as 'other'")
                ev = "other"
            d = parse_date(r.get(dcol, ""))
            if d:
                events.setdefault((r.get(ec) or "").strip(), []).append((d, ev))
    info: dict[str, dict] = {}
    if args.campaigns:
        crows = read_csv(args.campaigns)
        cc = need_col(crows, "campaign", args.campaigns)
        for r in crows:
            info[(r.get(cc) or "").strip()] = {
                "kind": kind(r.get(find_col(crows, "campaign_type") or "", "")),
                "strategy": (r.get(find_col(crows, "bid_strategy") or "", "") or "").lower(),
                "reasons": (r.get(find_col(crows, "status_reasons") or "", "") or "").upper(),
                "ai_max": (r.get(find_col(crows, "ai_max") or "", "") or "").lower(),
                "has_target": any(num(r.get(x)) > 0 for x in TARGET_CPA_COLUMNS + TARGET_ROAS_COLUMNS),
            }
    campaigns = sorted(set(info) | set(events))
    header = ["campaign", "recorded_changes", "judge_from", "status", "window_notes"]
    out = []
    for camp in campaigns:
        evs = sorted(events.get(camp, []))
        judge_from = None
        listed, wnotes = [], []
        for d, ev in evs:
            days, lag, _basis = WAIT_DAYS[ev]
            ready = d + dt.timedelta(days=days + (args.lag if lag else 0))
            judge_from = max(judge_from, ready) if judge_from else ready
            listed.append(f"{ev} {d.isoformat()}" + (" (before window)" if d < start else ""))
            if start < d <= end:
                wnotes.append(f"window split by {ev} on {d.isoformat()}")
        meta = info.get(camp, {})
        status = []
        if judge_from and judge_from > today:
            status.append(f"wait: too early to judge until {judge_from.isoformat()}")
        if "LEARNING" in meta.get("reasons", ""):
            status.append("bid strategy learning (Google status)")
        if not status:
            status.append("ok to judge")
        if args.lag and end > today - dt.timedelta(days=args.lag):
            wnotes.append(f"last {args.lag} days undercount conversions (conversion delay)")
        target_based = meta.get("has_target") or meta.get("strategy", "").startswith(("target_cpa", "target_roas"))
        if target_based and start.isoformat() < BIDDING_CHANGE_DATE <= end.isoformat():
            wnotes.append(f"crosses {BIDDING_CHANGE_DATE}: target-based bidding behaves differently after it")
        if meta.get("kind") == "pmax" and start.isoformat() < CHANNEL_DATA_START:
            wnotes.append(f"channel splits only exist from {CHANNEL_DATA_START}")
        out.append([camp, "; ".join(listed) or "none recorded", judge_from.isoformat() if judge_from else "",
                    "; ".join(status), "; ".join(wnotes)])
    emit(header, out, args.markdown, args.out, "Timing: can each campaign be judged yet?")
    if not args.events:
        note("no --events file: waiting periods after recent changes weren't checked. Use the change log or change history")
    note("waiting periods: " + "; ".join(f"{k} {v[0]}d{' + lag' if v[1] else ''}" for k, v in WAIT_DAYS.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("channels")
    p.add_argument("file")
    p.add_argument("--campaigns")
    p.add_argument("--by-type", action="store_true")
    p.add_argument("--target-cpa", type=float)
    p.add_argument("--target-roas", type=float)

    p = sub.add_parser("terms")
    p.add_argument("files", nargs="+")
    p.add_argument("--campaigns")
    p.add_argument("--keywords")
    p.add_argument("--search-themes")
    p.add_argument("--totals")
    p.add_argument("--brand")
    p.add_argument("--brand-campaigns")
    p.add_argument("--competitors")
    p.add_argument("--no-competitor-bidding", action="store_true")
    p.add_argument("--unwanted")
    p.add_argument("--protected")
    p.add_argument("--context")
    p.add_argument("--labels")
    p.add_argument("--target-cpa", type=float)
    p.add_argument("--window")
    p.add_argument("--by", default="campaign")
    p.add_argument("--detail")
    p.add_argument("--candidates")

    p = sub.add_parser("landing")
    p.add_argument("file")
    p.add_argument("--advertiser-urls", nargs="*")
    p.add_argument("--all-campaigns", action="store_true")
    p.add_argument("--review-patterns")
    p.add_argument("--target-cpa", type=float)
    p.add_argument("--target-roas", type=float)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--detail")

    p = sub.add_parser("placements")
    p.add_argument("file")
    p.add_argument("--safe-tlds")
    p.add_argument("--extra-tlds")
    p.add_argument("--spam-words")
    p.add_argument("--min-impressions", type=float, default=1)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--detail")

    p = sub.add_parser("assets")
    p.add_argument("file")
    p.add_argument("--groups")
    p.add_argument("--campaign-assets")

    p = sub.add_parser("conversions")
    p.add_argument("file")
    p.add_argument("--actions")
    p.add_argument("--campaigns")
    p.add_argument("--low-value")

    p = sub.add_parser("budget")
    p.add_argument("--settings", required=True)
    p.add_argument("--performance", required=True)
    p.add_argument("--days", type=float, required=True)
    p.add_argument("--target-cpa", type=float)
    p.add_argument("--breakeven-cpa", type=float)
    p.add_argument("--target-roas", type=float)
    p.add_argument("--breakeven-roas", type=float)

    p = sub.add_parser("timing")
    p.add_argument("--window", required=True)
    p.add_argument("--events")
    p.add_argument("--campaigns")
    p.add_argument("--lag", type=int, default=0)
    p.add_argument("--today")

    for name in ("channels", "terms", "landing", "placements", "assets", "conversions", "budget", "timing"):
        sp = sub.choices[name]
        sp.add_argument("--markdown", action="store_true")
        sp.add_argument("--out")

    args = parser.parse_args()
    handlers = {"channels": cmd_channels, "terms": cmd_terms, "landing": cmd_landing, "placements": cmd_placements,
                "assets": cmd_assets, "conversions": cmd_conversions, "budget": cmd_budget, "timing": cmd_timing}
    handlers[args.command](args)
    for message in notes:
        print(f"note: {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
