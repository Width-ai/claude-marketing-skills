#!/usr/bin/env python3
"""Turn a checked copy file into the files that get it into Google Ads.

Runs check_ad_copy.py's checks first and refuses to build while any error
remains. Then writes either or both of:

  --change-set FILE   a change set for the google-ads-apply-changes skill:
                      one add_rsa entry per RSA (status paused), plus "other"
                      entries for pins and for sitelinks, callouts, and
                      snippets, which apply-changes has no action for. The
                      batch is unapproved; apply-changes previews it and
                      records the approval.

  --editor-dir DIR    Google Ads Editor import files for when apply-changes
                      isn't installed: ads.csv (new RSAs, Paused),
                      sitelinks.csv, callouts.csv, structured_snippets.csv,
                      and manifest.md with the import order, the pins to set
                      by hand, and how to undo. Needs --approved-by NAME after
                      the person approves the copy, or --draft for a preview.

Files are UTF-16 with tabs, the format Google Ads Editor writes when it
exports. Use --utf8 for comma-separated UTF-8, and --template with a CSV
exported from your Editor to copy its exact header spellings.

Usage:
  python3 build_upload_files.py COPY.json
      [--context .agents/google-ads-context.md] [--claims approved-claims.txt]
      [--change-set google-ads-changes/DATE-NAME.json]
      [--editor-dir google-ads-changes/DATE-NAME-editor/]
      [--approved-by NAME | --draft] [--utf8] [--template EDITOR_EXPORT.csv]
      [--today YYYY-MM-DD]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the skill folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ad_copy as checker  # noqa: E402

ACCOUNT_LEVEL = "<Account-level>"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def texts(values) -> list[str]:
    return [v if isinstance(v, str) else str(v.get("text", "")) for v in values or []]


def pins(values, field: str) -> list[tuple[int, str]]:
    out = []
    for v in values or []:
        if isinstance(v, dict) and v.get("pin") not in (None, "", 0):
            pos = str(v["pin"]).lower().replace("headline_", "").replace("description_", "")
            out.append((int(pos), str(v.get("text", ""))))
    return sorted(out)


def load_template(path: str) -> dict:
    raw = Path(path).read_bytes()
    text = checker.decode(raw)
    first = text.splitlines()[0] if text else ""
    delimiter = "\t" if first.count("\t") >= first.count(",") else ","
    header = next(csv.reader(io.StringIO(first), delimiter=delimiter), [])
    return {h.strip().lower(): h.strip() for h in header if h.strip()}


def write_csv(path: Path, header: list[str], rows: list[list[str]], utf8: bool, template: dict) -> None:
    header = [template.get(h.lower(), h) for h in header]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="," if utf8 else "\t", lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = buffer.getvalue()
    path.write_bytes(data.encode("utf-8-sig") if utf8 else data.encode("utf-16"))


def asset_scopes(copy: dict):
    """Yield (level, campaign, ad_group, holder) for every place assets are defined."""
    campaign = copy.get("campaign", "")
    for level in ("account", "campaign"):
        yield level, campaign, "", {k: [a for a in checker.as_items(copy.get(k), k)
                                      if (a.get("level") or "campaign") == level]
                                  for k in ("sitelinks", "callouts", "snippets")}
    for group in copy.get("ad_groups") or []:
        yield "ad_group", campaign, group.get("ad_group", ""), {k: checker.as_items(group.get(k), k)
                                                              for k in ("sitelinks", "callouts", "snippets")}


def where_label(level: str, campaign: str, ad_group: str) -> str:
    return {"account": "the account", "campaign": f"campaign '{campaign}'"}.get(level, f"ad group '{ad_group}' "
                                                                                     f"in campaign '{campaign}'")


def build_change_set(copy: dict, copy_path: str) -> dict:
    campaign = copy.get("campaign", "")
    reason = copy.get("reason") or "New responsive search ad written from approved claims and checked with check_ad_copy.py"
    changes = []

    def next_id():
        return f"c{len(changes) + 1}"

    for group in copy.get("ad_groups") or []:
        gname = group.get("ad_group", "")
        for r_index, rsa in enumerate(group.get("rsas") or [], 1):
            entry = {
                "id": next_id(), "action": "add_rsa", "campaign": campaign, "ad_group": gname,
                "headlines": texts(rsa.get("headlines")), "descriptions": texts(rsa.get("descriptions")),
                "final_url": rsa.get("final_url") or group.get("final_url") or copy.get("final_url") or "",
                "path1": rsa.get("path1") or "", "path2": rsa.get("path2") or "", "status": "paused",
                "reason": rsa.get("reason") or reason,
                "evidence": rsa.get("evidence") or copy.get("evidence") or "",
                "expected_effect": rsa.get("expected_effect") or copy.get("expected_effect") or
                "A second ad angle for Google to test; compare against the existing ads at review",
            }
            changes.append(entry)
            hp, dp = pins(rsa.get("headlines"), "headline"), pins(rsa.get("descriptions"), "description")
            if hp or dp:
                parts = [f"Headline position {p}: '{t}'" for p, t in hp] + [f"Description position {p}: '{t}'" for p, t in dp]
                changes.append({
                    "id": next_id(), "action": "other", "campaign": campaign, "ad_group": gname,
                    "description": f"After the new ad from {entry['id']} is created (paused) in ad group '{gname}', "
                                   "pin these in the Google Ads interface before enabling it: " + "; ".join(parts),
                    "reason": "Pins can't be set through add_rsa; these lines must show in a fixed position",
                })
    for level, camp, gname, holder in asset_scopes(copy):
        place = where_label(level, camp, gname)
        sls, cos, sns = holder["sitelinks"], holder["callouts"], holder["snippets"]
        if sls:
            changes.append({
                "id": next_id(), "action": "other", "campaign": camp, **({"ad_group": gname} if gname else {}),
                "description": f"Add {len(sls)} sitelinks to {place} (sitelinks.csv from google-ads-rsa-asset-writer): "
                               + "; ".join(f"'{s.get('link_text', '')}' to {s.get('final_url', '')}" for s in sls),
                "reason": copy.get("assets_reason") or "Sitelinks written from approved claims and checked with check_ad_copy.py",
            })
        if cos:
            changes.append({
                "id": next_id(), "action": "other", "campaign": camp, **({"ad_group": gname} if gname else {}),
                "description": f"Add {len(cos)} callouts to {place} (callouts.csv from google-ads-rsa-asset-writer): "
                               + "; ".join(f"'{c.get('text', '')}'" for c in cos),
                "reason": copy.get("assets_reason") or "Callouts written from approved claims and checked with check_ad_copy.py",
            })
        for s in sns:
            changes.append({
                "id": next_id(), "action": "other", "campaign": camp, **({"ad_group": gname} if gname else {}),
                "description": f"Add a structured snippet to {place} (structured_snippets.csv from "
                               f"google-ads-rsa-asset-writer): header '{s.get('header', '')}', values "
                               + "; ".join(f"'{v}'" for v in s.get("values") or []),
                "reason": copy.get("assets_reason") or "Snippet checked with check_ad_copy.py",
            })
    return {
        "name": copy.get("name") or f"{copy.get('created', dt.date.today().isoformat())} new RSAs and assets: {campaign}",
        "account_id": copy.get("account_id", ""), "account_name": copy.get("account_name", ""),
        "created": copy.get("created") or dt.date.today().isoformat(),
        "approved_by": "", "approved_at": "",
        "source": f"google-ads-rsa-asset-writer, copy file {copy_path}",
        "changes": changes,
    }


def build_editor(copy: dict, out: Path, approved_by: str, utf8: bool, template: dict) -> list[str]:
    campaign = copy.get("campaign", "")
    written, manual_pins = [], []
    ads = []
    for group in copy.get("ad_groups") or []:
        for rsa in group.get("rsas") or []:
            ads.append((group, rsa))
            hp, dp = pins(rsa.get("headlines"), "headline"), pins(rsa.get("descriptions"), "description")
            if hp or dp:
                manual_pins.append(f"Ad group '{group.get('ad_group', '')}', ad '{rsa.get('id', '')}': " + "; ".join(
                    [f"Headline position {p}: '{t}'" for p, t in hp] + [f"Description position {p}: '{t}'" for p, t in dp]))
    if ads:
        n_h = max(len(texts(r.get("headlines"))) for _, r in ads)
        n_d = max(len(texts(r.get("descriptions"))) for _, r in ads)
        header = (["Campaign", "Ad Group", "Ad type"] + [f"Headline {i}" for i in range(1, n_h + 1)] +
                  [f"Description {i}" for i in range(1, n_d + 1)] + ["Path 1", "Path 2", "Final URL", "Status"])
        rows = []
        for group, rsa in ads:
            h, d = texts(rsa.get("headlines")), texts(rsa.get("descriptions"))
            rows.append([campaign, group.get("ad_group", ""), "Responsive search ad"] + h + [""] * (n_h - len(h)) +
                        d + [""] * (n_d - len(d)) +
                        [rsa.get("path1") or "", rsa.get("path2") or "",
                         rsa.get("final_url") or group.get("final_url") or copy.get("final_url") or "", "Paused"])
        write_csv(out / "ads.csv", header, rows, utf8, template)
        written.append(f"`ads.csv` ({plural(len(rows), 'new responsive search ad', 'new responsive search ads')}, "
                       "all Paused)")

    sl_rows, co_rows, sn_rows, has_group = [], [], [], {"sl": False, "co": False, "sn": False}
    for level, camp, gname, holder in asset_scopes(copy):
        c = ACCOUNT_LEVEL if level == "account" else camp
        for s in holder["sitelinks"]:
            sl_rows.append([c, gname, s.get("link_text", ""), s.get("description1") or "", s.get("description2") or "",
                            s.get("final_url", "")])
            has_group["sl"] |= bool(gname)
        for co in holder["callouts"]:
            co_rows.append([c, gname, co.get("text", "")])
            has_group["co"] |= bool(gname)
        for sn in holder["snippets"]:
            sn_rows.append([c, gname, sn.get("header", ""), ";".join(str(v) for v in sn.get("values") or [])])
            has_group["sn"] |= bool(gname)

    def emit(name, header, rows, group_flag, what_one, what_many):
        if not rows:
            return
        if not group_flag:
            header = [h for h in header if h != "Ad Group"]
            rows = [[r[0]] + r[2:] for r in rows]
        write_csv(out / name, header, rows, utf8, template)
        written.append(f"`{name}` ({plural(len(rows), what_one, what_many)})")

    emit("sitelinks.csv", ["Campaign", "Ad Group", "Link text", "Description line 1", "Description line 2", "Final URL"],
         sl_rows, has_group["sl"], "sitelink", "sitelinks")
    emit("callouts.csv", ["Campaign", "Ad Group", "Callout text"], co_rows, has_group["co"], "callout", "callouts")
    emit("structured_snippets.csv", ["Campaign", "Ad Group", "Header", "Snippet Values"], sn_rows, has_group["sn"],
         "structured snippet", "structured snippets")

    lines = [f"# Google Ads Editor import: {copy.get('name', '')}", "",
             f"Account: {copy.get('account_name', '')} {copy.get('account_id', '')}".rstrip(),
             f"Approved by: {approved_by or 'DRAFT, NOT APPROVED: for review only, do not post'}",
             f"Encoding: {'UTF-8, comma-separated' if utf8 else 'UTF-16, tab-separated'}", "",
             "## Import these files in this order", ""]
    lines += [f"{i}. {w}" for i, w in enumerate(written, 1)] or ["Nothing to import."]
    lines += ["", "## Check before you post", "",
              "- New ads are Paused. Turn each one on in Google Ads only after you've looked at it. "
              "Google allows 3 enabled responsive search ads per ad group, so pause an old one first if needed."]
    if manual_pins:
        lines += ["- Pins aren't in these files. Set them on the new paused ads before enabling:"]
        lines += [f"  - {p}" for p in manual_pins]
    if sl_rows or co_rows or sn_rows:
        lines += ["- Sitelinks, callouts, and snippets have no paused state in these files. They start showing with "
                  "the campaign's live ads as soon as you post. To hold them back, import them later."]
    if sn_rows:
        lines += ["- Structured snippet values are separated by semicolons in the Snippet Values column. Google's "
                  "Editor help names the column but not the separator, so check the import preview shows each value "
                  "on its own. If it doesn't, add the snippet by hand in Google Ads (Ads & assets, then Assets)."]
    lines += ["- Campaign and ad group names must match existing ones exactly. A new campaign or ad group you didn't "
              "expect in Editor's pending changes means a name didn't match: revert it before posting.", "",
              "## Steps", "",
              "1. Open Google Ads Editor, select the account, and click **Get recent changes**.",
              "2. Go to **Account > Import > From file...** and pick the first file above.",
              "3. In the preview, check every column header is recognized. Fix any from the drop-down.",
              "4. Finish the import. The rows become pending changes; nothing is live yet.",
              "5. Repeat for each file, in order.",
              "6. Review the pending changes, then click **Check changes** and fix anything Editor flags.",
              "7. Click **Post**, then reply in the chat so the changes can be checked and logged.", "",
              "## Undo", "",
              "- Before posting: revert any pending change in Editor.",
              "- After posting: pause the new ads. To stop a sitelink, callout, or snippet from showing, pause it in "
              "Google Ads under Assets. If pausing isn't offered for it, removing the link is the only undo: decide "
              "that yourself, because these skills never delete."]
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("copy")
    parser.add_argument("--context")
    parser.add_argument("--claims", action="append", default=[])
    parser.add_argument("--change-set")
    parser.add_argument("--editor-dir")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--utf8", action="store_true")
    parser.add_argument("--template")
    parser.add_argument("--today")
    args = parser.parse_args()
    if not args.change_set and not args.editor_dir:
        sys.exit("give --change-set, --editor-dir, or both")
    if args.editor_dir and not args.approved_by and not args.draft:
        sys.exit("Editor files need --approved-by NAME after the person approves the copy, or --draft for a preview")

    copy_path = Path(args.copy)
    copy = json.loads(copy_path.read_text(encoding="utf-8-sig"))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = {"items": [], "protected": [], "unwanted": [], "competitors": [], "competitors_allowed": False,
           "competitor_policy": "MISSING", "avoid": [], "use": [], "restricted": "", "path": None}
    if args.context and Path(args.context).exists():
        ctx = checker.parse_context(args.context)
    claim_items = [i for p in args.claims for i in checker.parse_claims_file(p)]
    result = checker.run(json.loads(copy_path.read_text(encoding="utf-8-sig")), ctx, claim_items, [], [], None,
                         copy_path.parent, today)
    errors = result["report"].level("error")
    if errors:
        print(f"Not built: check_ad_copy.py finds {len(errors)} error(s). Fix them and run it again:", file=sys.stderr)
        for e in errors[:15]:
            print(f"  [{e['where']}] {e['message']}", file=sys.stderr)
        return 1

    if args.change_set:
        batch = build_change_set(copy, args.copy)
        path = Path(args.change_set)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        counts = {}
        for c in batch["changes"]:
            counts[c["action"]] = counts.get(c["action"], 0) + 1
        print(f"wrote {path} ({len(batch['changes'])} changes: " +
              ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + "; unapproved)")
    if args.editor_dir:
        template = load_template(args.template) if args.template else {}
        written = build_editor(copy, Path(args.editor_dir), args.approved_by, args.utf8, template)
        for w in written:
            print(f"wrote {Path(args.editor_dir)}/{w.split('`')[1]}")
        print(f"wrote {Path(args.editor_dir) / 'manifest.md'}" + ("" if args.approved_by else " (DRAFT)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
