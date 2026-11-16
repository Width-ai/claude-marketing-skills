"""Review how each headline in one live responsive search ad performs, and
compare the headlines with competitor ads and the searches that convert.

For each headline: impressions, serving share, CTR, conversions, and
conversions per impression, with 95% ranges, compared with the ad's other
unpinned headlines. Each headline gets a verdict:

  pinned         shows in a fixed spot, so it isn't compared with the rest
  too early      the ad hasn't had enough impressions, or Google says it's learning
  replace        Google rarely shows it and it has no conversions, or its CTR
                 or conversions per impression are clearly below the others
  keep           clearly above the others on clicks or conversions
  keep for now   no clear difference

"Clearly" means the headline's 95% range doesn't include the rate of the ad's
other unpinned headlines. Headlines serve in combinations, and Google shows
the ones it expects to win more often, so a verdict is a reason to test a
replacement, not proof that a line is bad.

It also reports:
  - near duplicates among the headlines
  - a rough theme for each headline (keyword, offer, price, free, proof,
    guarantee, speed, call to action, brand), found by word match, and which
    themes the lines you'd keep don't cover
  - converting search terms and keywords whose words no headline uses
  - with competitor headlines: which of your headlines sound like a
    competitor's, claim types and phrases competitors use that you don't,
    and phrases only you use

Usage:
  python3 analyze_headlines.py --assets FILE [FILE ...]
      [--ad FILE]                the ad: its headlines, pins, and totals (connector JSON or CSV)
      [--ad-id ID]               which ad, when the files hold more than one
      [--search-terms FILE] [--keywords FILE]
      [--competitors FILE]       competitor headlines (CSV, JSON, or text)
      [--context .agents/google-ads-context.md]
      [--start YYYY-MM-DD] [--end YYYY-MM-DD]
      [--max-replace 3] [--markdown REPORT.md] [--json]

Exit code 2 when the files hold more than one ad and --ad-id wasn't given, or
when no headline data was found.

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- thresholds

MIN_AD_IMPRESSIONS = 2000     # below this, the whole ad is too early to judge
MIN_LINE_IMPRESSIONS = 200    # a headline needs this many before its rates are compared
LOW_SERVING_SHARE = 0.10      # rsa-ad-copy-writer: under 10% of the most-served headline, no conversions
MAX_REPLACE = 3               # replacements per round; fewer changes keep the test readable
NEAR_DUPLICATE = 0.6          # word overlap that counts as a near duplicate
SOUNDS_LIKE = 0.5             # word overlap that counts as sounding like a competitor
FULL_ASSET_STATS_FROM = dt.date(2025, 6, 5)   # Google: full asset-level stats from this date
TOP_TERMS = 15
Z = 1.96

STOPWORDS = set("""a an the and or for to of in on at by with from your you our we us my me it its is are be
been was were this that these those as if than then so not no all any more most very just near here there
what which who how when where why get""".split())
CTA_VERBS = set("""book call schedule start try request shop buy order sign join contact download compare find
claim see learn discover explore talk chat visit reserve grab hire speak apply enroll register subscribe
browse view check upgrade switch save""".split())
THEME_RES = {
    "price": re.compile(r"[$£€]\s?\d|\b\d+(?:\.\d+)?\s?(?:dollars?|usd|eur|gbp)\b|\bfrom \$|\bper month\b|/mo\b", re.I),
    "offer": re.compile(r"\d+\s?%|\b(?:sale|deal|deals|discount|discounts|coupon|promo|rebate|bonus|off)\b|\bsave\b", re.I),
    "free": re.compile(r"\bfree\b|\bno[- ]cost\b|\bcomplimentary\b|\bno charge\b", re.I),
    "proof": re.compile(r"\brated\b|\bstars?\b|\breviews?\b|\baward|\bsince (?:19|20)\d\d\b|\b\d+\+?\s?(?:years?|yrs)\b|"
                        r"\blicensed\b|\binsured\b|\bcertified\b|\baccredited\b|\btrusted\b|\bcustomers\b|\bclients\b|"
                        r"#1\b|\bbbb\b|\bvoted\b|\bfeatured\b|\bfamily[- ]owned\b|\blocal(?:ly)? owned\b", re.I),
    "guarantee": re.compile(r"\bguarantee|\bwarrant|\bmoney[- ]back\b|\brefund|\brisk[- ]free\b|\bprice match", re.I),
    "speed": re.compile(r"\bsame[- ]day\b|\b24\s?/\s?7\b|\b24[- ]hours?\b|\btoday\b|\btonight\b|\bfast\b|\bquick|"
                        r"\bminutes?\b|\bin \d+ (?:hours?|days?)\b|\bnext[- ]day\b|\bovernight\b|\bemergency\b|\bnow\b", re.I),
}
THEME_ORDER = ["brand", "keyword", "offer", "price", "free", "proof", "guarantee", "speed", "cta", "benefit"]
THEME_NAMES = {"cta": "call to action"}
CLAIM_TYPES = ["offer", "price", "free", "proof", "guarantee", "speed", "cta"]

COLS = {
    "text": ["asset.text_asset.text", "asset", "asset text", "headline/description", "text"],
    "field": ["ad_group_ad_asset_view.field_type", "asset type", "field type", "asset field type", "type"],
    "pinned": ["ad_group_ad_asset_view.pinned_field", "pinned field", "pinned position", "pinned", "pin", "position"],
    "label": ["ad_group_ad_asset_view.performance_label", "performance label", "performance"],
    "enabled": ["ad_group_ad_asset_view.enabled", "enabled", "asset status", "status"],
    "ad_id": ["ad_group_ad.ad.id", "ad id", "ad_id"],
    "campaign": ["campaign.name", "campaign"],
    "ad_group": ["ad_group.name", "ad group", "ad_group"],
    "ad_status": ["ad_group_ad.status", "ad status", "ad state", "status"],
    "impressions": ["metrics.impressions", "impr.", "impressions", "impr"],
    "clicks": ["metrics.clicks", "clicks"],
    "conversions": ["metrics.conversions", "conversions", "conv."],
    "term": ["search_term_view.search_term", "search term", "search_term", "ad_group_criterion.keyword.text",
             "keyword", "search keyword", "query"],
    "competitor": ["competitor", "advertiser", "domain", "brand", "name", "display url"],
    "headline": ["headline", "text", "ad text", "copy", "line"],
    "kind": ["kind", "field", "type", "asset type"],
    "source": ["source", "where"],
}


# ---------------------------------------------------------------- reading files

def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    if raw[:200].count(b"\x00") > 20:
        return raw.decode("utf-16-le")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def snake(key: str) -> str:
    return ".".join(re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", part).lower() for part in str(key).split("."))


def flatten(obj, prefix: str = "") -> dict:
    out = {}
    for key, value in obj.items():
        path = f"{prefix}.{snake(key)}" if prefix else snake(key)
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def num(value) -> float | None:
    if value in (None, "", "--", " --"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else None
    except ValueError:
        return None


def read_rows(path: str, header_hint: list[str]) -> list[dict]:
    """Rows as dicts with lowercased keys, from connector JSON or a CSV/TSV export with title rows."""
    text = decode(Path(path).read_bytes())
    if text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((data[k] for k in ("results", "rows", "data", "ads", "headlines", "competitors")
                         if isinstance(data.get(k), list)), [data])
        return [{k.lower(): v for k, v in flatten(r).items()} if isinstance(r, dict) else {"text": r} for r in data]
    lines = text.splitlines()
    sample = "\n".join(lines[:20])
    delim = max((",", "\t", ";"), key=sample.count)
    table = list(csv.reader(io.StringIO(text), delimiter=delim))
    hints = {h.lower() for h in header_hint}
    start = 0
    for i, r in enumerate(table[:15]):
        cells = {c.strip().lower() for c in r}
        if cells & hints or any(c.startswith("headline 1") for c in cells):
            start = i
            break
    if not table:
        return []
    header = [h.strip().lower() for h in table[start]]
    rows = []
    for r in table[start + 1:]:
        if not any(c.strip() for c in r):
            continue
        if any(c.strip().lower().startswith("total") for c in r[:3]):
            continue
        rows.append({header[i]: (r[i] if i < len(r) else "") for i in range(len(header))})
    return rows


def pick(row: dict, key: str):
    for name in COLS[key]:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def pin_of(value) -> str:
    """'1', '2', '3' for a pinned headline position, 'D1'/'D2' for descriptions, '' when not pinned."""
    v = str(value or "").strip().lower()
    if not v or v in ("--", "unspecified", "unknown", "none", "not pinned", "0"):
        return ""
    m = re.search(r"(\d)", v)
    if not m:
        return ""
    return ("D" if "description" in v else "") + m.group(1)


def field_of(value) -> str:
    v = str(value or "").strip().lower()
    if v.startswith("headline"):
        return "headline"
    if v.startswith("description"):
        return "description"
    return v


def text_list(value) -> list[tuple[str, str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [(value.strip(), "")] if value.strip() else []
    out = []
    for v in value or []:
        if isinstance(v, dict):
            out.append((str(v.get("text", "")).strip(), pin_of(v.get("pinned_field") or v.get("pinnedField"))))
        elif str(v).strip():
            out.append((str(v).strip(), ""))
    return out


def load_ads(paths: list[str]) -> list[dict]:
    """The ad itself: headlines with pins, descriptions, paths, URL, and totals."""
    ads = []
    for path in paths:
        for row in read_rows(path, ["ad id", "headline 1", "ad_group_ad.ad.id", "impr."]):
            ad = {"id": str(pick(row, "ad_id") or "").strip(), "campaign": str(pick(row, "campaign") or ""),
                  "ad_group": str(pick(row, "ad_group") or ""), "status": str(pick(row, "ad_status") or "").lower(),
                  "impressions": num(pick(row, "impressions")), "clicks": num(pick(row, "clicks")),
                  "conversions": num(pick(row, "conversions")), "headlines": [], "descriptions": [],
                  "path1": "", "path2": "", "final_url": ""}
            for key, value in row.items():
                if key.endswith("responsive_search_ad.headlines"):
                    ad["headlines"] += text_list(value)
                elif key.endswith("responsive_search_ad.descriptions"):
                    ad["descriptions"] += text_list(value)
                elif key.endswith("responsive_search_ad.path1") or key == "path 1":
                    ad["path1"] = str(value or "")
                elif key.endswith("responsive_search_ad.path2") or key == "path 2":
                    ad["path2"] = str(value or "")
                elif key.endswith("ad.final_urls") or key in ("final url", "final urls"):
                    urls = text_list(value) if not isinstance(value, str) or value.strip().startswith("[") else [(value, "")]
                    ad["final_url"] = urls[0][0] if urls else ""
            for i in range(1, 16):
                t = str(row.get(f"headline {i}") or "").strip()
                if t and t != "--":
                    ad["headlines"].append((t, pin_of(row.get(f"headline {i} position") or row.get(f"headline {i} pinned"))))
            for i in range(1, 5):
                t = str(row.get(f"description {i}") or "").strip()
                if t and t != "--":
                    ad["descriptions"].append((t, pin_of(row.get(f"description {i} position"))))
            if ad["headlines"] or ad["impressions"] is not None:
                ads.append(ad)
    return ads


def load_assets(paths: list[str]) -> tuple[list[dict], int]:
    rows_out, removed = [], 0
    for path in paths:
        for row in read_rows(path, ["asset", "asset.text_asset.text", "asset type"]):
            text = str(pick(row, "text") or "").strip()
            field = field_of(pick(row, "field") or "headline")
            if not text or field not in ("headline", "description"):
                continue
            enabled = row.get("ad_group_ad_asset_view.enabled", row.get("enabled"))
            enabled = "" if enabled is None else str(enabled).strip().lower()
            status = str(row.get("asset status", row.get("status", "")) or "").strip().lower()
            if enabled in ("false", "0") or status in ("removed", "deleted"):
                removed += 1
                continue
            rows_out.append({
                "text": text, "field": field, "pin": pin_of(pick(row, "pinned")),
                "label": str(pick(row, "label") or "").strip().lower(),
                "ad_id": str(pick(row, "ad_id") or "").strip(), "campaign": str(pick(row, "campaign") or ""),
                "ad_group": str(pick(row, "ad_group") or ""),
                "impressions": num(pick(row, "impressions")) or 0.0, "clicks": num(pick(row, "clicks")) or 0.0,
                "conversions": num(pick(row, "conversions")) or 0.0,
            })
    return rows_out, removed


def load_terms(path: str, ad_group: str) -> list[dict]:
    sums: dict = {}
    for row in read_rows(path, COLS["term"]):
        term = str(pick(row, "term") or "").strip()
        if not term:
            continue
        group = str(pick(row, "ad_group") or "")
        if ad_group and group and group.strip().lower() != ad_group.strip().lower():
            continue
        t = sums.setdefault(term.lower(), {"term": term, "impressions": 0.0, "clicks": 0.0, "conversions": 0.0})
        for m in ("impressions", "clicks", "conversions"):
            t[m] += num(pick(row, m)) or 0.0
    return sorted(sums.values(), key=lambda t: (-t["conversions"], -t["clicks"], -t["impressions"]))


def load_competitors(path: str) -> list[dict]:
    """Competitor lines: {competitor, text, kind}. CSV/JSON with competitor and headline columns, or text lines."""
    raw = decode(Path(path).read_bytes())
    out = []
    if raw.lstrip().startswith(("[", "{")):
        data = json.loads(raw)
        groups = data.get("competitors") if isinstance(data, dict) else data
        if isinstance(data, dict) and groups is None:
            groups = [data]
        for g in groups or []:
            if isinstance(g, str):
                out.append({"competitor": "unknown", "text": g, "kind": "headline"})
                continue
            name = str(g.get("competitor") or g.get("name") or g.get("advertiser") or g.get("domain") or "unknown")
            if g.get("headline") or g.get("text"):
                kind = field_of(g.get("kind") or g.get("field") or "headline") or "headline"
                out.append({"competitor": name, "text": str(g.get("headline") or g.get("text")), "kind": kind})
            for h in g.get("headlines") or []:
                out.append({"competitor": name, "text": str(h), "kind": "headline"})
            for d in g.get("descriptions") or []:
                out.append({"competitor": name, "text": str(d), "kind": "description"})
        return [o for o in out if o["text"].strip()]
    first = next((ln for ln in raw.splitlines() if ln.strip()), "")
    if "," in first and any(h in first.lower() for h in ("headline", "competitor", "advertiser")):
        for row in read_rows(path, COLS["competitor"] + COLS["headline"]):
            text = str(pick(row, "headline") or "").strip()
            if text:
                kind = field_of(pick(row, "kind") or "headline")
                out.append({"competitor": str(pick(row, "competitor") or "unknown").strip(), "text": text,
                            "kind": kind if kind in ("headline", "description") else "headline"})
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in re.split(r"\t|\s\|\s", line, maxsplit=2)]
        if len(parts) == 1:
            out.append({"competitor": "unknown", "text": parts[0], "kind": "headline"})
        elif len(parts) == 2:
            out.append({"competitor": parts[0], "text": parts[1], "kind": "headline"})
        else:
            kind = field_of(parts[1])
            if kind in ("headline", "description"):
                out.append({"competitor": parts[0], "text": parts[2], "kind": kind})
            else:
                out.append({"competitor": parts[0], "text": " | ".join(parts[1:]), "kind": "headline"})
    return out


def read_sections(text: str) -> dict:
    sections, name, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if name:
                sections[name] = "\n".join(buf)
            name, buf = m.group(1).strip().lower(), []
        elif name:
            buf.append(line)
    if name:
        sections[name] = "\n".join(buf)
    return sections


def skip_value(v: str) -> bool:
    v = v.strip().lower()
    return not v or v.startswith("[") or v in ("missing", "not applicable", "none", "n/a")


def load_context(path: str) -> dict:
    ctx = {"protected": [], "competitors": [], "competitor_policy": "MISSING"}
    sections = read_sections(Path(path).read_text(encoding="utf-8-sig"))
    for line in sections.get("protected terms", "").splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
        if m and not skip_value(m.group(1)):
            ctx["protected"].append(m.group(1))
    in_list = False
    for line in sections.get("competitor policy", "").splitlines():
        m = re.match(r"^(\s*)[-*]\s+(.+?)\s*$", line)
        if not m:
            continue
        indent, body = len(m.group(1)), m.group(2)
        if indent and in_list:
            if not skip_value(body):
                ctx["competitors"].append(re.split(r"\s[(:]", body)[0].strip())
            continue
        in_list = False
        label, _, value = body.partition(":")
        label = label.lower()
        if "name competitors" in label:
            ctx["competitor_policy"] = value.strip() or "MISSING"
        elif "main competitors" in label:
            in_list = True
            ctx["competitors"] += [p.strip() for p in re.split(r"[,;]", value) if not skip_value(p)]
    return ctx


# ---------------------------------------------------------------- words and themes

def words(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9$%#]+(?:[-'/.][a-z0-9]+)*", str(text).lower())
    out = []
    for t in toks:
        t = t.replace("'", "")
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def content(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS]


def overlap(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def phrase_in(phrase: str, text: str) -> bool:
    p = re.escape(phrase.strip().lower())
    return bool(p) and re.search(rf"(?<![a-z0-9]){p}(?![a-z0-9])", text.lower()) is not None


def name_in(name: str, text: str) -> bool:
    """A name's words, in order, inside the text, ignoring punctuation: 'Roto-Rooter' finds 'roto rooter'."""
    base = re.sub(r"\.(com|net|org|co|io|ai|us|ca|uk)$", "", name.strip().lower())
    n = re.findall(r"[a-z0-9]+", base)
    t = re.findall(r"[a-z0-9]+", text.lower())
    if not n:
        return False
    joined = "".join(n)
    return any(t[i:i + len(n)] == n for i in range(len(t) - len(n) + 1)) or joined in t


