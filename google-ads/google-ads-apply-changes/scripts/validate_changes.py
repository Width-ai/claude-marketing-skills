#!/usr/bin/env python3
"""Check a Google Ads change set before anyone approves or applies it.

Errors (exit code 1) block the batch:
  - unknown actions, missing fields, invalid values, deletes
  - campaign or ad group names not found in the snapshot (an Editor import
    would silently create a new campaign or ad group)
  - "from" values that no longer match the snapshot
  - responsive search ad text over Google's limits, or duplicate assets
  - duplicate changes in the batch
  - changes over the limits in the account context, unless the entry has
    "over_limit_approved": true

Warnings (shown to the person, who decides):
  - negatives that would block a live positive keyword
  - negatives that would block a search term that converted
  - negatives touching a protected term from the account context
  - ad text likely to be disapproved (repeated punctuation, emoji, all caps,
    phone numbers, exclamation marks in headlines)

Usage:
  python3 validate_changes.py CHANGES.json
      [--context .agents/google-ads-context.md]
      [--snapshot FILE.csv ...]      normalized CSVs with campaign/ad_group columns
      [--positives keywords.csv]     normalized keyword inventory
      [--search-terms search_terms.csv]
      [--max-budget-change 0.20] [--max-target-change 0.15] [--max-changes 50]
      [--conversion-lag 7] [--today YYYY-MM-DD] [--json]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

ACTIONS = {
    "add_negative": ["level", "campaign", "keyword", "match_type"],
    "remove_negative": ["level", "campaign", "keyword", "match_type"],
    "add_keyword": ["campaign", "ad_group", "keyword", "match_type"],
    "set_status": ["entity", "campaign", "to"],
    "set_budget": ["campaign", "to"],
    "set_keyword_bid": ["campaign", "ad_group", "keyword", "match_type", "to"],
    "set_target": ["campaign", "target_type", "to"],
    "add_rsa": ["campaign", "ad_group", "headlines", "descriptions", "final_url"],
    "other": ["description"],
}
MATCH_TYPES = {"exact", "phrase", "broad"}
STATUSES = {"enabled", "paused"}
ENTITIES = {"campaign", "ad_group", "keyword"}
DELETE_WORDS = {"delete", "remove", "removed", "remove_campaign", "remove_ad_group", "remove_keyword"}

# Days to wait before judging a change. See the change log skill's review windows.
REVIEW_DAYS = {
    "set_target": 14, "set_keyword_bid": 14, "set_budget": 7, "add_negative": 14,
    "remove_negative": 14, "add_keyword": 14, "add_rsa": 14, "set_status": 7, "other": 14,
}
BIDDING_ACTIONS = {"set_target", "set_keyword_bid"}

HEADLINE_MAX, DESCRIPTION_MAX, PATH_MAX = 30, 90, 15
KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 80, 10
KEYWORD_SYMBOLS = set("!@%^*=;~`<>?\\|{},")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
REPEAT_PUNCT_RE = re.compile(r"([!?.,])\1")
ACRONYM_OK = {"USA", "UK", "EU", "FAQ", "HVAC", "SEO", "CRM", "API", "AI", "PPC", "ROI", "B2B", "SaaS", "CPA", "LLC", "NYC", "IRS", "DIY", "24/7"}


def width(text: str) -> int:
    """Characters as Google counts them: wide and full-width characters count double."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


# Keyword insertion and other customizers count as their default text: {KeyWord:Water Heaters} counts as 13.
INSERTION_RE = re.compile(r"\{[^{}:]+:([^{}]*)\}")


def ad_width(text: str) -> int:
    return width(INSERTION_RE.sub(lambda m: m.group(1), text))


def tokens(text: str) -> list[str]:
    t = text.strip().lower()
    if t.startswith("-"):
        t = t[1:]
    t = t.strip('[]"')
    return [w for w in re.split(r"\s+", t) if w]


