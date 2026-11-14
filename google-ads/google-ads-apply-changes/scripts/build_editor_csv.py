#!/usr/bin/env python3
"""Build Google Ads Editor import files from an approved change set.

Writes one CSV per change type into the output folder, so each file only
carries the columns that change type needs:

  negatives.csv         new ad group and campaign negative keywords
  keywords.csv          new keywords (paused unless the change says enabled)
  keyword_bids.csv      keyword max CPC changes
  campaign_status.csv   campaign pauses and enables
  ad_group_status.csv   ad group pauses and enables
  keyword_status.csv    keyword pauses and enables
  budgets.csv           campaign daily budget changes
  ads.csv               new responsive search ads (paused unless the change says enabled)
  rollback/             files that undo the changes above where Editor can express it
  manifest.md           what's in each file, import order, and anything left out

Changes Editor files can't express (target CPA/ROAS, removing negatives,
"other") are listed in the manifest to apply through a connector or by hand.

Files are UTF-16 with tabs, the format Google Ads Editor uses for its own
exports and recommends for text with non-English characters. Use --utf8 for
comma-separated UTF-8 instead. Use --template with a CSV exported from your
Editor to copy its exact header spellings.

Usage:
  python3 build_editor_csv.py CHANGES.json --out FOLDER [--utf8] [--template EDITOR_EXPORT.csv]
      [--include-unapproved]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

CRITERION = {"exact": "Exact", "phrase": "Phrase", "broad": "Broad"}
STATUS = {"enabled": "Enabled", "paused": "Paused"}

FILES = {
    "negatives": ["Campaign", "Ad Group", "Keyword", "Criterion Type"],
    "keywords": ["Campaign", "Ad Group", "Keyword", "Criterion Type", "Max CPC", "Final URL", "Status"],
    "keyword_bids": ["Campaign", "Ad Group", "Keyword", "Criterion Type", "Max CPC"],
    "campaign_status": ["Campaign", "Campaign Status"],
    "ad_group_status": ["Campaign", "Ad Group", "Ad Group Status"],
    "keyword_status": ["Campaign", "Ad Group", "Keyword", "Criterion Type", "Status"],
    "budgets": ["Campaign", "Budget"],
}
ADS_FIXED = ["Campaign", "Ad Group", "Ad type"]
ADS_TAIL = ["Path 1", "Path 2", "Final URL", "Status"]
ORDER = ["budgets", "campaign_status", "ad_group_status", "keywords", "keyword_bids", "keyword_status", "negatives", "ads"]


def money(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def negative_type(level: str, match: str) -> str:
    prefix = "Campaign Negative " if level == "campaign" else "Negative "
    return prefix + CRITERION[match]


def load_template(path: str) -> dict:
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    first = text.splitlines()[0] if text else ""
    delimiter = "\t" if first.count("\t") >= first.count(",") else ","
    header = next(csv.reader(io.StringIO(first), delimiter=delimiter), [])
    return {h.strip().lower(): h.strip() for h in header if h.strip()}


def write(path: Path, header: list[str], rows: list[list[str]], utf8: bool, template: dict) -> None:
    header = [template.get(h.lower(), h) for h in header]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="," if utf8 else "\t", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = buffer.getvalue()
    path.write_bytes(data.encode("utf-8-sig") if utf8 else data.encode("utf-16"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("changes")
    parser.add_argument("--out", required=True)
    parser.add_argument("--utf8", action="store_true")
    parser.add_argument("--template")
    parser.add_argument("--include-unapproved", action="store_true",
                        help="build files even though the batch has no approved_by (for a dry run)")
    args = parser.parse_args()

    batch = json.loads(Path(args.changes).read_text(encoding="utf-8"))
    if not batch.get("approved_by") and not args.include_unapproved:
        sys.exit("the change set has no approved_by; get approval first, or pass --include-unapproved for a draft")
    template = load_template(args.template) if args.template else {}
    if args.template:
        wanted = {h.lower() for cols in FILES.values() for h in cols} | {h.lower() for h in ADS_FIXED + ADS_TAIL}
        missing = sorted(h for h in wanted if h not in template and not h.startswith(("headline", "description")))
        if missing:
            print(f"note: template has no column for: {', '.join(missing)} (using standard spelling)", file=sys.stderr)

    out = Path(args.out)
    rows: dict[str, list[list[str]]] = {k: [] for k in FILES}
    rollback: dict[str, list[list[str]]] = {k: [] for k in FILES}
    ads: list[dict] = []
    manual: list[str] = []
    no_rollback: list[str] = []
    skipped: list[str] = []

    for index, c in enumerate(batch.get("changes", []), 1):
        cid = str(c.get("id") or f"#{index}")
        if c.get("approved") is False:
            skipped.append(f"{cid}: not approved")
            continue
        action = c.get("action")
        camp, group = c.get("campaign", ""), c.get("ad_group", "")
        kw, match = c.get("keyword", ""), str(c.get("match_type", "")).lower()
        if action == "add_negative":
            level = str(c.get("level")).lower()
            rows["negatives"].append([camp, "" if level == "campaign" else group, kw, negative_type(level, match)])
            no_rollback.append(f"{cid}: remove negative '{kw}' ({match}, {level} level) in Editor or the Google Ads UI")
        elif action == "add_keyword":
            status = STATUS[str(c.get("status", "paused")).lower()]
            rows["keywords"].append([camp, group, kw, CRITERION[match], money(c.get("max_cpc")), c.get("final_url", ""), status])
            rollback["keyword_status"].append([camp, group, kw, CRITERION[match], "Paused"])
        elif action == "set_keyword_bid":
            rows["keyword_bids"].append([camp, group, kw, CRITERION[match], money(c.get("to"))])
            if c.get("from") not in (None, ""):
                rollback["keyword_bids"].append([camp, group, kw, CRITERION[match], money(c.get("from"))])
            else:
                no_rollback.append(f"{cid}: no 'from' bid recorded for '{kw}'")
        elif action == "set_status":
            entity = str(c.get("entity")).lower()
            to = STATUS[str(c.get("to")).lower()]
            back = STATUS.get(str(c.get("from", "")).lower())
            if entity == "campaign":
                rows["campaign_status"].append([camp, to])
                if back:
                    rollback["campaign_status"].append([camp, back])
            elif entity == "ad_group":
                rows["ad_group_status"].append([camp, group, to])
                if back:
                    rollback["ad_group_status"].append([camp, group, back])
            else:
                rows["keyword_status"].append([camp, group, kw, CRITERION[match], to])
                if back:
                    rollback["keyword_status"].append([camp, group, kw, CRITERION[match], back])
            if not back:
                no_rollback.append(f"{cid}: no 'from' status recorded")
        elif action == "set_budget":
            rows["budgets"].append([camp, money(c.get("to"))])
            if c.get("from") not in (None, ""):
                rollback["budgets"].append([camp, money(c.get("from"))])
            else:
                no_rollback.append(f"{cid}: no 'from' budget recorded for '{camp}'")
        elif action == "add_rsa":
            ads.append(c)
            no_rollback.append(f"{cid}: pause the new ad in ad group '{group}' in Editor or the Google Ads UI")
        else:
            manual.append(f"{cid}: {action} ({c.get('description') or c.get('target_type') or kw or camp})")

    written = []
    for name in ORDER:
        if name == "ads":
            if not ads:
                continue
            n_h = max(len(a.get("headlines", [])) for a in ads)
            n_d = max(len(a.get("descriptions", [])) for a in ads)
            header = ADS_FIXED + [f"Headline {i}" for i in range(1, n_h + 1)] + [f"Description {i}" for i in range(1, n_d + 1)] + ADS_TAIL
            ad_rows = []
            for a in ads:
                h = list(a.get("headlines", [])) + [""] * (n_h - len(a.get("headlines", [])))
                d = list(a.get("descriptions", [])) + [""] * (n_d - len(a.get("descriptions", [])))
                ad_rows.append([a.get("campaign", ""), a.get("ad_group", ""), "Responsive search ad"] + h + d +
                               [a.get("path1", ""), a.get("path2", ""), a.get("final_url", ""),
                                STATUS[str(a.get("status", "paused")).lower()]])
            write(out / "ads.csv", header, ad_rows, args.utf8, template)
            written.append(("ads.csv", len(ad_rows)))
            continue
        if rows[name]:
            write(out / f"{name}.csv", FILES[name], rows[name], args.utf8, template)
            written.append((f"{name}.csv", len(rows[name])))
    rolled = []
    for name in ORDER:
        if name in rollback and rollback[name]:
            write(out / "rollback" / f"{name}.csv", FILES[name], rollback[name], args.utf8, template)
            rolled.append((f"rollback/{name}.csv", len(rollback[name])))

    lines = [f"# Google Ads Editor import: {batch.get('name', Path(args.changes).stem)}", ""]
    lines.append(f"Account: {batch.get('account_name', '')} {batch.get('account_id', '')}".rstrip())
    lines.append(f"Approved by: {batch.get('approved_by') or 'NOT APPROVED (draft)'} {batch.get('approved_at', '')}".rstrip())
    lines.append(f"Encoding: {'UTF-8, comma-separated' if args.utf8 else 'UTF-16, tab-separated'}")
    lines += ["", "## Import these files in this order", ""]
    lines += [f"{i}. `{f}` ({n} rows)" for i, (f, n) in enumerate(written, 1)] or ["Nothing to import."]
    lines += ["", "## Rollback files (import only to undo)", ""]
    lines += [f"- `{f}` ({n} rows)" for f, n in rolled] or ["- None"]
    lines += ["", "## Undo by hand (Editor files can't express these)", ""]
    lines += [f"- {m}" for m in no_rollback] or ["- None"]
    lines += ["", "## Apply through a connector or the Google Ads UI (not in these files)", ""]
    lines += [f"- {m}" for m in manual] or ["- None"]
    if skipped:
        lines += ["", "## Skipped", ""] + [f"- {s}" for s in skipped]
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for f, n in written:
        print(f"wrote {out / f} ({n} rows)")
    for f, n in rolled:
        print(f"wrote {out / f} ({n} rows)")
    print(f"wrote {out / 'manifest.md'}")
    if manual:
        print(f"{len(manual)} change(s) need a connector or the Google Ads UI; see manifest.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