def themes(text: str, terms: list[str], brand: list[str]) -> list[str]:
    tags = []
    if any(phrase_in(b, text) for b in brand):
        tags.append("brand")
    toks = content(text)
    cset, pairs = set(toks), set(zip(toks, toks[1:]))
    for t in terms:
        tt = content(t)
        if (tt and set(tt) <= cset) or pairs & set(zip(tt, tt[1:])):
            tags.append("keyword")
            break
    for name, rx in THEME_RES.items():
        if rx.search(text):
            tags.append(name)
    first = words(text)[:1]
    if first and first[0] in CTA_VERBS:
        tags.append("cta")
    if not tags:
        tags.append("benefit")
    return [t for t in THEME_ORDER if t in tags]


def theme_label(t: str) -> str:
    return THEME_NAMES.get(t, t)


# ---------------------------------------------------------------- statistics

def wilson(k: float, n: float) -> tuple[float, float] | tuple[None, None]:
    if not n:
        return None, None
    k = min(max(k, 0.0), n)
    p = k / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def signal(k: float, n: float, base: float | None) -> str:
    lo, hi = wilson(k, n)
    if lo is None or base is None:
        return "unknown"
    if lo > base:
        return "higher"
    if hi < base:
        return "lower"
    return "same"


# ---------------------------------------------------------------- the review

