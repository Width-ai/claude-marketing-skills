#!/usr/bin/env python3
"""Write the readable build plan for a new Google Ads Search campaign.

Turns a build spec (see references/build-spec.md) into one Markdown document
the person reviews and approves: what gets created, every setting with the
reason for it, budget math, ad groups and keywords with reported search
volumes (or MISSING), negatives, every ad line with its character count and
source, sitelinks, callouts, the claims and where each comes from, the
validator's errors and warnings, and the steps to do by hand in Google Ads
Editor. Every count and number in the plan comes from this script.

Usage:
  python3 render_plan.py BUILD.json [--out plan.md]
      [--context .agents/google-ads-context.md] [--existing FILE ...]
      [--keyword-data keyword_list.csv] [--today YYYY-MM-DD]

Standard library only. Uses validate_build.py from the same folder.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_build as vb  # noqa: E402

DEFAULT_REASONS = {
    "networks": "Search partners and the Display Network are off by default. Search partner traffic can't be "
                "controlled site by site, and Display spends Search budget on display placements. Test either one "
                "on its own once Search works.",
    "location_option": "Presence shows ads to people in or regularly in the locations. Presence or interest, "
                       "Google's default, also reaches people elsewhere who show interest in the area.",
    "languages": "Google removed campaign language targeting from Search in late September 2026; ads now "
                 "match on the language of the ads and landing pages.",
    "ai_max_off": "Off at launch. New Search campaigns start with AI Max on; this build turns it off so the campaign "
                  "runs on the chosen keywords and landing pages until it has steady conversions.",
    "eu": "Google requires every new campaign to declare whether it has EU political ads.",
    "status": "Everything is created paused. Nothing runs until you enable it after review.",
}


def esc(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def money(value, currency: str) -> str:
    if value is None:
        return "MISSING"
    return f"{value:,.2f} {currency}".strip()


def schedule_text(blocks: list[dict]) -> str:
    if not blocks:
        return "All hours, every day"
    parts = []
    for b in blocks:
        days = b.get("days") or []
        if len(days) > 2 and days == vb.DAYS[vb.DAYS.index(days[0]):vb.DAYS.index(days[0]) + len(days)]:
            label = f"{days[0]} to {days[-1]}"
        else:
            label = ", ".join(days)
        parts.append(f"{label} {b.get('start', '')} to {b.get('end', '')}")
    return "; ".join(parts)


def location_text(loc: dict) -> str:
    if loc.get("radius") not in (None, ""):
        where = loc.get("label") or (f"{loc.get('lat')}, {loc.get('lng')}" if loc.get("lat") is not None else "an address")
        return f"{loc.get('radius')} {loc.get('unit', 'mi')} around {where}"
    return str(loc.get("name", ""))


def source_label(item, sources: dict) -> str:
    sid = vb.source_of(item)
    if not sid:
        return "no claim"
    src = sources.get(sid, {})
    flag = "" if src.get("type") != "page" or src.get("confirmed") is True else ", CONFIRM"
    return f"{sid}{flag}"


def render(spec: dict, report: vb.Report, ctx: dict, today: dt.date) -> str:
    camp = vb.campaign_of(spec)
    cur = spec.get("currency", "")
    sources = spec.get("sources") or {}
    c = vb.counts(spec)
    math = vb.budget_math(spec, ctx)
    approved = spec.get("approved_by")
    lines: list[str] = []
    add = lines.append

    add(f"# Build plan: {camp.get('name', '')}")
    add("")
    add(f"- **Account:** {spec.get('account_name', 'MISSING')} ({spec.get('account_id', 'MISSING')})")
    add(f"- **Currency and time zone:** {cur or 'MISSING'}, {spec.get('time_zone') or 'MISSING'}")
    add(f"- **Prepared:** {spec.get('created', today.isoformat())}")
    add(f"- **Status:** {'Approved by ' + approved + ' ' + str(spec.get('approved_at', '')) if approved else 'Draft, not approved'}")
    add("")
    add("## What this creates")
    add("")
    add(f"This creates **1 new Search campaign**, '{esc(camp.get('name', ''))}', with **{c['ad_groups']} ad groups** inside it "
        f"(not {c['ad_groups']} campaigns), {c['keywords']} keywords ({c['keywords_exact']} exact, {c['keywords_phrase']} "
        f"phrase, {c['keywords_broad']} broad), {c['campaign_negatives']} campaign negatives, {c['ad_group_negatives']} ad "
        f"group negatives, {c['responsive_search_ads']} responsive search ads, {c['sitelinks']} sitelinks, and "
        f"{c['callouts']} callouts. Everything is created paused. No existing campaign changes.")
    if spec.get("brief"):
        add("")
        add(f"**The brief as understood:** {spec['brief']}")
    add("")

    # Settings.
    nets = camp.get("networks") or {}
    on = [label for key, label in (("search_partners", "search partners"), ("display", "Display Network")) if nets.get(key)]
    networks = "Google Search only" if not on else "Google Search plus " + " and ".join(on)
    strategy = str(camp.get("bid_strategy", "")).lower()
    goals = camp.get("conversion_goals") or {}
    ai = vb.ai_max_of(camp)
    if ai.get("enabled") is True:
        ai_text = (f"On (text customization {'on' if ai.get('text_customization') else 'off'}, final URL expansion "
                   f"{'on' if ai.get('final_url_expansion') else 'off'})")
    elif ai.get("enabled") is False:
        ai_text = "Off (text customization off, final URL expansion off)"
    else:
        ai_text = "MISSING"
    option = "Presence or interest" if str(camp.get("location_option", "presence")).lower() == "presence_or_interest" else "Presence"
    eu = str(camp.get("eu_political_ads", "")).lower()
    target = ""
    if strategy == "target_cpa":
        target = money(vb.num(camp.get("target_cpa")), cur)
    elif strategy == "target_roas" and vb.num(camp.get("target_roas")):
        target = f"{vb.num(camp.get('target_roas')) * 100:g}%"
    elif strategy == "maximize_clicks" and vb.num(camp.get("max_cpc_limit")):
        target = "Max CPC limit " + money(vb.num(camp.get("max_cpc_limit")), cur)
    rows = [
        ("Campaign type", "Search", "This skill builds Search campaigns."),
        ("Status", "Paused, with every ad group, keyword, and ad", DEFAULT_REASONS["status"]),
        ("Networks", networks, nets.get("reason") or DEFAULT_REASONS["networks"]),
        ("Locations", "; ".join(location_text(l) for l in camp.get("locations") or []) or "MISSING", camp.get("locations_reason", "")),
        ("Location option", option, camp.get("location_option_reason") or DEFAULT_REASONS["location_option"]),
        ("Excluded locations", "; ".join(l.get("name", "") for l in camp.get("excluded_locations") or []) or "None",
         "Set by hand in Editor (see the steps below)." if camp.get("excluded_locations") else ""),
        ("Languages", "Not set", DEFAULT_REASONS["languages"]),
        ("Ad schedule", schedule_text(camp.get("ad_schedule") or []) + (f" ({spec.get('time_zone')})" if spec.get("time_zone") else ""),
         camp.get("schedule_reason", "")),
        ("Daily budget", money(vb.num(camp.get("daily_budget")), cur), camp.get("budget_source", "")),
        ("Bid strategy", vb.BID_STRATEGIES.get(strategy, strategy or "MISSING") + (f", {target}" if target else ""),
         camp.get("bid_strategy_reason", "") + (f" Target from: {camp.get('target_source')}" if camp.get("target_source") else "")),
        ("Conversion goals", ", ".join(goals.get("primary") or []) or "MISSING",
         ("Tracking checked and working. " if goals.get("tracking_ready") is True else "Tracking NOT confirmed. ")
         + f"Primary conversions in the last 30 days: {goals.get('conversions_30d', 'MISSING')}."),
        ("AI Max", ai_text, ai.get("reason") or (DEFAULT_REASONS["ai_max_off"] if ai.get("enabled") is False else "")),
        ("EU political ads", {"no": "Doesn't have EU political ads", "yes": "Has EU political ads"}.get(eu, "MISSING"),
         DEFAULT_REASONS["eu"]),
        ("Start and end", (camp.get("start_date") or "Starts when you enable it") + (f", ends {camp['end_date']}" if camp.get("end_date") else ", no end date"), ""),
    ]
    add("## Campaign settings")
    add("")
    add("| Setting | Value | Why |")
    add("|---|---|---|")
    for setting, value, why in rows:
        add(f"| {setting} | {esc(value)} | {esc(why)} |")
    add("")

    add("## Budget math")
    add("")
    add("Calculated by `render_plan.py`. Estimates are labeled.")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Daily budget | {money(math['daily_budget'], cur)} |")
    add(f"| Most it can spend in a month (30.4 times daily) | {money(math['monthly_cap'], cur)} |")
    add(f"| Most it can spend in one day (2 times daily) | {money(math['max_single_day'], cur)} |")
    if math.get("conversions_per_day_at_target") is not None:
        add(f"| Conversions a day the budget buys at a {money(math['target_cpa_used'], cur)} CPA (estimate) | "
            f"{math['conversions_per_day_at_target']:g} |")
    else:
        add("| Conversions a day at target CPA | MISSING (no target CPA) |")
    if math.get("clicks_per_day") is not None:
        add(f"| Clicks a day at {money(math['expected_cpc'], cur)} per click (estimate, {esc(camp.get('expected_cpc_source', 'source not given'))}) | "
            f"{math['clicks_per_day']:g} |")
    else:
        add("| Clicks a day | MISSING (no expected CPC from account history or a keyword tool) |")
    add("")

    add("## Ad groups and keywords")
    add("")
    for gi, group in enumerate(spec.get("ad_groups") or [], 1):
        add(f"### {gi}. {group.get('name', '')}")
        add("")
        if group.get("theme"):
            add(f"- **Theme:** {group['theme']}")
        add(f"- **Landing page:** {group.get('final_url', 'MISSING')}")
        if vb.num(group.get("max_cpc")) is not None:
            add(f"- **Default max CPC:** {money(vb.num(group.get('max_cpc')), cur)}")
        add("")
        add("| Keyword | Match type | Found through | Avg. monthly searches (as reported) |")
        add("|---|---|---|---|")
        for kw in group.get("keywords") or []:
            vol = kw.get("avg_monthly_searches")
            vol = f"{vol} ({kw.get('volume_source', '')})" if vol not in (None, "", "MISSING") else "MISSING"
            add(f"| {esc(kw.get('text'))} | {esc(kw.get('match_type'))} | {esc(kw.get('source', ''))} | {esc(vol)} |")
        negs = group.get("negatives") or []
        if negs:
            add("")
            add("Ad group negatives: " + "; ".join(f"{n.get('keyword')} ({n.get('match_type')}, {n.get('source', '')})" for n in negs))
        add("")

    add("## Campaign negative keywords")
    add("")
    negs = spec.get("negatives") or []
    if negs:
        add("| Negative | Match type | Source | Note |")
        add("|---|---|---|---|")
        for n in negs:
            add(f"| {esc(n.get('keyword'))} | {esc(n.get('match_type'))} | {esc(n.get('source', ''))} | {esc(n.get('reason', ''))} |")
    else:
        add("None.")
    add("")

    add("## Responsive search ads")
    add("")
    for group in spec.get("ad_groups") or []:
        for ai_, ad in enumerate(vb.ads_of(group), 1):
            url = ad.get("final_url") or group.get("final_url", "")
            path = "/".join(p for p in (ad.get("path1"), ad.get("path2")) if p)
            add(f"### {group.get('name', '')}, ad {ai_}")
            add("")
            add(f"Final URL: {url}" + (f" (display path /{path})" if path else ""))
            add("")
            add("| # | Headline | Characters | Source |")
            add("|---|---|---|---|")
            for i, h in enumerate([h for h in ad.get("headlines") or [] if vb.text_of(h)], 1):
                t = vb.text_of(h)
                add(f"| {i} | {esc(t)} | {vb.width(t)}/{vb.HEADLINE_MAX} | {source_label(h, sources)} |")
            add("")
            add("| # | Description | Characters | Source |")
            add("|---|---|---|---|")
            for i, d in enumerate([d for d in ad.get("descriptions") or [] if vb.text_of(d)], 1):
                t = vb.text_of(d)
                add(f"| {i} | {esc(t)} | {vb.width(t)}/{vb.DESCRIPTION_MAX} | {source_label(d, sources)} |")
            add("")

    add("## Sitelinks")
    add("")
    add("| Text | Description 1 | Description 2 | URL | Source |")
    add("|---|---|---|---|---|")
    for s in spec.get("sitelinks") or []:
        t, d1, d2 = vb.text_of(s), s.get("description1", ""), s.get("description2", "")
        add(f"| {esc(t)} ({vb.width(t)}/{vb.SITELINK_TEXT_MAX}) | {esc(d1)} ({vb.width(d1)}/{vb.SITELINK_DESC_MAX}) | "
            f"{esc(d2)} ({vb.width(d2)}/{vb.SITELINK_DESC_MAX}) | {esc(s.get('final_url', ''))} | {source_label(s, sources)} |")
    add("")
    add("## Callouts")
    add("")
    add("| Callout | Characters | Source |")
    add("|---|---|---|")
    for s in spec.get("callouts") or []:
        t = vb.text_of(s)
        add(f"| {esc(t)} | {vb.width(t)}/{vb.CALLOUT_MAX} | {source_label(s, sources)} |")
    add("")

    add("## Claims and their sources")
    add("")
    add("Every line above that makes a claim cites one of these. Lines marked \"no claim\" make none.")
    add("")
    used: dict[str, int] = {}
    for group in spec.get("ad_groups") or []:
        for ad in vb.ads_of(group):
            for item in (ad.get("headlines") or []) + (ad.get("descriptions") or []):
                if vb.source_of(item):
                    used[vb.source_of(item)] = used.get(vb.source_of(item), 0) + 1
    for item in (spec.get("sitelinks") or []) + (spec.get("callouts") or []):
        if vb.source_of(item):
            used[vb.source_of(item)] = used.get(vb.source_of(item), 0) + 1
    add("| ID | Approved wording | From | Confirmed | Lines using it |")
    add("|---|---|---|---|---|")
    for sid, src in sources.items():
        confirmed = "yes" if src.get("type") != "page" or src.get("confirmed") is True else "NO, confirm before approval"
        expires = f" (expires {src['expires']})" if src.get("expires") else ""
        add(f"| {sid} | {esc(src.get('text', ''))}{expires} | {esc(src.get('type', ''))}: {esc(src.get('where', ''))} | "
            f"{confirmed} | {used.get(sid, 0)} |")
    add("")

    add("## Checks")
    add("")
    add(f"`validate_build.py` found **{len(report.errors())} errors** and **{len(report.warnings())} warnings**.")
    add("")
    for item in report.errors():
        add(f"- ERROR [{esc(item['where'])}] {esc(item['message'])}")
    for item in report.warnings():
        add(f"- Warning [{esc(item['where'])}] {esc(item['message'])}")
    add("")

    add("## Set by hand in Google Ads Editor before posting")
    add("")
    for i, step in enumerate(vb.by_hand_steps(spec), 1):
        add(f"{i}. {step}")
    add("")
    add("## After approval")
    add("")
    add("1. Claude builds the Google Ads Editor import files and gives you the import steps.")
    add("2. You import them, do the steps above, review, and post. The campaign arrives in Google Ads paused.")
    add("3. Launching is a separate yes: enable the ads, keywords, and ad groups, then the campaign last.")
    add("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build")
    parser.add_argument("--out")
    parser.add_argument("--context")
    parser.add_argument("--existing", nargs="*", default=None)
    parser.add_argument("--keyword-data")
    parser.add_argument("--today")
    args = parser.parse_args()

    spec = vb.load_spec(args.build)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = vb.parse_context(args.context) if args.context and Path(args.context).exists() else {}
    existing = vb.load_existing(args.existing) if args.existing else None
    keyword_data = vb.load_keyword_data(args.keyword_data) if args.keyword_data else None
    report = vb.check_build(spec, ctx or None, existing, keyword_data, today)
    text = render(spec, report, ctx, today)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(report.errors())} errors, {len(report.warnings())} warnings)")
    else:
        print(text)
    return 1 if report.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
