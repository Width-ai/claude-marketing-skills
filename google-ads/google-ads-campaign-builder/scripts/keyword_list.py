#!/usr/bin/env python3
"""Clean a keyword candidate list for a new Google Ads Search campaign.

Reads any mix of:
  - plain text files, one keyword per line
  - CSV or TSV files with a "keyword" column (UTF-8 or UTF-16)
  - Keyword Planner exports from the Google Ads interface (UTF-16, tab-separated,
    with title lines above the header), or a keyword tool's CSV output

Writes one row per unique keyword with:
  keyword, words, chars, avg_monthly_searches (exactly as reported, or MISSING),
  competition, top_of_page_bid_low, top_of_page_bid_high, currency, theme,
  sources, flags, duplicate_of

Search volumes are copied as reported, never estimated. Keyword Planner ranges
such as "1K - 10K" stay ranges. A keyword with no reported volume gets MISSING.

Flags:
  too_long          over 80 characters (Google's keyword limit)
  too_many_words    over 10 words
  symbols           characters Google rejects in keywords
  bmm               a "+" prefix (broad match modifier, retired)
  unwanted:<term>   contains a term from --exclude (for example the context
                    file's "Terms we don't want")
  competitor:<name> contains a name from --competitors
  no_service_word   contains none of the --require words
  word_order_dup    same words as another keyword in a different order
                    (Google treats these as duplicates)

Usage:
  python3 keyword_list.py FILE [FILE ...] --out keywords.csv
      [--exclude "jobs,careers,diy,water heater rental"]
      [--competitors "Bluewater Plumbing,Capital City Plumbers"]
      [--require "water heater,tankless"]
      [--themes "Installation=install,installation,new;Repair=repair,fix"]

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 80, 10
REJECTED_SYMBOLS = set("!@%^*=;~`<>?\\|{},")
HEADER_ALIASES = {
    "keyword": ["keyword", "keywords", "keyword text", "search term", "query", "text"],
    "volume": ["avg. monthly searches", "avg monthly searches", "average monthly searches", "search volume",
               "volume", "avg_monthly_searches"],
    "competition": ["competition"],
    "bid_low": ["top of page bid (low range)", "top_of_page_bid_low", "low top of page bid"],
    "bid_high": ["top of page bid (high range)", "top_of_page_bid_high", "high top of page bid"],
    "currency": ["currency"],
}
DASHES = "\u2013\u2014\u2012\u2212"  # en dash, em dash, figure dash, minus sign


def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def clean_value(value: str) -> str:
    v = (value or "").strip()
    if not v or all(ch in DASHES + "-" for ch in v):
        return ""
    for d in DASHES:
        v = v.replace(f" {d} ", " to ").replace(d, " to ")
    return re.sub(r"\s+", " ", v)


def normalize(text: str) -> tuple[str, list[str]]:
    """Lower-case, collapse spaces, strip match-type punctuation. Returns (keyword, flags)."""
    flags = []
    t = (text or "").strip()
    if t.startswith("-"):
        t = t[1:]
    t = t.strip().strip('[]"').strip()
    if t.startswith("+") or " +" in t:
        flags.append("bmm")
        t = t.replace("+", "")
    t = re.sub(r"\s+", " ", t).lower().strip()
    return t, flags


def read_file(path: str) -> list[dict]:
    text = decode(Path(path).read_bytes())
    lines = text.splitlines()
    header_at = None
    for i, line in enumerate(lines[:30]):
        cells = [c.strip().strip('"').lower() for c in re.split(r"[\t,]", line)]
        if cells and cells[0] in HEADER_ALIASES["keyword"] and len(cells) > 1:
            header_at = i
            break
    if header_at is None:  # plain list
        return [{"keyword": line} for line in lines if line.strip() and not line.lstrip().startswith("#")]
    header_line = lines[header_at]
    delimiter = "\t" if header_line.count("\t") >= header_line.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_at:])), delimiter=delimiter)
    out = []
    for row in reader:
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        item = {}
        for key, aliases in HEADER_ALIASES.items():
            item[key] = next((low[a] for a in aliases if low.get(a)), "")
        if item["keyword"]:
            out.append(item)
    return out


def contains(keyword: str, term: str) -> bool:
    term = term.strip().lower()
    return bool(term) and re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", keyword) is not None


def parse_themes(value: str) -> list[tuple[str, list[str]]]:
    themes = []
    for part in (value or "").split(";"):
        if "=" in part:
            name, terms = part.split("=", 1)
            themes.append((name.strip(), [t.strip().lower() for t in terms.split(",") if t.strip()]))
    return themes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--exclude", default="")
    parser.add_argument("--competitors", default="")
    parser.add_argument("--require", default="")
    parser.add_argument("--themes", default="")
    args = parser.parse_args()

    exclude = [t.strip().lower() for t in re.split(r"[,;\n]", args.exclude) if t.strip()]
    competitors = [t.strip().lower() for t in re.split(r"[,;\n]", args.competitors) if t.strip()]
    require = [t.strip().lower() for t in re.split(r"[,;\n]", args.require) if t.strip()]
    themes = parse_themes(args.themes)

    merged: dict[str, dict] = {}
    read = 0
    for path in args.files:
        for item in read_file(path):
            read += 1
            kw, flags = normalize(item["keyword"])
            if not kw:
                continue
            row = merged.setdefault(kw, {"keyword": kw, "avg_monthly_searches": "", "competition": "",
                                         "top_of_page_bid_low": "", "top_of_page_bid_high": "", "currency": "",
                                         "sources": [], "flags": set()})
            row["flags"].update(flags)
            name = Path(path).name
            if name not in row["sources"]:
                row["sources"].append(name)
            for src, dst in (("volume", "avg_monthly_searches"), ("competition", "competition"),
                             ("bid_low", "top_of_page_bid_low"), ("bid_high", "top_of_page_bid_high"),
                             ("currency", "currency")):
                value = clean_value(item.get(src, ""))
                if value and not row[dst]:
                    row[dst] = value

    order: dict[tuple, str] = {}
    for kw, row in merged.items():
        words = kw.split()
        if len(kw) > KEYWORD_MAX_CHARS:
            row["flags"].add("too_long")
        if len(words) > KEYWORD_MAX_WORDS:
            row["flags"].add("too_many_words")
        if set(kw) & REJECTED_SYMBOLS:
            row["flags"].add("symbols")
        for term in exclude:
            if contains(kw, term):
                row["flags"].add(f"unwanted:{term}")
        for name in competitors:
            if contains(kw, name):
                row["flags"].add(f"competitor:{name}")
        if require and not any(contains(kw, t) for t in require):
            row["flags"].add("no_service_word")
        key = tuple(sorted(words))
        row["duplicate_of"] = ""
        if key in order:
            row["flags"].add("word_order_dup")
            row["duplicate_of"] = order[key]
        else:
            order[key] = kw
        row["theme"] = next((name for name, terms in themes if any(contains(kw, t) for t in terms)),
                            "unassigned" if themes else "")

    columns = ["keyword", "words", "chars", "avg_monthly_searches", "competition", "top_of_page_bid_low",
               "top_of_page_bid_high", "currency", "theme", "sources", "flags", "duplicate_of"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for kw, row in sorted(merged.items(), key=lambda kv: (bool(kv[1]["flags"]), kv[1].get("theme", ""), kv[0])):
            writer.writerow([kw, len(kw.split()), len(kw), row["avg_monthly_searches"] or "MISSING", row["competition"],
                             row["top_of_page_bid_low"], row["top_of_page_bid_high"], row["currency"], row["theme"],
                             "; ".join(row["sources"]), "; ".join(sorted(row["flags"])), row["duplicate_of"]])

    flagged = sum(1 for r in merged.values() if r["flags"])
    with_volume = sum(1 for r in merged.values() if r["avg_monthly_searches"])
    print(f"read {read} rows from {len(args.files)} file(s); {len(merged)} unique keywords")
    print(f"{with_volume} with a reported search volume, {len(merged) - with_volume} MISSING")
    print(f"{flagged} flagged, {len(merged) - flagged} clean")
    counts: dict[str, int] = {}
    for r in merged.values():
        for f in r["flags"]:
            counts[f.split(":")[0]] = counts.get(f.split(":")[0], 0) + 1
    for f, n in sorted(counts.items()):
        print(f"  {f}: {n}")
    if themes:
        tally: dict[str, int] = {}
        for r in merged.values():
            if not r["flags"]:
                tally[r["theme"]] = tally.get(r["theme"], 0) + 1
        print("clean keywords by theme: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