def choose_ad(ads: list[dict], assets: list[dict], ad_id: str | None) -> tuple[str | None, list[str]]:
    ids = {a["id"] for a in ads if a["id"]} | {r["ad_id"] for r in assets if r["ad_id"]}
    if ad_id:
        return ad_id.strip(), []
    if len(ids) > 1:
        return None, sorted(ids)
    return (next(iter(ids)) if ids else None), []


def review(args) -> dict:
    notes = []
    ads = load_ads([args.ad]) if args.ad else []
    assets, removed = load_assets(args.assets)
    ad_id, choices = choose_ad(ads, assets, args.ad_id)
    if choices:
        listing = []
        for i in choices:
            ad = next((a for a in ads if a["id"] == i), None)
            impr = ad["impressions"] if ad and ad["impressions"] is not None else \
                max([r["impressions"] for r in assets if r["ad_id"] == i] or [0])
            group = ad["ad_group"] if ad else next((r["ad_group"] for r in assets if r["ad_id"] == i), "")
            listing.append({"ad_id": i, "ad_group": group, "impressions": impr})
        return {"error": "more than one ad in the files; pick one with --ad-id", "ads": listing}
    if ad_id:
        ads = [a for a in ads if not a["id"] or a["id"] == ad_id]
        assets = [r for r in assets if not r["ad_id"] or r["ad_id"] == ad_id]
    ad = ads[0] if ads else None
    if removed:
        notes.append(f"{removed} row(s) for lines no longer in the ad were left out")

    # Sum the asset rows by line (rows may be one per day).
    lines: dict = {}
    for r in assets:
        key = (r["field"], r["text"].lower())
        line = lines.setdefault(key, {"field": r["field"], "text": r["text"], "pin": r["pin"], "label": r["label"],
                                      "impressions": 0.0, "clicks": 0.0, "conversions": 0.0, "in_data": True})
        for m in ("impressions", "clicks", "conversions"):
            line[m] += r[m]
        line["label"] = line["label"] or r["label"]
        line["pin"] = line["pin"] or r["pin"]
    if ad and ad["headlines"]:
        current = {t.lower() for t, _ in ad["headlines"]}
        for (field, low), line in list(lines.items()):
            if field == "headline" and low not in current:
                notes.append(f"'{line['text']}' has data but isn't in the ad now; left out")
                del lines[(field, low)]
        for t, p in ad["headlines"]:
            line = lines.setdefault(("headline", t.lower()), {"field": "headline", "text": t, "pin": p, "label": "",
                                                              "impressions": 0.0, "clicks": 0.0, "conversions": 0.0,
                                                              "in_data": False})
            line["pin"] = p
            line["text"] = t
    heads = [l for l in lines.values() if l["field"] == "headline"]
    if ad and ad["headlines"]:
        order = {t.lower(): i for i, (t, _) in enumerate(ad["headlines"])}
        heads.sort(key=lambda l: order.get(l["text"].lower(), 99))
    else:
        heads.sort(key=lambda l: -l["impressions"])
    if not heads:
        return {"error": "no headline rows found in the asset files"}

    brand = []
    competitor_names = []
    if args.context:
        if Path(args.context).exists():
            ctx = load_context(args.context)
            brand = ctx["protected"]
            competitor_names = ctx["competitors"]
        else:
            notes.append(f"context file not found: {args.context}")
    terms = []
    for path, kind in ((args.search_terms, "search term"), (args.keywords, "keyword")):
        if path:
            for t in load_terms(path, ad["ad_group"] if ad else ""):
                t["kind"] = kind
                terms.append(t)
    top_terms = sorted(terms, key=lambda t: (-t["conversions"], -t["clicks"]))[:TOP_TERMS]
    term_texts = [t["term"] for t in top_terms if t["conversions"] > 0 or t["clicks"] > 0][:10]

    # Window and volume.
    start = dt.date.fromisoformat(args.start) if args.start else None
    end = dt.date.fromisoformat(args.end) if args.end else None
    if start and start < FULL_ASSET_STATS_FROM:
        notes.append(f"the window starts {start}; Google has full headline stats only from {FULL_ASSET_STATS_FROM}, "
                     "so earlier dates may be incomplete")
    unpinned = [h for h in heads if not h["pin"]]
    top = max([h["impressions"] for h in unpinned] or [0.0])
    ad_impr = ad["impressions"] if ad and ad["impressions"] is not None else None
    volume = ad_impr if ad_impr is not None else max([h["impressions"] for h in heads] or [0.0])
    too_early_ad = volume < MIN_AD_IMPRESSIONS
    if too_early_ad:
        notes.append(f"the ad has {volume:,.0f} impressions in this window; under {MIN_AD_IMPRESSIONS:,} is too "
                     "early to judge single headlines. Add headlines to empty slots, or wait.")
    if ad_impr is None:
        notes.append("no ad totals given (--ad), so serving share is measured against the most-served headline")
    if not unpinned:
        notes.append("every headline is pinned, so there's nothing to compare")

    # Baselines: each headline against the ad's other unpinned headlines.
    tot = {m: sum(h[m] for h in unpinned) for m in ("impressions", "clicks", "conversions")}
    for h in heads:
        h["themes"] = themes(h["text"], term_texts, brand)
        n, c, v = h["impressions"], h["clicks"], h["conversions"]
        h["ctr"] = c / n if n else None
        h["ctr_low"], h["ctr_high"] = wilson(c, n)
        h["conv_rate"] = v / c if c else None
        h["cpi"] = v / n if n else None
        h["share_top"] = n / top if top else None
        h["share_ad"] = n / ad_impr if ad_impr else None
        if h["pin"]:
            rest = tot
        else:
            rest = {m: tot[m] - h[m] for m in tot}
        h["base_ctr"] = rest["clicks"] / rest["impressions"] if rest["impressions"] else None
        h["base_cpi"] = rest["conversions"] / rest["impressions"] if rest["impressions"] else None
        h["ctr_signal"] = signal(c, n, h["base_ctr"]) if n >= MIN_LINE_IMPRESSIONS else "too few"
        h["cpi_signal"] = signal(v, n, h["base_cpi"]) if n >= MIN_LINE_IMPRESSIONS and rest["conversions"] + v > 0 \
            else ("too few" if n < MIN_LINE_IMPRESSIONS else "no conversions")

    # Near duplicates: the less-served line of a pair gets the flag.
    for i, a in enumerate(heads):
        for b in heads[i + 1:]:
            sa, sb = set(content(a["text"])), set(content(b["text"]))
            if overlap(sa, sb) >= NEAR_DUPLICATE or (sa and sb and (sa <= sb or sb <= sa)):
                weaker, stronger = (a, b) if a["impressions"] < b["impressions"] else (b, a)
                weaker.setdefault("duplicate_of", stronger["text"])

    for h in heads:
        reasons = []
        label = h["label"]
        if h["pin"]:
            verdict = "pinned"
            reasons.append(f"pinned to position {h['pin']}, so it shows whenever that spot shows; not compared")
        elif too_early_ad or label in ("learning", "pending"):
            verdict = "too early"
            reasons.append("Google lists it as learning" if label in ("learning", "pending")
                           else "the ad needs more impressions first")
        elif (h["share_top"] is not None and h["share_top"] < LOW_SERVING_SHARE and h["conversions"] == 0):
            verdict = "replace"
            reasons.append("Google hasn't shown it" if h["impressions"] == 0 else
                           f"shown {h['share_top']:.0%} as often as the most-shown headline, with no conversions")
        else:
            ups = [w for w, sig in (("CTR", h["ctr_signal"]), ("conversions per impression", h["cpi_signal"]))
                   if sig == "higher"]
            downs = [w for w, sig in (("CTR", h["ctr_signal"]), ("conversions per impression", h["cpi_signal"]))
                     if sig == "lower"]
            if h["cpi_signal"] == "higher" or (ups and not downs):
                verdict = "keep"
            elif downs:
                verdict = "replace"
            else:
                verdict = "keep for now"
            if ups:
                reasons.append(" and ".join(ups) + " clearly above the other headlines")
            if downs:
                reasons.append(" and ".join(downs) + " clearly below the other headlines")
            if not ups and not downs:
                reasons.append("too few impressions to compare" if h["ctr_signal"] == "too few"
                               else "no clear difference")
        if h.get("duplicate_of") and verdict not in ("keep", "pinned"):
            reasons.append(f"near duplicate of '{h['duplicate_of']}'")
        if label == "low" and verdict not in ("replace", "pinned"):
            reasons.append("Google rates it Low")
        if label == "best":
            reasons.append("Google rates it Best")
        h["verdict"], h["reasons"] = verdict, reasons

    # What to replace first: the rarely shown, then the weakest CTR, then near duplicates rated keep for now.
    def priority(h):
        if h["verdict"] == "replace" and h["share_top"] is not None and h["share_top"] < LOW_SERVING_SHARE:
            return (0, h["impressions"])
        if h["verdict"] == "replace":
            gap = (h["ctr_high"] or 0) - (h["base_ctr"] or 0)
            return (1, gap)
        return (2, h["impressions"])
    candidates = [h for h in heads if h["verdict"] == "replace"]
    dupes = [h for h in heads if h["verdict"] == "keep for now" and h.get("duplicate_of")]
    ordered = sorted(candidates, key=priority) + sorted(dupes, key=priority)
    replace_now = ordered[:args.max_replace]
    for i, h in enumerate(heads, 1):
        h["n"] = i
    open_slots = max(0, 15 - len(heads))
    kept = [h for h in heads if h not in replace_now]
    kept_themes = sorted({t for h in kept for t in h["themes"]}, key=THEME_ORDER.index)
    missing = [t for t in ("keyword", "proof", "cta") if t not in kept_themes and (t != "keyword" or term_texts)]
    if not term_texts:
        notes.append("no search terms or keywords given, so keyword lines can't be spotted")
    if not any(t in kept_themes for t in ("offer", "price", "free")):
        missing.append("offer")

    # Searches the headlines don't echo.
    head_sets = [set(content(h["text"])) for h in heads]
    all_words = set().union(*head_sets) if head_sets else set()
    comp_low = list(competitor_names)
    if args.competitors:
        comp_low += sorted({l["competitor"] for l in load_competitors(args.competitors) if l["competitor"] != "unknown"})
    term_rows = []
    for t in top_terms:
        cset = set(content(t["term"]))
        if not cset:
            continue
        if any(name_in(c, t["term"]) for c in comp_low):
            cover = "competitor name"
        elif any(cset <= hs for hs in head_sets):
            cover = "yes"
        elif cset & all_words:
            cover = "partly"
        else:
            cover = "no"
        term_rows.append({**t, "covered": cover,
                          "missing_words": [] if cover == "competitor name" else sorted(cset - all_words)})

    comp = compare_competitors(args.competitors, heads, replace_now, brand, competitor_names, notes) \
        if args.competitors else None

    return {
        "ad": {"id": ad_id or (ad["id"] if ad else ""), "campaign": (ad or {}).get("campaign") or
               next((r["campaign"] for r in assets if r["campaign"]), ""),
               "ad_group": (ad or {}).get("ad_group") or next((r["ad_group"] for r in assets if r["ad_group"]), ""),
               "status": (ad or {}).get("status", ""), "impressions": ad_impr,
               "clicks": (ad or {}).get("clicks"), "conversions": (ad or {}).get("conversions"),
               "headline_count": len(heads), "pinned": sum(1 for h in heads if h["pin"]),
               "descriptions": [t for t, _ in (ad or {}).get("descriptions", [])]},
        "window": {"start": args.start, "end": args.end},
        "volume": volume, "too_early": too_early_ad,
        "pool": {**tot, "ctr": tot["clicks"] / tot["impressions"] if tot["impressions"] else None,
                 "cpi": tot["conversions"] / tot["impressions"] if tot["impressions"] else None},
        "headlines": heads,
        "replace_now": [h["n"] for h in replace_now],
        "replace_other": [h["n"] for h in ordered[args.max_replace:]],
        "open_slots": open_slots,
        "kept_themes": kept_themes, "missing_themes": missing,
        "terms": term_rows,
        "competitors": comp,
        "thresholds": {"min_ad_impressions": MIN_AD_IMPRESSIONS, "min_line_impressions": MIN_LINE_IMPRESSIONS,
                       "low_serving_share": LOW_SERVING_SHARE, "max_replace": args.max_replace},
        "notes": notes,
    }


