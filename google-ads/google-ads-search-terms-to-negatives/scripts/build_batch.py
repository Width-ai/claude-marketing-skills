#!/usr/bin/env python3
"""Turn reviewed proposals into a change set for google-ads-apply-changes, plus a standalone fallback.

Reads proposals.csv from review_terms.py after the person has reviewed it. Rows
with include set to anything other than yes are left out.

Writes:
  - a change set JSON in the google-ads-apply-changes format, split into parts
    when it has more changes than the batch limit (Max changes per batch in
    the account context, or 50). Negatives at campaign and ad group level are
    add_negative. New keywords are add_keyword, exact, status paused. Negatives
    for a shared list are "other" entries, applied by hand or through a
    connector, because the change set has no shared-list action.
  - with --fallback-dir: Google Ads Editor import files (negatives.csv and
    keywords.csv, UTF-16 tab-separated like Editor's own exports) and
    manual-steps.md with numbered steps for the Google Ads interface, for when
    google-ads-apply-changes isn't installed. Needs --approved-by (the person
    who approved the review) or --draft.

The change set itself is never marked approved here: google-ads-apply-changes
previews it and records the approval.

Usage:
  python3 build_batch.py proposals.csv --out google-ads-changes/2026-11-14-search-term-negatives.json
      [--context .agents/google-ads-context.md] [--account-id 123-456-7890] [--account-name NAME]
      [--name "2026-11-14 search term negatives"] [--max-changes 50] [--today YYYY-MM-DD]
      [--fallback-dir FOLDER (--approved-by NAME | --draft) [--utf8]]

Standard library only.
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

MATCH = {"exact", "phrase", "broad"}
LEVELS = {"campaign", "ad_group", "shared_list"}
KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 80, 10
CRITERION = {"exact": "Exact", "phrase": "Phrase", "broad": "Broad"}
UI_SYNTAX = {"exact": "[{}]", "phrase": '"{}"', "broad": "{}"}


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def parse_context(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    out = {}
    m = re.search(r"(?m)^\*\*Account:\*\*\s*(.+?)\s*\(([\d-]+)\)\s*$", text)
    if m:
        out["account_name"], out["account_id"] = m.group(1).strip(), m.group(2)
    m = re.search(r"max(?:imum)? changes per batch[^:\n]*:\s*(\d+)", text, re.IGNORECASE)
    if m:
        out["max_changes"] = int(m.group(1))
    return out


def write_editor(path: Path, header: list[str], rows: list[list[str]], utf8: bool) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="," if utf8 else "\t", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    data = buffer.getvalue()
    path.write_bytes(data.encode("utf-8-sig") if utf8 else data.encode("utf-16"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("proposals")
    parser.add_argument("--out", required=True, help="change set path, such as google-ads-changes/2026-11-14-search-term-negatives.json")
    parser.add_argument("--context")
    parser.add_argument("--account-id")
    parser.add_argument("--account-name")
    parser.add_argument("--name")
    parser.add_argument("--max-changes", type=int)
    parser.add_argument("--today")
    parser.add_argument("--fallback-dir")
    parser.add_argument("--approved-by")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--utf8", action="store_true")
    args = parser.parse_args()

    if args.fallback_dir and not args.approved_by and not args.draft:
        print("error: --fallback-dir needs --approved-by NAME (who approved the review) or --draft", file=sys.stderr)
        return 1
    ctx = parse_context(args.context) if args.context and Path(args.context).exists() else {}
    today = args.today or dt.date.today().isoformat()
    limit = args.max_changes or ctx.get("max_changes") or 50
    rows = [r for r in read_csv(args.proposals) if r.get("include", "yes").lower() in ("yes", "y", "true", "1")]
    skipped = len(read_csv(args.proposals)) - len(rows)

    errors, changes = [], []
    for r in rows:
        pid, action, level = r.get("id", "?"), r.get("action", ""), r.get("level", "")
        keyword, match = r.get("keyword", "").strip(), r.get("match_type", "").lower()
        if match not in MATCH:
            errors.append(f"{pid}: match_type must be exact, phrase, or broad")
        if not keyword or len(keyword) > KEYWORD_MAX_CHARS or len(keyword.split()) > KEYWORD_MAX_WORDS:
            errors.append(f"{pid}: keyword missing or over {KEYWORD_MAX_WORDS} words or {KEYWORD_MAX_CHARS} characters")
        if level not in LEVELS:
            errors.append(f"{pid}: level must be campaign, ad_group, or shared_list")
        base = {"reason": r.get("reason", ""), "evidence": r.get("evidence", ""), "expected_effect": r.get("expected_effect", "")}
        if r.get("warnings"):
            base["review_notes"] = r["warnings"]
        if action == "add_keyword":
            if not r.get("campaign") or not r.get("ad_group"):
                errors.append(f"{pid}: add_keyword needs campaign and ad_group")
            changes.append({"action": "add_keyword", "campaign": r.get("campaign", ""), "ad_group": r.get("ad_group", ""),
                            "keyword": keyword, "match_type": match, "status": "paused", **base})
        elif level == "shared_list":
            if not r.get("shared_set"):
                errors.append(f"{pid}: a shared-list negative needs shared_set")
            covers = r.get("list_campaigns", "")
            changes.append({"action": "other", "entity_type": "other", "field": "negative keyword",
                            "entity": f"{keyword} ({match}) in list '{r.get('shared_set', '')}'",
                            "keyword": keyword, "match_type": match, "shared_set": r.get("shared_set", ""),
                            "campaigns": [c.strip() for c in covers.split(";") if c.strip()],
                            "description": (f"Add the negative keyword '{keyword}' ({match} match) to the negative keyword list "
                                            f"'{r.get('shared_set', '')}'. The list must be attached to: {covers or 'MISSING'}. "
                                            "If the list doesn't exist yet, create it and attach it to those campaigns."),
                            **base})
        elif action == "add_negative":
            if not r.get("campaign") or (level == "ad_group" and not r.get("ad_group")):
                errors.append(f"{pid}: add_negative needs campaign, and ad_group at ad group level")
            entry = {"action": "add_negative", "level": level, "campaign": r.get("campaign", "")}
            if level == "ad_group":
                entry["ad_group"] = r.get("ad_group", "")
            entry.update({"keyword": keyword, "match_type": match, **base})
            changes.append(entry)
        else:
            errors.append(f"{pid}: action must be add_negative or add_keyword")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1
    if not changes:
        print("no included proposals; nothing written")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = [changes[i:i + limit] for i in range(0, len(changes), limit)]
    name = args.name or f"{today} search term negatives"
    written = []
    for n, part in enumerate(parts, 1):
        path = out if len(parts) == 1 else out.with_name(f"{out.stem}-part{n}{out.suffix}")
        for i, c in enumerate(part, 1):
            c_ordered = {"id": f"c{i}"}
            c_ordered.update(c)
            part[i - 1] = c_ordered
        batch = {"name": name if len(parts) == 1 else f"{name} (part {n} of {len(parts)})",
                 "account_id": args.account_id or ctx.get("account_id", "MISSING"),
                 "account_name": args.account_name or ctx.get("account_name", "MISSING"),
                 "created": today, "source": "google-ads-search-terms-to-negatives",
                 "approved_by": "", "approved_at": "", "changes": part}
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append((path, len(part)))
    counts = {}
    for c in changes:
        key = "shared list negative" if c["action"] == "other" else c["action"]
        counts[key] = counts.get(key, 0) + 1
    for path, n in written:
        print(f"wrote {path} ({n} changes)")
    print("contents: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + (f"; {skipped} proposals left out" if skipped else ""))
    if len(parts) > 1:
        print(f"split into {len(parts)} parts of at most {limit} changes (Max changes per batch)")

    if args.fallback_dir:
        folder = Path(args.fallback_dir)
        folder.mkdir(parents=True, exist_ok=True)
        negs = [[c["campaign"], c.get("ad_group", ""), c["keyword"],
                 ("Campaign Negative " if c["level"] == "campaign" else "Negative ") + CRITERION[c["match_type"]]]
                for c in changes if c["action"] == "add_negative"]
        kws = [[c["campaign"], c["ad_group"], c["keyword"], CRITERION[c["match_type"]], "Paused"]
               for c in changes if c["action"] == "add_keyword"]
        lists = [c for c in changes if c["action"] == "other"]
        files = []
        if negs:
            write_editor(folder / "negatives.csv", ["Campaign", "Ad Group", "Keyword", "Criterion Type"], negs, args.utf8)
            files.append(("negatives.csv", len(negs)))
        if kws:
            write_editor(folder / "keywords.csv", ["Campaign", "Ad Group", "Keyword", "Criterion Type", "Status"], kws, args.utf8)
            files.append(("keywords.csv", len(kws)))
        status = f"Approved by {args.approved_by} on {today}" if args.approved_by else "DRAFT: not approved yet. Don't post it."
        L = [f"# {name}: steps to apply", "", status + ".", f"Account: {args.account_name or ctx.get('account_name', 'MISSING')} "
             f"({args.account_id or ctx.get('account_id', 'MISSING')})", ""]
        L += ["## Option A: Google Ads Editor", ""]
        if files:
            L += ["1. Open Google Ads Editor, select the account, and click **Get recent changes**."]
            step = 2
            for f, n in files:
                L.append(f"{step}. Go to **Account > Import > From file...** and choose `{f}` ({n} rows). Check the column "
                         "headers in the preview, then finish the import.")
                step += 1
            L += [f"{step}. Review the pending changes. A campaign or ad group you didn't expect means a name didn't match: "
                  "revert it before posting.",
                  f"{step + 1}. Click **Check changes**, fix anything it flags, then click **Post**.",
                  f"{step + 2}. New keywords arrive paused. Enable them when you're ready."]
        else:
            L.append("No Editor files: this batch only has shared-list changes.")
        L += ["", "## Option B: the Google Ads interface", "",
              "Google moves menu items now and then. If a path doesn't match, type the page name into the search bar at the top.", ""]
        step = 1
        camp_negs = [c for c in changes if c["action"] == "add_negative"]
        if camp_negs:
            L.append(f"{step}. **Negatives.** Go to **Campaigns > Keywords** (or **Audiences, keywords, and content > Search "
                     "keywords** in some layouts) and open the **Negative keywords** tab. Click the plus button, pick the "
                     "campaign or ad group, and paste the keywords below in the form shown. Brackets mean exact match, "
                     "quotes mean phrase match, and no marks means broad match. Click **Save**.")
            step += 1
            for c in camp_negs:
                where = c["campaign"] + (f" > ad group {c['ad_group']}" if c.get("ad_group") else " (campaign level)")
                L.append(f"   - {where}: `{UI_SYNTAX[c['match_type']].format(c['keyword'])}`")
        if lists:
            L.append(f"{step}. **Negative keyword lists.** Go to **Tools > Exclusion lists** and open the **Negative keywords "
                     "lists** tab. Open the list (or create it with the plus button), add the keywords below, and save. Then "
                     "check the list is applied to every campaign named: select it and click **Apply to campaigns**.")
            step += 1
            for c in lists:
                L.append(f"   - {c['shared_set']}: `{UI_SYNTAX[c['match_type']].format(c['keyword'])}` "
                         f"(applied to: {', '.join(c['campaigns']) or 'MISSING'})")
        if kws:
            L.append(f"{step}. **New keywords.** Go to **Campaigns > Keywords**, click the plus button, pick the ad group, paste "
                     "the keyword, and save. Then set each new keyword to **Paused** until you're ready to run it.")
            step += 1
            for c in changes:
                if c["action"] == "add_keyword":
                    L.append(f"   - {c['campaign']} > {c['ad_group']}: `[{c['keyword']}]`")
        L += ["", "## Undo", "",
              "- Remove a negative keyword from the same page or list where it was added. Removing it restores the "
              "searches it blocked; it can't recover clicks already missed.",
              "- Pause a new keyword rather than deleting it.", "",
              "## After applying", "",
              "Tell Claude when it's done, so the changes can be checked against the account and logged with a review date "
              "two weeks out."]
        (folder / "manual-steps.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        for f, n in files:
            print(f"wrote {folder / f} ({n} rows)")
        print(f"wrote {folder / 'manual-steps.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
