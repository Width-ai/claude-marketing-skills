#!/usr/bin/env python3
"""Keep a Google Ads change log: what changed, why, and when to check the result.

The log is a CSV (default .agents/google-ads-change-log.csv). Commands:

  init       Create an empty log.
  add        Add entries from a change set JSON (--from) or one entry from flags.
  update     Change an entry's status, outcome, applied time, or review date.
  due        List applied changes whose review date has arrived and that have no outcome.
  reconcile  Compare the log with the account's change history (normalized CSV)
             and list changes nobody logged, grouped by who made them.
  summary    Markdown summary of changes in a date range, grouped by campaign.

Examples:
  changelog.py init
  changelog.py add --from google-ads-changes/2026-11-14-negatives.json --status applied \\
      --applied-via editor --approved-by "Matt" --conversion-lag 7
  changelog.py add --action set_budget --campaign "Brand" --before 50 --after 60 \\
      --reason "Lost 30% impression share to budget" --status applied --applied-via ui
  changelog.py update 12 --outcome "CPA 82 to 71, 14 days before vs after" --status verified
  changelog.py due
  changelog.py reconcile --history google-ads-data/2026-11-14/change_history.csv
  changelog.py summary --since 2026-10-01 --until 2026-10-31

Add --log PATH to use a different log file. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

COLUMNS = ["id", "logged_at", "status", "account_id", "campaign", "ad_group", "entity_type", "entity",
           "action", "field", "before", "after", "reason", "evidence", "expected_effect", "approved_by",
           "applied_via", "applied_at", "review_on", "outcome", "notes", "change_set"]
STATUSES = ["proposed", "approved", "applied", "verified", "rejected", "rolled_back"]

# Days to wait before judging a change; bidding changes also wait out the conversion delay.
REVIEW_DAYS = {
    "set_target": 14, "set_bid_strategy": 14, "set_keyword_bid": 14, "set_budget": 7,
    "add_negative": 14, "remove_negative": 14, "add_keyword": 14, "add_rsa": 14,
    "add_assets": 21, "enable_ai_max": 14, "set_status": 7, "other": 14,
}
BIDDING = {"set_target", "set_bid_strategy", "set_keyword_bid"}

# Which change history resource types each action shows up as.
RESOURCE_TYPES = {
    "add_negative": {"campaign_criterion", "ad_group_criterion", "shared_criterion", "shared_set"},
    "remove_negative": {"campaign_criterion", "ad_group_criterion", "shared_criterion"},
    "add_keyword": {"ad_group_criterion"},
    "set_keyword_bid": {"ad_group_criterion"},
    "set_budget": {"campaign_budget"},
    "set_target": {"campaign", "bidding_strategy"},
    "set_bid_strategy": {"campaign", "bidding_strategy"},
    "add_rsa": {"ad_group_ad", "ad"},
    "add_assets": {"asset", "campaign_asset", "ad_group_asset", "asset_group_asset", "customer_asset"},
    "enable_ai_max": {"campaign"},
}
STATUS_RESOURCE = {"campaign": "campaign", "ad_group": "ad_group", "keyword": "ad_group_criterion"}

CLIENT_LABELS = {
    "google_ads_web_client": "Google Ads UI",
    "google_ads_api": "API tool or connector",
    "google_ads_scripts": "Google Ads Script",
    "google_ads_automated_rule": "Automated rule",
    "google_ads_bulk_upload": "Bulk upload",
    "google_ads_recommendations": "Recommendation applied (often auto-apply)",
    "google_ads_mobile_app": "Google Ads mobile app",
    "internal_tool": "Google internal tool",
    "search_ads_360_sync": "Search Ads 360",
    "search_ads_360_post": "Search Ads 360",
    "other": "Other",
    "unknown": "Unknown",
}


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_log(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def next_id(rows: list[dict]) -> int:
    ids = [int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()]
    return (max(ids) if ids else 0) + 1


def review_date(action: str, start: dt.date, lag: int) -> str:
    days = REVIEW_DAYS.get(action, 14) + (lag if action in BIDDING else 0)
    return (start + dt.timedelta(days=days)).isoformat()


def describe(change: dict) -> tuple[str, str, str]:
    """Return (entity_type, entity, field) for a change set entry."""
    action = change.get("action", "")
    kw = change.get("keyword", "")
    match = change.get("match_type", "")
    if action in ("add_negative", "remove_negative"):
        return f"{change.get('level', '')}_negative", f"{kw} ({match})", "negative keyword"
    if action in ("add_keyword", "set_keyword_bid"):
        return "keyword", f"{kw} ({match})", "max_cpc" if action == "set_keyword_bid" else "keyword"
    if action == "set_status":
        entity = change.get("entity", "")
        name = {"campaign": change.get("campaign", ""), "ad_group": change.get("ad_group", ""),
                "keyword": f"{kw} ({match})"}.get(entity, "")
        return entity, name, "status"
    if action == "set_budget":
        return "campaign", change.get("campaign", ""), "daily budget"
    if action == "set_target":
        return "campaign", change.get("campaign", ""), f"target {change.get('target_type', '')}"
    if action == "add_rsa":
        return "ad", f"RSA in {change.get('ad_group', '')}", "new ad"
    return change.get("entity_type", ""), change.get("entity", ""), change.get("field", "")


def cmd_init(args) -> None:
    path = Path(args.log)
    if path.exists():
        sys.exit(f"{path} already exists")
    write_log(path, [])
    print(f"created {path}")


def cmd_add(args) -> None:
    path = Path(args.log)
    rows = read_log(path)
    now = dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    start = dt.date.fromisoformat(args.applied_at[:10]) if args.applied_at else dt.date.today()
    new: list[dict] = []
    if args.source:
        batch = json.loads(Path(args.source).read_text(encoding="utf-8"))
        for change in batch.get("changes", []):
            if change.get("approved") is False:
                continue
            entity_type, entity, field = describe(change)
            action = change.get("action", "other")
            before = change.get("from", "")
            after = change.get("to", "")
            if action in ("add_negative", "add_keyword", "add_rsa"):
                before, after = "", "added" + (" (paused)" if action != "add_negative" and str(change.get("status", "paused")).lower() == "paused" else "")
            new.append({
                "status": args.status, "account_id": batch.get("account_id", ""),
                "campaign": change.get("campaign", ""), "ad_group": change.get("ad_group", ""),
                "entity_type": entity_type, "entity": entity, "action": action, "field": field,
                "before": before, "after": after,
                "reason": change.get("reason") or "reason not recorded",
                "evidence": change.get("evidence", ""), "expected_effect": change.get("expected_effect", ""),
                "approved_by": args.approved_by or batch.get("approved_by", ""),
                "applied_via": args.applied_via or "", "change_set": Path(args.source).name,
            })
    else:
        if not args.action:
            sys.exit("give --from CHANGE_SET.json or --action with details")
        new.append({
            "status": args.status, "account_id": args.account_id or "", "campaign": args.campaign or "",
            "ad_group": args.ad_group or "", "entity_type": args.entity_type or "", "entity": args.entity or "",
            "action": args.action, "field": args.field or "", "before": args.before or "", "after": args.after or "",
            "reason": args.reason or "reason not recorded", "evidence": args.evidence or "",
            "expected_effect": args.expected_effect or "", "approved_by": args.approved_by or "",
            "applied_via": args.applied_via or "", "notes": args.notes or "",
        })
        if not new[-1]["entity"] and args.action in ("set_budget", "set_target", "set_bid_strategy", "enable_ai_max"):
            new[-1]["entity"], new[-1]["entity_type"] = args.campaign or "", new[-1]["entity_type"] or "campaign"
    first = next_id(rows)
    for i, row in enumerate(new):
        row["id"] = str(first + i)
        row["logged_at"] = now
        if row["status"] in ("applied", "verified"):
            row["applied_at"] = args.applied_at or now
            row["review_on"] = args.review_on or review_date(row["action"], start, args.conversion_lag)
        rows.append(row)
    write_log(path, rows)
    for row in new:
        missing = " (REASON MISSING)" if row["reason"] == "reason not recorded" else ""
        print(f"#{row['id']} {row['status']}: {row['action']} {row['entity']} in {row['campaign']}"
              f"{', review on ' + row['review_on'] if row.get('review_on') else ''}{missing}")


def cmd_update(args) -> None:
    path = Path(args.log)
    rows = read_log(path)
    target = [r for r in rows if r["id"] == str(args.id)]
    if not target:
        sys.exit(f"no entry #{args.id}")
    row = target[0]
    if args.status:
        if args.status not in STATUSES:
            sys.exit(f"status must be one of {', '.join(STATUSES)}")
        row["status"] = args.status
        if args.status == "applied" and not row.get("applied_at"):
            row["applied_at"] = args.applied_at or dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
            start = dt.date.fromisoformat(row["applied_at"][:10])
            row["review_on"] = row.get("review_on") or review_date(row["action"], start, args.conversion_lag)
    for field in ("outcome", "notes", "review_on", "applied_via", "approved_by", "reason"):
        value = getattr(args, field, None)
        if value:
            row[field] = value
    write_log(path, rows)
    print(f"updated #{row['id']}: status {row['status']}, review on {row.get('review_on', '')}, outcome: {row.get('outcome', '')}")


def cmd_due(args) -> None:
    rows = read_log(Path(args.log))
    today = args.today or dt.date.today().isoformat()
    due = [r for r in rows if r.get("status") == "applied" and r.get("review_on") and r["review_on"] <= today and not r.get("outcome")]
    if not due:
        print(f"No reviews due as of {today}.")
        return
    print(f"| # | Review on | Campaign | Change | Before → after | Reason |\n|---|---|---|---|---|---|")
    for r in sorted(due, key=lambda r: r["review_on"]):
        print(f"| {r['id']} | {r['review_on']} | {r['campaign']} | {r['action']} {r['entity']} | "
              f"{r['before']} → {r['after']} | {r['reason']} |")


def history_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    out = []
    for r in rows:
        when = r.get("change_date_time") or r.get("date") or ""
        out.append({
            "when": when[:19], "day": when[:10],
            "resource": (r.get("change_resource_type") or "").lower(),
            "operation": (r.get("change_operation") or "").lower(),
            "client": (r.get("client_type") or "unknown").lower(),
            "user": r.get("user_email", ""), "fields": r.get("changed_fields", ""),
            # change_event.campaign is a resource name (customers/1/campaigns/2), not a campaign name.
            "campaign": "" if (r.get("campaign") or r.get("change_campaign") or "").startswith("customers/")
                        else (r.get("campaign") or r.get("change_campaign") or ""),
            "resource_name": r.get("change_resource_name", ""),
        })
    return out


def cmd_reconcile(args) -> None:
    log = read_log(Path(args.log))
    history = history_rows(args.history)
    if args.since:
        history = [h for h in history if h["day"] >= args.since]
    if args.until:
        history = [h for h in history if h["day"] <= args.until]
    days = sorted(h["day"] for h in history if h["day"])
    start, end = (days[0], days[-1]) if days else ("", "")
    applied = [r for r in log if r.get("status") in ("applied", "verified", "rolled_back")
               and start <= (r.get("applied_at") or "")[:10] <= end]

    def window(day: str) -> set[str]:
        d = dt.date.fromisoformat(day)
        return {(d + dt.timedelta(days=k)).isoformat() for k in (-1, 0, 1)}

    used: set[int] = set()
    unmatched_log = []
    for entry in applied:
        if entry.get("applied_via") == "editor":
            continue  # Editor changes never appear in the API change history.
        types = set(RESOURCE_TYPES.get(entry["action"], set()))
        if entry["action"] == "set_status":
            types = {STATUS_RESOURCE.get(entry.get("entity_type", ""), "")}
        days_ok = window(entry["applied_at"][:10])
        found = False
        for i, h in enumerate(history):
            if i in used or h["day"] not in days_ok:
                continue
            if types and h["resource"] not in types:
                continue
            if entry.get("campaign") and h["campaign"] and entry["campaign"].lower() not in h["campaign"].lower():
                continue
            used.add(i)
            found = True
            break
        if not found:
            unmatched_log.append(entry)

    editor_entries = [e for e in applied if e.get("applied_via") == "editor"]
    unlogged = [h for i, h in enumerate(history) if i not in used]
    by_client: "defaultdict[str, list[dict]]" = defaultdict(list)
    for h in unlogged:
        by_client[CLIENT_LABELS.get(h["client"], h["client"])].append(h)

    print(f"Change history: {len(history)} changes from {start or '?'} to {end or '?'}; "
          f"log: {len(applied)} applied changes in that window.\n")
    print(f"## Changes in the account with no log entry ({len(unlogged)})\n")
    if not unlogged:
        print("None.\n")
    for client, items in sorted(by_client.items(), key=lambda kv: -len(kv[1])):
        print(f"### {client} ({len(items)})\n")
        print("| When | Resource | Operation | User | Fields |\n|---|---|---|---|---|")
        for h in items[: args.limit]:
            print(f"| {h['when']} | {h['resource']} | {h['operation']} | {h['user']} | {h['fields'][:80]} |")
        if len(items) > args.limit:
            print(f"| ... | {len(items) - args.limit} more | | | |")
        print()
    print(f"## Logged changes with no match in the history ({len(unmatched_log)})\n")
    if not unmatched_log:
        print("None.\n")
    for e in unmatched_log:
        print(f"- #{e['id']} {e['applied_at'][:10]} {e['action']} {e['entity']} in {e['campaign']} "
              f"(applied via {e.get('applied_via') or 'unknown'}): check it was really applied")
    if editor_entries:
        print(f"\n{len(editor_entries)} logged change(s) were applied through Google Ads Editor. "
              "Editor changes don't appear in the API change history, so they weren't matched.")
    if any(h["client"] == "google_ads_recommendations" for h in unlogged):
        print("\nSome changes came from recommendations Google applied. Check whether auto-apply is on.")


def cmd_summary(args) -> None:
    rows = read_log(Path(args.log))
    since, until = args.since or "0000", args.until or "9999"
    rows = [r for r in rows if since <= ((r.get("applied_at") or r.get("logged_at") or "")[:10]) <= until]
    if not rows:
        print("No changes in that range.")
        return
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in sorted(rows, key=lambda r: (r.get("campaign", ""), r.get("applied_at") or r.get("logged_at"))):
        groups.setdefault(r.get("campaign") or "(account)", []).append(r)
    counts = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    print(f"# Google Ads changes, {args.since or 'start'} to {args.until or 'now'}\n")
    print(", ".join(f"{n} {s}" for s, n in counts.items()) + "\n")
    for campaign, items in groups.items():
        print(f"## {campaign}\n")
        for r in items:
            when = (r.get("applied_at") or r.get("logged_at") or "")[:10]
            change = f"{r['action']} {r['entity']}".strip()
            arrow = f": {r['before']} → {r['after']}" if (r.get("before") or r.get("after")) else ""
            outcome = f" Outcome: {r['outcome']}" if r.get("outcome") else (
                f" Review on {r['review_on']}." if r.get("review_on") else "")
            print(f"- {when} [{r['status']}] {change}{arrow}. Why: {r['reason']}.{outcome}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", default=".agents/google-ads-change-log.csv")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")

    a = sub.add_parser("add")
    a.add_argument("--from", dest="source")
    a.add_argument("--status", default="applied", choices=STATUSES)
    for flag in ("account-id", "campaign", "ad-group", "entity-type", "entity", "action", "field", "before",
                 "after", "reason", "evidence", "expected-effect", "approved-by", "applied-via", "applied-at",
                 "review-on", "notes"):
        a.add_argument(f"--{flag}")
    a.add_argument("--conversion-lag", type=int, default=0)

    u = sub.add_parser("update")
    u.add_argument("id")
    u.add_argument("--status")
    for flag in ("outcome", "notes", "review-on", "applied-via", "approved-by", "reason", "applied-at"):
        u.add_argument(f"--{flag}")
    u.add_argument("--conversion-lag", type=int, default=0)

    d = sub.add_parser("due")
    d.add_argument("--today")

    r = sub.add_parser("reconcile")
    r.add_argument("--history", required=True)
    r.add_argument("--since")
    r.add_argument("--until")
    r.add_argument("--limit", type=int, default=25)

    s = sub.add_parser("summary")
    s.add_argument("--since")
    s.add_argument("--until")

    args = parser.parse_args()
    {"init": cmd_init, "add": cmd_add, "update": cmd_update, "due": cmd_due,
     "reconcile": cmd_reconcile, "summary": cmd_summary}[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