def compare_competitors(path: str, heads: list[dict], replace_now: list[dict], brand: list[str],
                        context_competitors: list[str], notes: list[str]) -> dict:
    lines = load_competitors(path)
    if not lines:
        notes.append(f"no competitor lines found in {path}")
        return {"competitors": [], "lines": 0}
    names = sorted({l["competitor"] for l in lines})
    skip = set()
    for n in names + context_competitors + brand:
        skip |= set(content(n))
        skip |= set(content(re.sub(r"\.(com|net|org|co|io|ai|us|ca|uk)$", "", n.lower())))
    comp_heads = [l for l in lines if l["kind"] == "headline"]

    # Which of our headlines sound like a competitor's.
    sounds = []
    for h in heads:
        hs = set(content(h["text"])) - skip
        best = max(((overlap(hs, set(content(c["text"])) - skip), c) for c in comp_heads),
                   key=lambda x: x[0], default=(0.0, None))
        if best[1] is not None and best[0] >= SOUNDS_LIKE:
            sounds.append({"n": h["n"], "text": h["text"], "competitor": best[1]["competitor"],
                           "their_line": best[1]["text"], "overlap": round(best[0], 2)})

    # Claim types: who leads with what.
    types = []
    for t in CLAIM_TYPES:
        users = sorted({l["competitor"] for l in lines if t in themes(l["text"], [], [])})
        ours = [h["n"] for h in heads if t in h["themes"]]
        kept_ours = [h["n"] for h in heads if t in h["themes"] and h not in replace_now]
        types.append({"type": t, "competitors": users, "your_headlines": ours, "your_kept": kept_ours})
    n_comp = len(names)
    gaps = [t["type"] for t in types if t["competitors"] and not t["your_kept"]
            and len(t["competitors"]) >= max(1, math.ceil(n_comp / 2))]

    # Phrases: unigrams and bigrams, counted by competitor.
    def grams(text):
        toks = [w for w in content(text) if w not in skip]
        return set(toks) | {" ".join(p) for p in zip(toks, toks[1:])}
    by_phrase: dict = {}
    for l in comp_heads:
        for g in grams(l["text"]):
            e = by_phrase.setdefault(g, {"competitors": set(), "lines": 0})
            e["competitors"].add(l["competitor"])
            e["lines"] += 1
    our_text = " ".join(h["text"] for h in heads)
    our_grams = set().union(*[grams(h["text"]) for h in heads]) if heads else set()
    rows = sorted(by_phrase.items(), key=lambda kv: (-len(kv[1]["competitors"]), -kv[1]["lines"],
                                                       -len(kv[0].split()), kv[0]))
    shown = []
    for phrase, e in rows:
        if len(e["competitors"]) < (2 if n_comp > 1 else 1) or (n_comp == 1 and e["lines"] < 2):
            continue
        if any(phrase in s["phrase"].split(" ") or phrase == s["phrase"] for s in shown
               if len(s["competitors"]) == len(e["competitors"]) and s["lines"] == e["lines"]):
            continue
        if any(phrase in s["phrase"] and len(s["competitors"]) == len(e["competitors"]) and s["lines"] == e["lines"]
               for s in shown):
            continue
        shown.append({"phrase": phrase, "competitors": sorted(e["competitors"]), "lines": e["lines"],
                      "you_use": phrase in our_grams or phrase_in(phrase, our_text)})
        if len(shown) >= 15:
            break
    comp_words = set()
    for l in lines:
        comp_words |= set(content(l["text"]))
    unique, seen = [], set()
    for h in heads:
        if h in replace_now:
            continue
        for w in content(h["text"]):
            if w in skip or w in comp_words or w in seen or re.fullmatch(r"[\d.,$%#/]+", w):
                continue
            seen.add(w)
            unique.append({"word": w, "n": h["n"], "text": h["text"]})
    return {"competitors": names, "lines": len(lines), "headlines": len(comp_heads), "sounds_like": sounds,
            "claim_types": types, "gaps": gaps, "phrases": shown, "only_you": unique}