def negative_blocks(neg: list[str], match: str, query: list[str]) -> bool:
    """Whether a negative keyword blocks a query or keyword text. Negatives don't match close variants."""
    if not neg or not query:
        return False
    if match == "exact":
        return neg == query
    if match == "phrase":
        n = len(neg)
        return any(query[i:i + n] == neg for i in range(len(query) - n + 1))
    return set(neg) <= set(query)


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def num(value):
    try:
        return float(str(value).replace(",", "").replace("$", "")) if value not in (None, "") else None
    except ValueError:
        return None


def parse_context(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    ctx: dict = {"protected": [], "limits": {}}
    section = re.search(r"(?ms)^##\s+Protected terms\s*$(.*?)(?=^##\s|\Z)", text)
    if section:
        for line in section.group(1).splitlines():
            m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if m and not m.group(1).startswith("["):
                ctx["protected"].append(m.group(1).strip())
    patterns = {
        "max_budget_change": r"max(?:imum)? budget change[^:\n]*:\s*([\d.]+)\s*%",
        "max_target_change": r"max(?:imum)? target change[^:\n]*:\s*([\d.]+)\s*%",
        "max_changes": r"max(?:imum)? changes per batch[^:\n]*:\s*(\d+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = float(m.group(1))
            ctx["limits"][key] = value / 100 if key != "max_changes" else int(value)
    return ctx


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, change_id: str, message: str):
        self.items.append({"level": level, "change": change_id, "message": message})

    def errors(self):
        return [i for i in self.items if i["level"] == "error"]

    def warnings(self):
        return [i for i in self.items if i["level"] == "warning"]


def lint_ad_text(report: Report, cid: str, label: str, text: str, headline: bool):
    if REPEAT_PUNCT_RE.search(text):
        report.add("warning", cid, f"{label} repeats punctuation ('{text}'), which Google's editorial policy disallows")
    if EMOJI_RE.search(text):
        report.add("warning", cid, f"{label} contains an emoji or symbol character ('{text}')")
    if headline and "!" in text:
        report.add("warning", cid, f"{label} has an exclamation mark ('{text}'); headlines with one are often disapproved")
    caps = [w for w in re.findall(r"[A-Za-z]{3,}", text) if w.isupper() and w not in ACRONYM_OK]
    if caps:
        report.add("warning", cid, f"{label} has all-caps words {caps} ('{text}'); gimmicky capitalization gets disapproved")
    if PHONE_RE.search(text):
        report.add("warning", cid, f"{label} looks like it contains a phone number ('{text}'); use a call asset instead")


def check_rsa(report: Report, cid: str, change: dict):
    headlines = [h.strip() for h in change.get("headlines", []) if str(h).strip()]
    descriptions = [d.strip() for d in change.get("descriptions", []) if str(d).strip()]
    if not 3 <= len(headlines) <= 15:
        report.add("error", cid, f"needs 3 to 15 headlines, has {len(headlines)}")
    if not 2 <= len(descriptions) <= 4:
        report.add("error", cid, f"needs 2 to 4 descriptions, has {len(descriptions)}")
    for i, h in enumerate(headlines, 1):
        if ad_width(h) > HEADLINE_MAX:
            report.add("error", cid, f"headline {i} is {ad_width(h)} characters, over {HEADLINE_MAX}: '{h}'")
        lint_ad_text(report, cid, f"headline {i}", h, True)
    for i, d in enumerate(descriptions, 1):
        if ad_width(d) > DESCRIPTION_MAX:
            report.add("error", cid, f"description {i} is {ad_width(d)} characters, over {DESCRIPTION_MAX}: '{d}'")
        lint_ad_text(report, cid, f"description {i}", d, False)
    for label, items in (("headline", headlines), ("description", descriptions)):
        seen = {}
        for text in items:
            key = text.lower()
            if key in seen:
                report.add("error", cid, f"duplicate {label}: '{text}'")
            seen[key] = True
    for key in ("path1", "path2"):
        value = str(change.get(key, "") or "")
        if ad_width(value) > PATH_MAX:
            report.add("error", cid, f"{key} is {ad_width(value)} characters, over {PATH_MAX}: '{value}'")
    if change.get("pins") or change.get("pinned"):
        report.add("warning", cid, "pinned assets reduce the combinations Google can test; pin only what must always show")
    url = str(change.get("final_url", ""))
    if url and not url.startswith(("http://", "https://")):
        report.add("error", cid, f"final_url must be a full URL starting with https://: '{url}'")


def check_keyword_text(report: Report, cid: str, text: str):
    clean = text.strip().strip('[]"')
    if len(clean) > KEYWORD_MAX_CHARS:
        report.add("error", cid, f"keyword is {len(clean)} characters, over {KEYWORD_MAX_CHARS}: '{clean}'")
    if len(clean.split()) > KEYWORD_MAX_WORDS:
        report.add("error", cid, f"keyword has more than {KEYWORD_MAX_WORDS} words: '{clean}'")
    bad = sorted(set(clean) & KEYWORD_SYMBOLS)
    if bad:
        report.add("warning", cid, f"keyword contains symbols Google may reject {bad}: '{clean}'")
    if clean.startswith("+") or " +" in clean:
        report.add("error", cid, f"'+' broad match modifier is retired; use phrase or broad: '{clean}'")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("changes")
    parser.add_argument("--context")
    parser.add_argument("--snapshot", nargs="*", default=[])
    parser.add_argument("--positives")
    parser.add_argument("--search-terms")
    parser.add_argument("--max-budget-change", type=float)
    parser.add_argument("--max-target-change", type=float)
    parser.add_argument("--max-changes", type=int)
    parser.add_argument("--conversion-lag", type=int, default=0)
    parser.add_argument("--today")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    batch = json.loads(Path(args.changes).read_text(encoding="utf-8"))
    changes = batch.get("changes", [])
    report = Report()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()

    ctx = parse_context(args.context) if args.context and Path(args.context).exists() else {"protected": [], "limits": {}}
    if args.context and not Path(args.context).exists():
        report.add("warning", "-", f"context file not found: {args.context}; using default limits")
    limits = {"max_budget_change": 0.20, "max_target_change": 0.15, "max_changes": 50}
    limits.update(ctx["limits"])
    for key in limits:
        if getattr(args, key) is not None:
            limits[key] = getattr(args, key)

    # Snapshot of what exists now.
    snap_rows: list[dict] = []
    for path in args.snapshot:
        snap_rows.extend(read_csv(path))
    campaigns = {r.get("campaign", "").strip().lower() for r in snap_rows if r.get("campaign")}
    ad_groups = {(r.get("campaign", "").strip().lower(), r.get("ad_group", "").strip().lower())
                 for r in snap_rows if r.get("campaign") and r.get("ad_group")}
    positives = []
    if args.positives:
        for r in read_csv(args.positives):
            status = (r.get("keyword_status") or r.get("status") or "").lower()
            if r.get("keyword") and r.get("is_negative", "").lower() != "true" and status not in ("removed",):
                positives.append(r)
    terms = read_csv(args.search_terms) if args.search_terms else []

    if len(changes) > limits["max_changes"]:
        report.add("error", "-", f"batch has {len(changes)} changes, over the limit of {limits['max_changes']}; split it")

    seen_keys: dict = {}
    for index, change in enumerate(changes, 1):
        cid = str(change.get("id") or f"#{index}")
        action = str(change.get("action", "")).strip()
        if action in DELETE_WORDS or action.startswith("delete"):
            report.add("error", cid, f"'{action}' deletes; pause instead (set_status to paused)")
            continue
        if action not in ACTIONS:
            report.add("error", cid, f"unknown action '{action}'")
            continue
        missing = [f for f in ACTIONS[action] if change.get(f) in (None, "", [])]
        if missing:
            report.add("error", cid, f"missing {', '.join(missing)}")
            continue
        for field in ("reason",):
            if not str(change.get(field, "")).strip():
                report.add("warning", cid, "no reason given; the change log needs one")

        camp = str(change.get("campaign", "")).strip().lower()
        group = str(change.get("ad_group", "")).strip().lower()
        match = str(change.get("match_type", "")).strip().lower()
        keyword = str(change.get("keyword", "")).strip()

        if "match_type" in ACTIONS[action] and match not in MATCH_TYPES:
            report.add("error", cid, f"match_type must be exact, phrase, or broad, not '{match}'")
        if action in ("add_negative", "remove_negative"):
            level = str(change.get("level")).lower()
            if level not in ("campaign", "ad_group"):
                report.add("error", cid, "level must be campaign or ad_group")
            if level == "ad_group" and not group:
                report.add("error", cid, "ad_group level negative needs ad_group")
        if action == "set_status":
            entity = str(change.get("entity")).lower()
            to = str(change.get("to")).lower()
            if entity not in ENTITIES:
                report.add("error", cid, "entity must be campaign, ad_group, or keyword")
            if to in DELETE_WORDS:
                report.add("error", cid, "status 'removed' deletes; use paused")
            elif to not in STATUSES:
                report.add("error", cid, f"status must be enabled or paused, not '{to}'")
            if entity in ("ad_group", "keyword") and not group:
                report.add("error", cid, f"{entity} status change needs ad_group")
            if entity == "keyword" and (not keyword or match not in MATCH_TYPES):
                report.add("error", cid, "keyword status change needs keyword and match_type")
        if action in ("add_keyword", "add_rsa"):
            status = str(change.get("status", "paused")).lower()
            if status not in STATUSES:
                report.add("error", cid, f"status must be enabled or paused, not '{status}'")
            elif status == "enabled":
                report.add("warning", cid, "creates the item enabled; new items default to paused unless the person asked")
        if keyword:
            check_keyword_text(report, cid, keyword)
        if action == "add_rsa":
            check_rsa(report, cid, change)

        # Names must exist in the snapshot.
        if snap_rows and action != "other":
            if camp not in campaigns:
                report.add("error", cid, f"campaign '{change.get('campaign')}' not found in the snapshot; "
                           "check the spelling (an Editor import would create a new campaign)")
            elif group and (camp, group) not in ad_groups and not (action == "add_negative" and change.get("level") == "campaign"):
                report.add("error", cid, f"ad group '{change.get('ad_group')}' not found in campaign '{change.get('campaign')}'; "
                           "check the spelling (an Editor import would create a new ad group)")
        elif not snap_rows and action != "other":
            pass  # reported once below

        # Current values must still match.
        if snap_rows and change.get("from") not in (None, ""):
            current = None
            if action == "set_budget":
                rows = [r for r in snap_rows if r.get("campaign", "").strip().lower() == camp and r.get("budget")]
                current = num(rows[0]["budget"]) if rows else None
                if current is not None and num(change["from"]) is not None and abs(current - num(change["from"])) > 0.005:
                    report.add("error", cid, f"budget is now {current:g}, not {change['from']}; re-check before applying")
            elif action == "set_status":
                entity = str(change.get("entity")).lower()
                col = {"campaign": "campaign_status", "ad_group": "ad_group_status", "keyword": "keyword_status"}[entity] if entity in ENTITIES else ""
                for r in snap_rows:
                    if r.get("campaign", "").strip().lower() != camp:
                        continue
                    if entity != "campaign" and r.get("ad_group", "").strip().lower() != group:
                        continue
                    if entity == "keyword" and (r.get("keyword", "").lower() != keyword.lower() or r.get("match_type") != match):
                        continue
                    current = (r.get(col) or (r.get("status") if entity == "keyword" else "") or "").lower()
                    if current:
                        break
                if current and current != str(change["from"]).lower():
                    report.add("error", cid, f"{entity} status is now '{current}', not '{change['from']}'")

        # Limits.
        if action in ("set_budget", "set_target") and num(change.get("from")) and num(change.get("to")) is not None:
            delta = abs(num(change["to"]) - num(change["from"])) / num(change["from"])
            key = "max_budget_change" if action == "set_budget" else "max_target_change"
            if delta > limits[key] + 1e-9 and not change.get("over_limit_approved"):
                report.add("error", cid, f"changes by {delta:.0%}, over the {limits[key]:.0%} limit; split it or get approval "
                           "for this line and set over_limit_approved")
        if action in ("set_budget", "set_target") and change.get("from") in (None, ""):
            report.add("warning", cid, "no 'from' value; can't check the limit or the current value")

        # Duplicates.
        key = (action, camp, group, keyword.lower(), match, str(change.get("level", "")).lower(), str(change.get("entity", "")).lower())
        if action not in ("add_rsa", "other") and key in seen_keys:
            report.add("error", cid, f"duplicates change {seen_keys[key]}")
        seen_keys.setdefault(key, cid)

        # Negative keyword reviews.
        if action == "add_negative":
            neg = tokens(keyword)
            level = str(change.get("level")).lower()
            for term in ctx["protected"]:
                if negative_blocks(neg, match, tokens(term)) or set(neg) & set(tokens(term)):
                    report.add("warning", cid, f"touches protected term '{term}'")
            in_scope = lambda r: r.get("campaign", "").strip().lower() == camp and (
                level == "campaign" or r.get("ad_group", "").strip().lower() == group)
            blocked_kw = [r["keyword"] for r in positives if in_scope(r) and negative_blocks(neg, match, tokens(r["keyword"]))]
            if blocked_kw:
                report.add("warning", cid, f"would block live keyword(s): {', '.join(sorted(set(blocked_kw))[:10])}")
            hit = [r for r in terms if in_scope(r) and negative_blocks(neg, match, tokens(r.get("search_term", "")))]
            converting = [r for r in hit if (num(r.get("conversions")) or 0) > 0]
            if converting:
                listing = ", ".join(f"'{r['search_term']}' ({num(r['conversions']):g} conv)" for r in converting[:5])
                report.add("warning", cid, f"would block search terms that converted: {listing}")
            if terms:
                clicks = sum(num(r.get("clicks")) or 0 for r in hit)
                cost = sum(num(r.get("cost")) or 0 for r in hit)
                change["_blocked"] = f"{len(hit)} search terms, {clicks:g} clicks, {cost:.2f} cost in the report window"

        days = REVIEW_DAYS.get(action, 14) + (args.conversion_lag if action in BIDDING_ACTIONS else 0)
        change["_review_on"] = (today + dt.timedelta(days=days)).isoformat()

    if not snap_rows:
        report.add("warning", "-", "no snapshot given; names and current values were not checked against the account")

    if args.json:
        print(json.dumps({"errors": report.errors(), "warnings": report.warnings(),
                          "review_on": {str(c.get("id") or i): c.get("_review_on") for i, c in enumerate(changes, 1)},
                          "blocked": {str(c.get("id") or i): c.get("_blocked") for i, c in enumerate(changes, 1) if c.get("_blocked")}},
                         indent=2))
    else:
        print(f"Change set: {batch.get('name', args.changes)} ({len(changes)} changes)")
        print(f"Limits: budget {limits['max_budget_change']:.0%}, target {limits['max_target_change']:.0%}, "
              f"{limits['max_changes']} changes per batch")
        print(f"\nErrors: {len(report.errors())}")
        for item in report.errors():
            print(f"  [{item['change']}] {item['message']}")
        print(f"\nWarnings: {len(report.warnings())}")
        for item in report.warnings():
            print(f"  [{item['change']}] {item['message']}")
        print("\nPer change:")
        for i, c in enumerate(changes, 1):
            extra = f"; would have blocked {c['_blocked']}" if c.get("_blocked") else ""
            if c.get("_review_on"):
                print(f"  [{c.get('id') or '#' + str(i)}] {c.get('action')}: review on {c['_review_on']}{extra}")
    return 1 if report.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
