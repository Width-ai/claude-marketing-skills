"""Compare a headline copy file with the live ad, and write the plan for testing the change.

The copy file holds the ad's new headline set: lines carried over unchanged
(source "kept") and new lines. This script checks the swap against the live ad,
then writes the steps for the route the person picked.

Errors (exit code 1):
  - the copy file doesn't hold exactly one ad group with one RSA
  - a line marked "kept" isn't in the live ad exactly as written. Google treats
    any change, even capitals or spacing, as a new line with no history.
  - no live headline is removed and none is added, so there's nothing to test

Warnings: a new line that's already in the ad (mark it kept), kept lines whose
pin changed, descriptions, paths, or final URL that differ from the live ad,
and more headlines swapped than --max-swap.

Routes:
  variation  An ad variation (Experiments > Ad variations > Update text) on the
             live ad, with a 50% split. The cleanest test. Set up by hand.
  new-ad     A new paused RSA in the same ad group, built by
             build_upload_files.py. The old ad stays until you pause it.
  edit       Edit the live ad. Google keeps the old version's stats separately,
             and the new version starts learning again. Use only when asked.

Usage:
  python3 plan_swap.py COPY.json --current AD_FILE [--ad-id ID]
      [--route variation|new-ad|edit] [--change-set FILE]
      [--review-days 28] [--max-swap 4] [--today YYYY-MM-DD] [--markdown PLAN.md]

--current takes the ad as the connector returns it, or an Editor or Google
Ads export with Headline 1 to 15 columns. --change-set adds one "other" entry
for google-ads-apply-changes to preview and log; for the new-ad route, pass the
change set build_upload_files.py wrote and the entry is appended to it.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_headlines import load_ads  # noqa: E402

MAX_SWAP = 4
REVIEW_DAYS = 28


def line_text(item) -> str:
    return (item.get("text") if isinstance(item, dict) else str(item or "")).strip()


def squash(text: str) -> str:
    return " ".join(text.split()).lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("copy")
    parser.add_argument("--current", required=True)
    parser.add_argument("--ad-id")
    parser.add_argument("--route", choices=["variation", "new-ad", "edit"], default="variation")
    parser.add_argument("--change-set")
    parser.add_argument("--review-days", type=int, default=REVIEW_DAYS)
    parser.add_argument("--max-swap", type=int, default=MAX_SWAP)
    parser.add_argument("--today")
    parser.add_argument("--markdown")
    args = parser.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    copy = json.loads(Path(args.copy).read_text(encoding="utf-8-sig"))
    errors, warnings = [], []

    groups = copy.get("ad_groups") or []
    rsas = [r for g in groups for r in (g.get("rsas") or [])]
    if len(groups) != 1 or len(rsas) != 1:
        errors.append(f"the copy file holds {len(groups)} ad group(s) and {len(rsas)} RSA(s); this plan needs "
                      "exactly one of each, the ad being optimized")
        return finish(errors, warnings, None, args)
    group, rsa = groups[0], rsas[0]

    ads = load_ads([args.current])
    if args.ad_id:
        ads = [a for a in ads if a["id"] == args.ad_id.strip()]
    ads = [a for a in ads if a["headlines"]]
    if len(ads) != 1:
        errors.append(f"found {len(ads)} ads with headlines in {args.current}; "
                      + ("pass --ad-id" if len(ads) > 1 else "check the file is the live ad"))
        return finish(errors, warnings, None, args)
    live = ads[0]
    if live["ad_group"] and group.get("ad_group") and live["ad_group"].strip().lower() != group["ad_group"].strip().lower():
        errors.append(f"the copy file is for ad group '{group['ad_group']}' but the live ad is in '{live['ad_group']}'")

    live_heads = {t: p for t, p in live["headlines"]}
    live_squashed = {squash(t): t for t in live_heads}
    new_heads = rsa.get("headlines") or []
    kept, added = [], []
    for item in new_heads:
        text = line_text(item)
        source = item.get("source", "") if isinstance(item, dict) else ""
        pin = str(item.get("pin") or "") if isinstance(item, dict) else ""
        if source == "kept":
            if text in live_heads:
                kept.append(text)
                if (live_heads[text] or "") != pin:
                    warnings.append(f"'{text}' was pinned to {live_heads[text] or 'none'} and is now pinned to "
                                    f"{pin or 'none'}")
            elif squash(text) in live_squashed:
                errors.append(f"kept line '{text}' differs from the live '{live_squashed[squash(text)]}' in capitals "
                              "or spacing; copy it exactly, or Google treats it as a new line")
            else:
                errors.append(f"kept line '{text}' isn't in the live ad; copy it exactly, or tag it as new")
        else:
            if text in live_heads:
                warnings.append(f"'{text}' is already in the live ad; mark it source 'kept'")
                kept.append(text)
            else:
                added.append({"text": text, "source": source or "new", "role": item.get("role", "")
                              if isinstance(item, dict) else "", "pin": pin})
    removed = [t for t in live_heads if t not in kept]
    if not removed and not added:
        errors.append("no headline is removed or added, so there's nothing to test")
    if len(removed) > args.max_swap or len(added) - len(removed) > args.max_swap:
        warnings.append(f"{len(removed)} removed and {len(added)} added; more than {args.max_swap} changes at once "
                        "makes it hard to tell which line made the difference")

    live_desc = [t for t, _ in live["descriptions"]]
    new_desc = [line_text(d) for d in rsa.get("descriptions") or []]
    if live_desc and sorted(live_desc) != sorted(new_desc):
        warnings.append("the descriptions differ from the live ad; this skill changes headlines only, so check "
                        "that's intended")
    for field, live_value in (("path1", live["path1"]), ("path2", live["path2"])):
        if live_value and (rsa.get(field) or "") != live_value:
            warnings.append(f"{field} is '{rsa.get(field) or ''}' in the copy file and '{live_value}' in the live ad")
    url = rsa.get("final_url") or group.get("final_url") or ""
    if live["final_url"] and url and url.rstrip("/") != live["final_url"].rstrip("/"):
        warnings.append(f"final URL is {url} in the copy file and {live['final_url']} in the live ad")

    plan = {
        "campaign": copy.get("campaign") or live["campaign"], "ad_group": group.get("ad_group") or live["ad_group"],
        "ad_id": live["id"], "route": args.route, "kept": kept, "removed": removed, "added": added,
        "pins": [(t, p) for t, p in live["headlines"] if p and t in kept],
        "headline_count": len(kept) + len(added),
        "review_on": (today + dt.timedelta(days=args.review_days)).isoformat(), "today": today.isoformat(),
        "review_days": args.review_days,
        "reason": copy.get("reason", ""), "evidence": copy.get("evidence", ""),
        "expected_effect": copy.get("expected_effect", ""),
    }
    if not errors and args.change_set:
        write_change_set(args.change_set, copy, plan)
    return finish(errors, warnings, plan, args)


def steps(plan: dict) -> list[str]:
    removed = "; ".join(f"'{t}'" for t in plan["removed"]) or "none"
    added = "; ".join(f"'{a['text']}'" for a in plan["added"]) or "none"
    marker = next((t for t in plan["kept"] if not any(t in a["text"] for a in plan["added"])), "")
    if plan["route"] == "variation":
        return [
            "In Google Ads, open **Campaigns > Experiments**, then the **Ad variations** tab, and click the plus button.",
            f"Under **Select ads**, choose the campaign **{plan['campaign']}**. Under **Target ad type**, choose "
            "**Responsive search ads**.",
            f"Under **Filter ads**, add a rule so only this ad matches: headline contains **{marker}**. Check the "
            "count of matching ads before you continue; if other ads match, add a second rule."
            if marker else "Under **Filter ads**, add rules so only this ad matches, and check the count.",
            "Choose **Update text**.",
            f"Remove these headlines: {removed}.",
            f"Add these headlines: {added}."
            + (" Keep the existing pins." if plan["pins"] else ""),
            f"Name it, set the start date, and an end date at least {plan['review_days']} days later. Set the experiment "
            "split to 50%, so half the people see the variation.",
            "Click **Create variation**. It starts on the start date.",
            f"Review on {plan['review_on']}: compare clicks, CTR, conversions, and cost per conversion between the "
            "original and the variation on the Ad variations tab. If the variation wins, apply it there (applying "
            "can create new ads). If not, end it and keep the original.",
        ]
    if plan["route"] == "new-ad":
        return [
            "Apply the new ad through google-ads-apply-changes, or import the Editor files from "
            "`build_upload_files.py`. It goes in paused.",
            "Check the ad group has room: Google allows 3 enabled RSAs per ad group.",
            "When you're ready to test, enable the new ad. Leave the old one running beside it so you can compare "
            "them, or pause it if you'd rather switch outright.",
            f"Review on {plan['review_on']}: compare the two ads on the Ads page over the same dates. Google favors "
            "the ad it expects to win, so the two won't get equal traffic.",
        ]
    return [
        f"In Google Ads, open the ad in **{plan['ad_group']}** and click edit.",
        f"Remove these headlines: {removed}.",
        f"Add these headlines: {added}.",
        "Save. Google keeps the old version's stats separately, and the edited ad starts learning again.",
        f"Review on {plan['review_on']}: compare the new version with the same number of days before the edit, "
        "keeping in mind that seasons and bids change too.",
    ]


def write_change_set(path: str, copy: dict, plan: dict) -> None:
    p = Path(path)
    if p.exists():
        cs = json.loads(p.read_text(encoding="utf-8-sig"))
    else:
        cs = {"name": copy.get("name", "headline test"), "account_id": copy.get("account_id", ""),
              "account_name": copy.get("account_name", ""), "created": plan["today"], "approved_by": "",
              "approved_at": "", "changes": []}
    ids = {c.get("id") for c in cs.get("changes", [])}
    n = 1
    while f"c{n}" in ids:
        n += 1
    removed = "; ".join(f"'{t}'" for t in plan["removed"]) or "none"
    added = "; ".join(f"'{a['text']}'" for a in plan["added"]) or "none"
    if plan["route"] == "variation":
        description = (f"Ad variation (Update text, 50% split) on RSA {plan['ad_id'] or ''} in {plan['ad_group']}: "
                       f"remove {removed}; add {added}")
    elif plan["route"] == "new-ad":
        description = (f"When the new RSA in {plan['ad_group']} is approved, enable it; keep or pause the old RSA "
                       f"{plan['ad_id'] or ''}. Headlines removed from the old ad: {removed}")
    else:
        description = f"Edit RSA {plan['ad_id'] or ''} in {plan['ad_group']}: remove {removed}; add {added}"
    cs.setdefault("changes", []).append({
        "id": f"c{n}", "action": "other", "campaign": plan["campaign"], "ad_group": plan["ad_group"],
        "description": description,
        "reason": plan["reason"] or "Replace headlines that lag the rest of the ad",
        "evidence": plan["evidence"], "expected_effect": plan["expected_effect"],
    })
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def finish(errors, warnings, plan, args) -> int:
    lines = []
    if plan:
        lines += [f"# Headline test plan: {plan['campaign']} / {plan['ad_group']}"
                  + (f" / ad {plan['ad_id']}" if plan["ad_id"] else ""), "",
                  f"**Route:** {plan['route']}. **Headlines after the change:** {plan['headline_count']} "
                  f"({len(plan['kept'])} kept, {len(plan['removed'])} removed, {len(plan['added'])} added).", "",
                  "| Change | Headline | Source |", "|---|---|---|"]
        lines += [f"| remove | {t} | live ad |" for t in plan["removed"]]
        lines += [f"| add | {a['text']} | {a['source']} |" for a in plan["added"]]
        lines += [f"| keep | {t} | live ad |" for t in plan["kept"]]
        lines.append("")
        if plan["pins"]:
            lines.append("Pins kept: " + ", ".join(f"'{t}' at {p}" for t, p in plan["pins"]))
            lines.append("")
    if errors:
        lines += ["**Errors:**"] + [f"- {e}" for e in errors] + [""]
    if warnings:
        lines += ["**Warnings:**"] + [f"- {w}" for w in warnings] + [""]
    if plan and not errors:
        lines += ["## Steps", ""] + [f"{i}. {s}" for i, s in enumerate(steps(plan), 1)] + [""]
        if args.change_set:
            lines.append(f"Change set entry written to {args.change_set}.")
    text = "\n".join(lines)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.markdown:
        print(f"\nwrote {args.markdown}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