# ---------------------------------------------------------------- output

def pct(x, digits=1) -> str:
    return "MISSING" if x is None else f"{x * 100:.{digits}f}%"


def rng(lo, hi) -> str:
    return "" if lo is None else f"{lo * 100:.1f} to {hi * 100:.1f}%"


def fmt(x, digits=0) -> str:
    if x is None:
        return "MISSING"
    return f"{x:,.{digits}f}" if digits or float(x).is_integer() else f"{x:,.1f}"


def markdown(res: dict) -> str:
    ad, pool = res["ad"], res["pool"]
    out = [f"# Headline review: {ad['campaign'] or 'campaign MISSING'} / {ad['ad_group'] or 'ad group MISSING'}"
           + (f" / ad {ad['id']}" if ad["id"] else ""), ""]
    w = res["window"]
    out.append(f"**Window:** {w['start'] or 'MISSING'} to {w['end'] or 'MISSING'}")
    if ad["impressions"] is not None:
        ctr = ad["clicks"] / ad["impressions"] if ad["impressions"] and ad["clicks"] is not None else None
        out.append(f"**Ad totals:** {fmt(ad['impressions'])} impressions, {fmt(ad['clicks'])} clicks "
                   f"(CTR {pct(ctr, 2)}), {fmt(ad['conversions'], 1) if ad['conversions'] is not None else 'MISSING'} conversions")
    else:
        out.append("**Ad totals:** MISSING (serving share is measured against the most-served headline)")
    out.append(f"**Headlines:** {ad['headline_count']} of 15, {ad['pinned']} pinned. "
               f"Unpinned headlines together: CTR {pct(pool['ctr'], 2)}, "
               f"{pct(pool['cpi'], 3)} conversions per impression")
    out.append("")
    if res["notes"]:
        out.append("**Notes:**")
        out += [f"- {n}" for n in res["notes"]]
        out.append("")
    share_head = "Share of ad impr." if ad["impressions"] else "Share of top headline"
    out += ["## Headlines", "",
            f"| # | Headline | Pin | Impr. | {share_head} | CTR (95% range) | Conv. | Conv. per 1,000 impr. | Theme | Verdict | Why |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in res["headlines"]:
        share = h["share_ad"] if h["share_ad"] is not None else h["share_top"]
        share_txt = "MISSING" if share is None else f"{share:.0%}"
        ctr_txt = "" if h["ctr"] is None else f"{h['ctr'] * 100:.2f}% ({rng(h['ctr_low'], h['ctr_high'])})"
        cpk = "" if h["cpi"] is None else f"{h['cpi'] * 1000:.2f}"
        out.append(f"| {h['n']} | {h['text']} | {h['pin']} | {fmt(h['impressions'])} | {share_txt} | {ctr_txt} | "
                   f"{fmt(h['conversions'], 1) if h['conversions'] else '0'} | {cpk} | "
                   f"{', '.join(theme_label(t) for t in h['themes'])} | **{h['verdict']}** | {'; '.join(h['reasons'])} |")
    out.append("")
    byn = {h["n"]: h for h in res["headlines"]}
    out += ["## What to change", ""]
    if res["replace_now"]:
        out.append(f"Replace these first ({len(res['replace_now'])}, at most {res['thresholds']['max_replace']} a round):")
        out += [f"- #{n} {byn[n]['text']} ({'; '.join(byn[n]['reasons'])})" for n in res["replace_now"]]
    else:
        out.append("No headline to replace on this data.")
    if res["replace_other"]:
        out.append("")
        out.append("Next round, if these still lag: " + ", ".join(f"#{n} {byn[n]['text']}" for n in res["replace_other"]))
    out.append("")
    out.append(f"Empty slots: {res['open_slots']} (an RSA takes up to 15 headlines).")
    out.append("Themes the remaining headlines cover: " + (", ".join(theme_label(t) for t in res["kept_themes"]) or "none"))
    if res["missing_themes"]:
        out.append("Not covered: " + ", ".join(theme_label(t) for t in res["missing_themes"])
                   + ". Themes are found by word match, so check them by eye.")
    out.append("")
    if res["terms"]:
        out += ["## Converting searches and your headlines", "",
                "| Search term or keyword | From | Clicks | Conv. | In a headline | Words no headline uses |",
                "|---|---|---|---|---|---|"]
        for t in res["terms"]:
            out.append(f"| {t['term']} | {t['kind']} | {fmt(t['clicks'])} | {fmt(t['conversions'], 1) if t['conversions'] else '0'} | "
                       f"{t['covered']} | {', '.join(t['missing_words'])} |")
        out.append("")
    comp = res["competitors"]
    if comp is not None:
        out += ["## Competitors", ""]
        if not comp.get("competitors"):
            out.append("No competitor lines were found in the file.")
        else:
            out.append(f"{comp['lines']} lines from {len(comp['competitors'])} competitor(s): "
                       + ", ".join(comp["competitors"]))
            out.append("")
            out.append("**Claim types:**")
            out.append("")
            out += ["| Type | Competitors using it | Your headlines | Kept after replacements |", "|---|---|---|---|"]
            for t in comp["claim_types"]:
                out.append(f"| {theme_label(t['type'])} | {len(t['competitors'])}: {', '.join(t['competitors'])} | "
                           f"{', '.join('#' + str(n) for n in t['your_headlines']) or 'none'} | "
                           f"{', '.join('#' + str(n) for n in t['your_kept']) or 'none'} |")
            out.append("")
            if comp["gaps"]:
                out.append("Most competitors use these and your remaining headlines don't: "
                           + ", ".join(theme_label(g) for g in comp["gaps"])
                           + ". Fill one only with a claim the business has approved.")
                out.append("")
            if comp["sounds_like"]:
                out.append("**Your headlines that sound like a competitor's:**")
                out.append("")
                out += ["| # | Yours | Theirs | Competitor | Word overlap |", "|---|---|---|---|---|"]
                for s in comp["sounds_like"]:
                    out.append(f"| {s['n']} | {s['text']} | {s['their_line']} | {s['competitor']} | {s['overlap']:.0%} |")
                out.append("")
                out.append("Keyword lines are meant to match the search, so sameness there is expected. It matters more "
                           "for benefit, proof, and offer lines, where a copy of a competitor's line gives no reason to "
                           "pick you.")
                out.append("")
            if comp["phrases"]:
                out.append("**Phrases competitors repeat:**")
                out.append("")
                out += ["| Phrase | Competitors | Headlines | You use it |", "|---|---|---|---|"]
                for p in comp["phrases"]:
                    out.append(f"| {p['phrase']} | {len(p['competitors'])}: {', '.join(p['competitors'])} | {p['lines']} | "
                               f"{'yes' if p['you_use'] else 'no'} |")
                out.append("")
            if comp["only_you"]:
                out.append("**Words only you use** (in the headlines you'd keep): "
                           + ", ".join(f"{u['word']} (#{u['n']})" for u in comp["only_you"]))
                out.append("")
    out += ["## How to read this", "",
            "Each headline is compared with the ad's other unpinned headlines. \"Clearly\" means its 95% range "
            "doesn't include their rate. Headlines serve in combinations, and Google shows the ones it expects to "
            "win more often, to the searches it expects them to win, so a headline's numbers partly reflect the lines "
            "it showed with. A replace verdict is a reason to test a new line, not proof the old one is bad.", ""]
    return "\n".join(out)


def print_summary(res: dict) -> None:
    ad = res["ad"]
    print(f"Ad: {ad['campaign']} / {ad['ad_group']} / {ad['id'] or 'id MISSING'}; "
          f"{ad['headline_count']} headlines, {ad['pinned']} pinned; volume {fmt(res['volume'])} impressions")
    for n in res["notes"]:
        print(f"  note: {n}")
    print()
    for h in res["headlines"]:
        ctr = "" if h["ctr"] is None else f"CTR {h['ctr'] * 100:.2f}% ({rng(h['ctr_low'], h['ctr_high'])})"
        print(f"  #{h['n']:<2} {h['verdict']:<12} {h['text']:<32} impr {fmt(h['impressions']):>8}  {ctr}  "
              f"conv {fmt(h['conversions'], 1) if h['conversions'] else '0'}  [{', '.join(h['themes'])}]  "
              f"{'; '.join(h['reasons'])}")
    print(f"\nReplace first: {', '.join('#' + str(n) for n in res['replace_now']) or 'none'}; "
          f"empty slots: {res['open_slots']}; not covered: {', '.join(res['missing_themes']) or 'none'}")
    gaps = [t for t in res["terms"] if t["covered"] in ("no", "partly")]
    if gaps:
        print("Converting searches not in a headline: " + "; ".join(f"{t['term']} ({fmt(t['conversions'], 1)} conv)"
                                                                   for t in gaps[:8]))
    comp = res["competitors"]
    if comp and comp.get("competitors"):
        print(f"Competitors: {', '.join(comp['competitors'])}; gaps: {', '.join(comp['gaps']) or 'none'}; "
              f"sound-alikes: {len(comp['sounds_like'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--assets", nargs="+", required=True, help="headline performance: connector JSON or CSV export")
    parser.add_argument("--ad", help="the ad: headlines, pins, and totals (connector JSON or CSV)")
    parser.add_argument("--ad-id")
    parser.add_argument("--search-terms")
    parser.add_argument("--keywords")
    parser.add_argument("--competitors")
    parser.add_argument("--context")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-replace", type=int, default=MAX_REPLACE)
    parser.add_argument("--markdown")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    res = review(args)
    if "error" in res:
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"error: {res['error']}")
            for a in res.get("ads", []):
                print(f"  ad {a['ad_id']} in '{a['ad_group']}': {fmt(a['impressions'])} impressions")
        return 2
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(markdown(res), encoding="utf-8")
    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print_summary(res)
        if args.markdown:
            print(f"\nwrote {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
