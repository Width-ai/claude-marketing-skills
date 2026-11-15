#!/usr/bin/env python3
"""Compute Google Ads metrics and comparisons in code, never by hand.

Works on CSVs written by normalize.py (standard column names). Ratios are
always recomputed from summed numerators and denominators, never averaged.

Commands:
  summary   Totals and ratios by any grouping, with optional break-even checks.
              metrics.py summary campaigns.csv --by campaign [--target-cpa 80] [--target-roas 4]
  compare   This period vs. a prior period, with direction words computed here.
              metrics.py compare current.csv prior.csv --by campaign
              metrics.py compare daily.csv --current 2026-11-01:2026-11-14 --prior 2026-10-18:2026-10-31 --by campaign
  coverage  How much of each campaign's traffic the search terms report discloses.
              metrics.py coverage --search-terms search_terms.csv --campaigns campaigns.csv
  zero-conv What zero conversions on N clicks can and can't rule out.
              metrics.py zero-conv --clicks 40 [--cpc 2.10 --target-cpa 80]

Add --markdown to print a Markdown table instead of CSV, and --out FILE to save.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import OrderedDict

ADDITIVE = ["impressions", "clicks", "interactions", "cost", "conversions", "conversion_value",
            "all_conversions", "all_conversions_value", "view_through_conversions"]

# name: (numerator, denominator, scale)
RATIOS = OrderedDict([
    ("ctr", ("clicks", "impressions")),
    ("cpc", ("cost", "clicks")),
    ("cvr", ("conversions", "clicks")),
    ("cpa", ("cost", "conversions")),
    ("roas", ("conversion_value", "cost")),
    ("value_per_conversion", ("conversion_value", "conversions")),
])

HIGHER_IS_BETTER = {"conversions", "conversion_value", "ctr", "cvr", "roas", "value_per_conversion",
                    "all_conversions", "all_conversions_value"}
LOWER_IS_BETTER = {"cpa", "cpc"}
FLAT_THRESHOLD = 0.005  # changes under 0.5% are reported as flat


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def num(value) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def div(a: float, b: float):
    return a / b if b else None


def aggregate(rows: list[dict], by: list[str]) -> "OrderedDict[tuple, dict]":
    present = [m for m in ADDITIVE if rows and m in rows[0]]
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for row in rows:
        key = tuple(row.get(k, "") for k in by)
        agg = groups.setdefault(key, {m: 0.0 for m in present})
        for m in present:
            agg[m] += num(row.get(m))
    for agg in groups.values():
        add_ratios(agg)
    return groups


def add_ratios(agg: dict) -> None:
    for name, (n, d) in RATIOS.items():
        if n in agg and d in agg:
            agg[name] = div(agg[n], agg[d])


def total_of(groups: "OrderedDict[tuple, dict]") -> dict:
    total: dict = {}
    for agg in groups.values():
        for k, v in agg.items():
            if k in ADDITIVE:
                total[k] = total.get(k, 0.0) + v
    add_ratios(total)
    return total


def zero_conv_upper(clicks: float, confidence: float = 0.95):
    """Highest conversion rate that zero conversions in `clicks` clicks fails to rule out."""
    if clicks <= 0:
        return None
    return 1 - (1 - confidence) ** (1 / clicks)


def fmt(value, name: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if name in ("ctr", "cvr", "pct_change", "breakeven_cvr", "cvr_upper_95", "disclosed_share") or name.endswith("_pct"):
        return f"{value:.4f}"
    if name in ("impressions", "clicks", "interactions"):
        return f"{value:.0f}"
    return f"{value:.2f}"


def emit(header: list[str], rows: list[list[str]], markdown: bool, out: str | None) -> None:
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        text = "\n".join(lines) + "\n"
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


def pct(value) -> str:
    return "" if value is None else f"{value * 100:.1f}%"


def cmd_summary(args) -> None:
    rows = read_csv(args.file)
    by = [b.strip() for b in args.by.split(",")] if args.by else []
    groups = aggregate(rows, by)
    metrics = [m for m in ADDITIVE if rows and m in rows[0]] + [r for r in RATIOS if rows and all(x in rows[0] for x in RATIOS[r])]
    extra = []
    if args.target_cpa:
        extra = ["breakeven_cvr", "cvr_upper_95", "verdict"]
    if args.target_roas:
        extra += ["roas_vs_target"]
    header = by + metrics + extra
    out_rows = []
    items = list(groups.items())
    if by and not args.no_total:
        items.append((tuple(["TOTAL"] + [""] * (len(by) - 1)), total_of(groups)))
    for key, agg in items:
        line = list(key) + [fmt(agg.get(m), m) for m in metrics]
        if args.target_cpa:
            cpc = agg.get("cpc")
            breakeven = div(cpc, args.target_cpa) if cpc is not None else None
            upper = None
            if agg.get("conversions", 0) == 0:
                upper = zero_conv_upper(agg.get("clicks", 0))
                if upper is None or breakeven is None:
                    verdict = "no clicks"
                elif upper < breakeven:
                    verdict = "underperforming (data rules out break-even CVR)"
                else:
                    verdict = "not enough data"
            else:
                cpa = agg.get("cpa")
                verdict = "within target" if cpa is not None and cpa <= args.target_cpa else "above target CPA"
            line += [fmt(breakeven, "breakeven_cvr"), fmt(upper, "cvr_upper_95"), verdict]
        if args.target_roas:
            roas = agg.get("roas")
            line += ["" if roas is None else ("at or above target" if roas >= args.target_roas else "below target")]
        out_rows.append(line)
    emit(header, out_rows, args.markdown, args.out)


def split_by_dates(rows: list[dict], window: str) -> list[dict]:
    start, _, end = window.partition(":")
    if "date" not in (rows[0] if rows else {}):
        sys.exit("--current/--prior need a 'date' column (YYYY-MM-DD)")
    return [r for r in rows if start <= r.get("date", "") <= end]


def direction(name: str, current, prior) -> tuple[str, str]:
    if current is None or prior is None:
        return "", "n/a"
    if prior == 0:
        if current == 0:
            return "", "flat"
        return "", "up from zero"
    change = (current - prior) / abs(prior)
    word = "flat" if abs(change) < FLAT_THRESHOLD else ("up" if change > 0 else "down")
    return fmt(change, "pct_change"), word


def judgement(name: str, word: str) -> str:
    if word not in ("up", "down", "up from zero"):
        return ""
    up = word.startswith("up")
    if name in HIGHER_IS_BETTER:
        return "better" if up else "worse"
    if name in LOWER_IS_BETTER:
        return "worse" if up else "better"
    return ""


def cmd_compare(args) -> None:
    if args.current and args.prior:
        rows = read_csv(args.files[0])
        current_rows, prior_rows = split_by_dates(rows, args.current), split_by_dates(rows, args.prior)
    elif len(args.files) == 2:
        current_rows, prior_rows = read_csv(args.files[0]), read_csv(args.files[1])
    else:
        sys.exit("give two files (current prior) or one file with --current and --prior date windows")
    by = [b.strip() for b in args.by.split(",")] if args.by else []
    cur, pri = aggregate(current_rows, by), aggregate(prior_rows, by)
    keys = list(cur.keys()) + [k for k in pri.keys() if k not in cur]
    sample = current_rows[0] if current_rows else (prior_rows[0] if prior_rows else {})
    metrics = args.metrics.split(",") if args.metrics else (
        [m for m in ("cost", "impressions", "clicks", "conversions", "conversion_value") if m in sample]
        + [r for r in RATIOS if all(x in sample for x in RATIOS[r])])
    header = by + ["metric", "current", "prior", "change", "pct_change", "direction", "judgement"]
    out_rows = []
    items = [(k, cur.get(k, {}), pri.get(k, {})) for k in keys]
    if by and not args.no_total:
        items.append((tuple(["TOTAL"] + [""] * (len(by) - 1)), total_of(cur), total_of(pri)))
    for key, c, p in items:
        if not c:
            note = "only in prior period"
        elif not p:
            note = "only in current period"
        else:
            note = ""
        for m in metrics:
            cv, pv = c.get(m), p.get(m)
            change = None if cv is None or pv is None else cv - pv
            pct_change, word = direction(m, cv, pv)
            if note and word == "n/a":
                word = note
            out_rows.append(list(key) + [m, fmt(cv, m), fmt(pv, m), fmt(change, m), pct_change, word, judgement(m, word)])
    emit(header, out_rows, args.markdown, args.out)


def cmd_coverage(args) -> None:
    terms, camps = read_csv(args.search_terms), read_csv(args.campaigns)
    key = "campaign_id" if terms and camps and "campaign_id" in terms[0] and "campaign_id" in camps[0] else "campaign"
    disclosed = aggregate(terms, [key])
    total = aggregate(camps, [key])
    header = [key, "total_clicks", "disclosed_clicks", "withheld_clicks", "disclosed_share", "total_cost", "disclosed_cost"]
    out_rows = []
    for k, agg in total.items():
        d = disclosed.get(k, {})
        tc, dc = agg.get("clicks", 0.0), d.get("clicks", 0.0)
        out_rows.append([k[0], fmt(tc, "clicks"), fmt(dc, "clicks"), fmt(max(tc - dc, 0), "clicks"),
                         fmt(div(dc, tc), "disclosed_share"), fmt(agg.get("cost")), fmt(d.get("cost"))])
    missing = [k[0] for k in disclosed if k not in total]
    emit(header, out_rows, args.markdown, args.out)
    if missing:
        print(f"note: search terms for campaigns not in the campaigns file: {', '.join(missing)}", file=sys.stderr)


def cmd_zero_conv(args) -> None:
    upper = zero_conv_upper(args.clicks)
    print(f"clicks: {args.clicks:.0f}, conversions: 0")
    print(f"95% upper bound on conversion rate: {pct(upper)} (rates at or above this are ruled out)")
    if args.cpc and args.target_cpa:
        breakeven = args.cpc / args.target_cpa
        print(f"break-even conversion rate (CPC / target CPA): {pct(breakeven)}")
        if upper is not None and upper < breakeven:
            print("verdict: underperforming. The data rules out converting at break-even.")
        else:
            needed = None
            if breakeven > 0:
                import math
                needed = math.ceil(math.log(0.05) / math.log(1 - breakeven)) if breakeven < 1 else 1
            print("verdict: not enough data to call it.")
            if needed:
                print(f"clicks needed with zero conversions to rule out break-even: {needed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summary")
    s.add_argument("file")
    s.add_argument("--by", default="")
    s.add_argument("--target-cpa", type=float)
    s.add_argument("--target-roas", type=float)
    s.add_argument("--no-total", action="store_true")

    c = sub.add_parser("compare")
    c.add_argument("files", nargs="+")
    c.add_argument("--by", default="")
    c.add_argument("--current", help="START:END for one-file mode")
    c.add_argument("--prior", help="START:END for one-file mode")
    c.add_argument("--metrics", help="comma-separated metrics to compare")
    c.add_argument("--no-total", action="store_true")

    v = sub.add_parser("coverage")
    v.add_argument("--search-terms", required=True)
    v.add_argument("--campaigns", required=True)

    z = sub.add_parser("zero-conv")
    z.add_argument("--clicks", type=float, required=True)
    z.add_argument("--cpc", type=float)
    z.add_argument("--target-cpa", type=float)

    for p in (s, c, v):
        p.add_argument("--markdown", action="store_true")
        p.add_argument("--out")

    args = parser.parse_args()
    {"summary": cmd_summary, "compare": cmd_compare, "coverage": cmd_coverage, "zero-conv": cmd_zero_conv}[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
