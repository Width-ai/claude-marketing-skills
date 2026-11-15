#!/usr/bin/env python3
"""Build Google Ads Editor import files that create a new, paused Search campaign.

Reads an approved build spec (see references/build-spec.md) and writes one file
per item type into the output folder, so each file only carries the columns
that item type needs:

  campaign.csv    the campaign row: type, networks, budget, bid strategy,
                  schedule, dates, status (Paused)
  locations.csv   targeted locations, one per row
  ad_groups.csv   ad groups (Paused)
  keywords.csv    keywords with match types (Paused)
  negatives.csv   campaign and ad group negative keywords
  ads.csv         responsive search ads (Paused)
  sitelinks.csv   campaign sitelinks
  callouts.csv    campaign callouts
  rollback/pause_campaign.csv   pauses the campaign again after a launch
  manifest.md     import order, what to expect after each import, settings to
                  set by hand before posting, and the launch steps

Settings whose Editor column or value spelling Google doesn't document
(location option, budget type, EU political ads declaration, AI Max) are
written only when --template points to an export from the person's own Editor
that shows the column and a matching value. Otherwise they go in the manifest
as steps to do by hand before posting.

Files are UTF-16 with tabs, the format Google Ads Editor uses for its own
exports. Use --utf8 for comma-separated UTF-8 instead. Use --template with a
CSV exported from the person's Editor to copy its exact header spellings.

Refuses to build when the spec fails validation, has no approved_by, or uses a
claim from a web page the person hasn't confirmed, unless --include-unapproved
is given for a draft.

Usage:
  python3 build_editor_files.py BUILD.json --out FOLDER [--utf8]
      [--template EDITOR_EXPORT.csv] [--include-unapproved]
      [--context .agents/google-ads-context.md] [--existing FILE ...]
      [--changeset google-ads-changes/DATE-NAME.json] [--today YYYY-MM-DD]

Standard library only. Uses validate_build.py from the same folder.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_build as vb  # noqa: E402

CRITERION = {"exact": "Exact", "phrase": "Phrase", "broad": "Broad"}
ORDER = ["campaign", "locations", "ad_groups", "keywords", "negatives", "ads", "sitelinks", "callouts"]
EXPECT = {
    "campaign": "1 new campaign and no changed campaigns. If Editor says an existing campaign changed, the name matched "
                "one already in the account: revert the import and rename.",
    "locations": "new location targets on the new campaign only",
    "ad_groups": "{n} new ad groups and no new campaigns",
    "keywords": "{n} new keywords and no new ad groups or campaigns",
    "negatives": "{n} new negative keywords and no new ad groups or campaigns",
    "ads": "{n} new responsive search ads and no new ad groups",
    "sitelinks": "{n} new sitelinks on the new campaign",
    "callouts": "{n} new callouts on the new campaign",
}

# Columns Google doesn't document for import. Written only when the person's Editor export shows the column and a
# value that matches the meaning. Each rule: (header in the export, setting, test for the value we want).
TEMPLATE_ONLY = {
    "targeting method": ("location_option",
                         lambda v, want: ("presence" in v and "interest" not in v) if want == "presence"
                         else ("presence" in v and "interest" in v)),
    "budget type": ("budget_type", lambda v, want: "daily" in v),
    "eu political ads": ("eu_political_ads", lambda v, want: ("doesn" in v or "does not" in v or v == "no") if want == "no" else False),
    "ai max": ("ai_max", lambda v, want: v in ({"disabled", "off", "false", "no"} if want == "off" else {"enabled", "on", "true", "yes"})),
    "text customization": ("ai_max", lambda v, want: v in ({"disabled", "off", "false", "no"} if want == "off" else {"enabled", "on", "true", "yes"})),
    "final url expansion": ("ai_max", lambda v, want: v in ({"disabled", "off", "false", "no"} if want == "off" else {"enabled", "on", "true", "yes"})),
}


def money(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def load_template(path: str) -> tuple[dict, dict]:
    """Return ({lowercase header: export spelling}, {lowercase header: set of values seen})."""
    text = vb.decode(Path(path).read_bytes())
    lines = text.splitlines()
    if not lines:
        return {}, {}
    delimiter = "\t" if lines[0].count("\t") >= lines[0].count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, [])
    spelling = {h.strip().lower(): h.strip() for h in header if h.strip()}
    values: dict[str, set] = {h.strip().lower(): set() for h in header if h.strip()}
    for n, row in enumerate(reader):
        if n > 50000:
            break
        for h, v in zip(header, row):
            v = v.strip()
            if v and len(values.get(h.strip().lower(), ())) < 200:
                values.setdefault(h.strip().lower(), set()).add(v)
    return spelling, values


def observed(values: dict, column: str, test) -> str:
    for v in sorted(values.get(column, set())):
        if test(v.strip().lower()):
            return v
    return ""


def write(path: Path, header: list[str], rows: list[list[str]], utf8: bool, spelling: dict) -> None:
    header = [spelling.get(h.lower(), h) for h in header]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="," if utf8 else "\t", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = buffer.getvalue()
    path.write_bytes(data.encode("utf-8-sig") if utf8 else data.encode("utf-16"))


def schedule_cell(blocks: list[dict]) -> str:
    """Google Ads Editor format: (Monday[08:00-17:30]);(Tuesday[08:00-17:30])"""
    parts = []
    for b in blocks or []:
        for day in b.get("days") or []:
            parts.append(f"({day}[{b.get('start')}-{b.get('end')}])")
    return ";".join(parts)


def location_cell(loc: dict) -> str:
    if loc.get("radius") not in (None, ""):
        lat, lng = vb.num(loc.get("lat")), vb.num(loc.get("lng"))
        if lat is None or lng is None:
            return ""
        radius = vb.num(loc.get("radius"))
        return f"({radius:g}{str(loc.get('unit', 'mi')).lower()}:{lat:.6f}:{lng:.6f})"
    return str(loc.get("name", "")).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build")
    parser.add_argument("--out", required=True)
    parser.add_argument("--utf8", action="store_true")
    parser.add_argument("--template")
    parser.add_argument("--include-unapproved", action="store_true",
                        help="build a draft even though the build has no approved_by or uses unconfirmed claims")
    parser.add_argument("--context")
    parser.add_argument("--existing", nargs="*", default=None)
    parser.add_argument("--changeset", help="also write a one-entry change set for the change log")
    parser.add_argument("--today")
    args = parser.parse_args()

    spec = vb.load_spec(args.build)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = vb.parse_context(args.context) if args.context and Path(args.context).exists() else None
    existing = vb.load_existing(args.existing) if args.existing else None
    report = vb.check_build(spec, ctx, existing, None, today)
    if report.errors():
        for item in report.errors():
            print(f"  [{item['where']}] {item['message']}", file=sys.stderr)
        sys.exit(f"the build has {len(report.errors())} validation error(s); fix them and run validate_build.py again")
    draft = not spec.get("approved_by")
    unconfirmed = vb.unconfirmed_sources(spec)
    if not args.include_unapproved:
        if draft:
            sys.exit("the build has no approved_by; show the plan and get approval first, or pass --include-unapproved for a draft")
        if unconfirmed:
            sys.exit(f"the ads use claims from a web page the person hasn't confirmed ({', '.join(unconfirmed)}); confirm "
                     "them and set confirmed to true, or pass --include-unapproved for a draft")

    spelling, values = load_template(args.template) if args.template else ({}, {})
    camp = vb.campaign_of(spec)
    name = str(camp.get("name", "")).strip()
    strategy = str(camp.get("bid_strategy", "")).lower()
    ai = vb.ai_max_of(camp)
    written: set[str] = set()
    from_export: list[str] = []
    out = Path(args.out)

    # Campaign row.
    header = ["Campaign", "Campaign Type", "Networks", "Budget", "Bid Strategy Type"]
    nets = camp.get("networks") or {}
    tokens = sorted({t.strip() for v in values.get("networks", set()) for t in v.split(";") if t.strip()})
    google_search = next((t for t in tokens if t.lower() == "google search"), "Google Search")
    network_cell = [google_search]
    if nets.get("search_partners"):
        network_cell.append(next((t for t in tokens if t.lower() == "search partners"), "Search Partners"))
    if nets.get("display"):
        network_cell.append(next((t for t in tokens if t.lower() in ("display network", "display")), "Display Network"))
    row = [name, "Search", ";".join(network_cell), money(camp.get("daily_budget")), vb.BID_STRATEGIES[strategy]]
    if strategy == "target_cpa":
        header.append("Target CPA")
        row.append(money(camp.get("target_cpa")))
    if strategy == "target_roas":
        header.append("Target ROAS")
        row.append(f"{vb.num(camp.get('target_roas')) * 100:g}%")
    if strategy == "maximize_clicks" and vb.num(camp.get("max_cpc_limit")) is not None:
        header.append("Maximum CPC bid limit")
        row.append(money(camp.get("max_cpc_limit")))
    if camp.get("ad_schedule"):
        header.append("Ad Schedule")
        row.append(schedule_cell(camp["ad_schedule"]))
    for key, label in (("start_date", "Start Date"), ("end_date", "End Date")):
        if camp.get(key):
            header.append(label)
            row.append(str(camp[key]))
    wants = {
        "targeting method": "presence" if str(camp.get("location_option", "presence")).lower() == "presence" else "presence_or_interest",
        "budget type": "daily",
        "eu political ads": str(camp.get("eu_political_ads", "")).lower(),
        "ai max": "on" if ai.get("enabled") else "off",
        "text customization": "on" if ai.get("text_customization") else "off",
        "final url expansion": "on" if ai.get("final_url_expansion") else "off",
    }
    ai_cols = {}
    for column, (setting, test) in TEMPLATE_ONLY.items():
        if column not in spelling:
            continue
        value = observed(values, column, lambda v, t=test, w=wants[column]: t(v, w))
        if not value:
            continue
        if setting == "ai_max":
            ai_cols[column] = value
            continue
        header.append(spelling[column])
        row.append(value)
        written.add(setting)
        from_export.append(f"{spelling[column]} = {value}")
    if len(ai_cols) == 3 or (ai_cols.get("ai max") and not ai.get("enabled")):
        for column, value in ai_cols.items():
            header.append(spelling[column])
            row.append(value)
            from_export.append(f"{spelling[column]} = {value}")
        written.add("ai_max")
    header.append("Campaign Status")
    row.append("Paused")
    files: dict[str, tuple[list[str], list[list[str]]]] = {"campaign": (header, [row])}

    # Locations.
    loc_rows = []
    use_ids = any(str(l.get("id", "")).strip() for l in camp.get("locations") or [])
    for loc in camp.get("locations") or []:
        cell = location_cell(loc)
        if cell:
            loc_rows.append([name, cell] + ([str(loc.get("id", "")).strip()] if use_ids else []))
    files["locations"] = (["Campaign", "Location"] + (["Location ID"] if use_ids else []), loc_rows)

    # Ad groups, keywords, negatives, ads.
    groups = spec.get("ad_groups") or []
    manual = strategy == "manual_cpc"
    files["ad_groups"] = (["Campaign", "Ad Group"] + (["Max CPC"] if manual else []) + ["Ad Group Status"],
                          [[name, g["name"]] + ([money(g.get("max_cpc"))] if manual else []) + ["Paused"] for g in groups])
    kw_bids = manual and any(vb.num(k.get("max_cpc")) is not None for g in groups for k in g.get("keywords") or [])
    kw_rows = []
    for g in groups:
        for k in g.get("keywords") or []:
            kw_rows.append([name, g["name"], str(k["text"]).strip(), CRITERION[str(k["match_type"]).lower()]]
                           + ([money(k.get("max_cpc"))] if kw_bids else []) + ["Paused"])
    files["keywords"] = (["Campaign", "Ad Group", "Keyword", "Criterion Type"] + (["Max CPC"] if kw_bids else []) + ["Status"], kw_rows)
    neg_rows = [[name, "", str(n["keyword"]).strip(), "Campaign Negative " + CRITERION[str(n["match_type"]).lower()]]
                for n in spec.get("negatives") or []]
    for g in groups:
        for n in g.get("negatives") or []:
            neg_rows.append([name, g["name"], str(n["keyword"]).strip(), "Negative " + CRITERION[str(n["match_type"]).lower()]])
    files["negatives"] = (["Campaign", "Ad Group", "Keyword", "Criterion Type"], neg_rows)
    ads = [(g, a) for g in groups for a in vb.ads_of(g)]
    n_h = max((len([h for h in a.get("headlines") or [] if vb.text_of(h)]) for _, a in ads), default=0)
    n_d = max((len([d for d in a.get("descriptions") or [] if vb.text_of(d)]) for _, a in ads), default=0)
    ad_type = observed(values, "ad type", lambda v: "responsive search" in v) or "Responsive search ad"
    ad_rows = []
    for g, a in ads:
        h = [vb.text_of(x) for x in a.get("headlines") or [] if vb.text_of(x)]
        d = [vb.text_of(x) for x in a.get("descriptions") or [] if vb.text_of(x)]
        ad_rows.append([name, g["name"], ad_type] + h + [""] * (n_h - len(h)) + d + [""] * (n_d - len(d))
                       + [a.get("path1", ""), a.get("path2", ""), a.get("final_url") or g.get("final_url", ""), "Paused"])
    files["ads"] = (["Campaign", "Ad Group", "Ad type"] + [f"Headline {i}" for i in range(1, n_h + 1)]
                    + [f"Description {i}" for i in range(1, n_d + 1)] + ["Path 1", "Path 2", "Final URL", "Status"], ad_rows)
    files["sitelinks"] = (["Campaign", "Link Text", "Description Line 1", "Description Line 2", "Final URL"],
                          [[name, vb.text_of(s), s.get("description1", ""), s.get("description2", ""), s.get("final_url", "")]
                           for s in spec.get("sitelinks") or []])
    files["callouts"] = (["Campaign", "Callout text"], [[name, vb.text_of(c)] for c in spec.get("callouts") or []])

    written_files = []
    for key in ORDER:
        header, rows = files[key]
        if rows:
            write(out / f"{key}.csv", header, rows, args.utf8, spelling)
            written_files.append((key, len(rows)))
    write(out / "rollback" / "pause_campaign.csv", ["Campaign", "Campaign Status"], [[name, "Paused"]], args.utf8, spelling)

    # Manifest.
    c = vb.counts(spec)
    lines = [f"# Google Ads Editor import: {spec.get('name', name)}", ""]
    lines.append(f"- Account: {spec.get('account_name', '')} {spec.get('account_id', '')}".rstrip())
    lines.append(f"- Approved by: {spec.get('approved_by') or 'NOT APPROVED (draft, do not post)'} {spec.get('approved_at', '')}".rstrip())
    lines.append(f"- Encoding: {'UTF-8, comma-separated' if args.utf8 else 'UTF-16, tab-separated'}")
    lines.append(f"- Header spellings: {'copied from ' + Path(args.template).name if args.template else 'standard Google Ads Editor headers'}")
    lines += ["", f"This creates 1 new Search campaign, '{name}', with {c['ad_groups']} ad groups inside it, "
              f"{c['keywords']} keywords, {c['campaign_negatives'] + c['ad_group_negatives']} negatives, "
              f"{c['responsive_search_ads']} responsive search ads, {c['sitelinks']} sitelinks, and {c['callouts']} callouts. "
              "Everything is paused. No existing campaign changes.", ""]
    lines += ["## Before you import", "",
              f"1. Open Google Ads Editor, select account {spec.get('account_id', '')}, and click **Get recent changes**.",
              f"2. Search the campaign list for '{name}'. It must not exist yet. If it does, stop and rename the build.", ""]
    lines += ["## Import these files in this order", "",
              "Use **Account > Import > From file...** for each file. Check the preview before you finish each import.", ""]
    for i, (key, n) in enumerate(written_files, 1):
        lines.append(f"{i}. `{key}.csv` ({n} {'row' if n == 1 else 'rows'}). Expect: {EXPECT[key].format(n=n).rstrip('.')}.")
    lines += ["", "Import the campaign file first and the ad groups before keywords, negatives, and ads. A keyword or ad "
              "file imported before its ad group makes Editor create that ad group with default settings.", ""]
    lines += ["## Set these by hand in Editor before posting", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(vb.by_hand_steps(spec, written), 1)]
    lines += ["", "## Check, then post", "",
              "1. Click **Check changes** and fix anything Editor flags.",
              "2. Look at the Ad strength column for the new ads. Google recommends Good or Excellent.",
              "3. Click **Post**. The campaign arrives in Google Ads paused, with everything inside it paused.",
              "4. Reply in the chat when it's posted, so the build can be checked against the account and logged.", ""]
    used = []
    for key, _n in written_files:
        for h in files[key][0]:
            label = re.sub(r"^Headline \d+$", f"Headline 1 to {n_h}", h)
            label = re.sub(r"^Description \d+$", f"Description 1 to {n_d}", label)
            if h == "Ad type":
                continue
            if label not in used and h.lower() not in {f.split(" = ")[0].lower() for f in from_export}:
                used.append(label)
    lines += ["## What the files set, and how sure we are of each column", "",
              "- Columns in these files, named as in Google's Editor help pages: " + ", ".join(used) + ".",
              "- Values that match Editor's own exports rather than a help page: Ad type (" + ad_type + ") and the "
              "negative criterion types (Negative Phrase, Campaign Negative Phrase, and so on).",
              "- Copied from your Editor export: " + ("; ".join(from_export) if from_export else "none"),
              "- If the import preview shows a column it doesn't recognize, pick the right column from the drop-down, "
              "or export a small sample from your Editor and rebuild with `--template`.", ""]
    lines += ["## Launch (a separate approval)", "",
              "When you're ready to spend, enable the ads, then the keywords, then the ad groups, and the campaign last. "
              "Check the search terms report in the first days.", ""]
    lines += ["## Undo", "",
              "- Before posting: revert the pending changes in Editor.",
              "- After posting: the campaign is paused, so nothing runs. To stop it after a launch, import "
              "`rollback/pause_campaign.csv`. Nothing is deleted.", ""]
    if draft or unconfirmed:
        lines += ["## Draft", "", "These files were built without approval or with unconfirmed claims. Don't post them.", ""]
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.md").write_text("\n".join(lines), encoding="utf-8")

    if args.changeset and not draft:
        change = {
            "name": spec.get("name", name), "account_id": spec.get("account_id", ""),
            "account_name": spec.get("account_name", ""), "created": spec.get("created", today.isoformat()),
            "approved_by": spec.get("approved_by", ""), "approved_at": spec.get("approved_at", ""),
            "changes": [{
                "id": "c1", "action": "other", "campaign": name, "entity_type": "campaign", "entity": name,
                "field": "new campaign (paused)", "from": "", "to": "created, paused",
                "description": (f"Create new Search campaign '{name}' through a Google Ads Editor import: "
                                f"{c['ad_groups']} ad groups, {c['keywords']} keywords, "
                                f"{c['campaign_negatives'] + c['ad_group_negatives']} negatives, "
                                f"{c['responsive_search_ads']} responsive search ads, {c['sitelinks']} sitelinks, "
                                f"{c['callouts']} callouts, all paused. Build file: {Path(args.build).name}"),
                "reason": spec.get("brief") or "reason not recorded",
                "evidence": f"Build plan approved by {spec.get('approved_by')}",
                "expected_effect": camp.get("expected_effect", ""),
            }],
        }
        Path(args.changeset).parent.mkdir(parents=True, exist_ok=True)
        Path(args.changeset).write_text(json.dumps(change, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.changeset}")

    for key, n in written_files:
        print(f"wrote {out / (key + '.csv')} ({n} rows)")
    print(f"wrote {out / 'rollback' / 'pause_campaign.csv'}")
    print(f"wrote {out / 'manifest.md'}")
    if from_export:
        print("from the Editor export: " + "; ".join(from_export))
    print(f"{len(vb.by_hand_steps(spec, written))} step(s) to do by hand in Editor before posting; see manifest.md")
    if report.warnings():
        print(f"{len(report.warnings())} validation warning(s); run validate_build.py to see them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
