# Adapted in part from Copycat in [google-marketing-solutions/copycat](https://github.com/google-marketing-solutions/copycat) (Apache-2.0, Copyright 2024 Google LLC) and rsa-ad-copy-writer in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe).
"""Check Google Ads responsive search ad copy, sitelinks, callouts, and
structured snippets before anyone approves them.

Methods borrowed and rewritten: counting keyword insertion and customizer
tokens by their default text, and the "memorization" check that flags a new ad
copied from existing ads, follow Copycat. The keyword coverage check and the
serving-share view of existing assets follow rsa-ad-copy-writer. Everything
else is this skill's own.

Errors (exit code 1) block the copy:
  - limits: 3 to 15 headlines of 30, 2 to 4 descriptions of 90, paths of 15,
    sitelink text 25 and description lines 35 (both lines or neither),
    callouts 25, snippet values 25 (3 to 10 values, one of Google's headers).
    Wide (Chinese, Japanese, Korean) characters count double.
  - claims: every number, percentage, price, "free", guarantee, superlative,
    comparison, rating, award, credential, and sale or deadline must match an
    approved item in the context file's "Business and offer" section or in an
    approved-claims file. Items still marked "confirm" or past their end date
    don't count.
  - duplicates, repeated punctuation, emoji and decorative symbols, gimmicky
    capitalization, phone numbers, extra spaces, words the context says to
    avoid, competitor names the context doesn't allow, and the punctuation
    rules Google states for sitelinks, callouts, and snippets.

Warnings (shown to the person, who decides): near duplicates, heavy pinning,
missing keyword, offer, proof, or call-to-action coverage, exclamation marks in
headlines, numbers that come only from a keyword, superlatives that need proof
on the landing page, offers not seen on the landing page, assets already
running in the account, and offers ending soon.

Usage:
  python3 check_ad_copy.py COPY.json
      [--context .agents/google-ads-context.md]
      [--claims approved-claims.txt]
      [--existing FILE ...]        existing ads or asset report (CSV, Editor export, or connector JSON)
      [--keywords keywords.csv]    normalized keyword CSV with ad_group, keyword, clicks, conversions
      [--landing-page page.txt]    text of the final URL page, for offer checks
      [--today YYYY-MM-DD] [--markdown TABLE.md] [--json]

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
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- limits

LIMITS = {
    "headline": 30, "description": 90, "path": 15,
    "sitelink_text": 25, "sitelink_description": 35,
    "callout": 25, "snippet_value": 25,
}
HEADLINES = (3, 15)
DESCRIPTIONS = (2, 4)
SNIPPET_VALUES = (3, 10)
SNIPPET_HEADERS = [
    "Amenities", "Brands", "Courses", "Degree programs", "Destinations", "Featured hotels",
    "Insurance coverage", "Models", "Neighborhoods", "Service catalog", "Shows", "Styles", "Types",
]
MAX_ENABLED_RSAS = 3          # Google Ads account limits: 3 enabled RSAs per ad group
SITELINKS_TO_SHOW = 2         # Google: at least 2 sitelinks are needed to show
SITELINKS_GOOD = 4            # Google: keep at least 4 active
SITELINKS_MAX = 20
CALLOUTS_GOOD = 4             # this skill's default
HEADLINES_GOOD = 10           # this skill's default; Ad Strength favors more unique headlines
LOW_SERVING_SHARE = 0.10      # rsa-ad-copy-writer's rule for weak existing assets
ENDING_SOON_DAYS = 14

AD_TEXT = {"headline", "description", "path"}
ASSET_TEXT = {"sitelink_text", "sitelink_description", "callout", "snippet_value"}
LABELS = {
    "headline": "headline", "description": "description", "path": "path",
    "sitelink_text": "sitelink text", "sitelink_description": "sitelink description",
    "callout": "callout", "snippet_value": "snippet value",
}

# ---------------------------------------------------------------- word lists

STOPWORDS = set("""a an the and or for to of in on at by with from your you our we us my me it its is are be
been was were all any more now this that these those near as so if than then into over per via who what when
where how why can will just here there also get""".split())
CTA_WORDS = set("""get book call schedule start try request shop buy order sign join contact download compare find
see learn claim reserve apply visit explore browse talk chat enroll register subscribe upgrade switch hire ask
speak message text quote""".split())
ACRONYMS = set("""USA US UK EU UAE FAQ HVAC SEO SEM PPC CRM ERP API AI ML IT HR CPA CFO CEO LLC INC LTD ROI B2B B2C
SAAS SaaS NYC LA DC IRS DIY ADA HOA EV EVs ATM PDF USB TV HD UHD LED LCD GPS SUV AWD MRI CPR RN MD DDS PhD MBA CPA
BBB ISO SOC GDPR HIPAA FDA OSHA EPA PPE AC DIY FAQs APIs SMS VIP AM PM""".split())
PROMO_CAPS = set("""FREE SALE NOW BEST NEW OFF HOT BUY CALL SAVE DEAL DEALS TODAY LIMITED CHEAP WOW ONLY EXCLUSIVE
HUGE BIG CLICK HURRY URGENT AMAZING""".split())
AI_TELLS = [
    "unlock the power", "say goodbye to", "take it to the next level", "next level", "reimagined",
    "look no further", "elevate your", "game-changer", "game changer", "seamless", "supercharge",
    "revolutionize", "in today's", "whether you're", "we've got you covered",
]
UNIT_WORDS = set("""year yr day hour hr minute min week month star review rating customer client user team
business company home homeowner family patient student member job project install installation order
location store office branch state country city product brand model item award expert technician tech
plumber engineer employee staff partner integration template feature download mile step point percent
sale shipment delivery repair call guest""".split())
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100, "thousand": 1000,
}

# Claim triggers that aren't numbers. Each category lists the words that make a
# claim, and the words an approved item must contain to support it.
TRIGGERS = {
    "free": (r"(?<![\w-])free(?![\w-])|\bcomplimentary\b|\bno[- ]cost\b|\bat no charge\b|\bfree of charge\b",
             r"(?<![\w-])free(?![\w-])|complimentary|no[- ]cost|no charge|\$0\b"),
    "guarantee": (r"\bguarantee[ds]?\b|\bmoney[- ]back\b|\bwarrant(?:y|ies|ied)\b|\brisk[- ]free\b|\bno[- ]risk\b"
                  r"|\brefunds?\b|\bprice[- ]match\b|\bpromise\b",
                  r"guarant|money[- ]back|warrant|risk[- ]free|no[- ]risk|refund|price[- ]match|promise"),
    "superlative": (r"(?<!\w)#\s?1\b|\bno\.?\s?1\b|\bnumber one\b|\bbest\b|\btop[- ]rated\b|\btop[- ]ranked\b"
                    r"|\bleading\b|\bcheapest\b|\blowest\b|\bhighest\b|\bfastest\b|\bquickest\b|\blargest\b"
                    r"|\bbiggest\b|\bgreatest\b|\bfinest\b|\bsafest\b|\bunbeatable\b|\bunmatched\b|\bunrivall?ed\b"
                    r"|\bworld[- ]class\b|\bmost (?:trusted|popular|reliable|affordable|experienced|recommended)\b",
                    None),
    "comparison": (r"\b(?:better|cheaper|faster|quicker|lower|higher|stronger|safer|easier|smarter|bigger|larger)"
                   r"\s+than\b|\bvs\.?(?!\w)|\bversus\b|\bunlike\b|\bcompared to\b", None),
    "rating": (r"[\u2605\u2606]|\b(?:highly|well|top|best)[- ]rated\b|\bfive[- ]star\b",
               r"rated|rating|star|review|\u2605"),
    "award": (r"\baward(?:s|ed)?\b|\baward[- ]winning\b|\bwinners?\b|\bvoted\b|\bas seen (?:on|in)\b"
              r"|\bfeatured (?:on|in)\b|\brecogni[sz]ed by\b", r"award|winner|voted|as seen|featured|recogni"),
    "credential": (r"\blicensed\b|\binsured\b|\bbonded\b|\bcertified\b|\baccredited\b|\bBBB\b", None),
    "sale": (r"\bsale\b|\bdiscount(?:s|ed)?\b|\bdeals?\b|\bcoupons?\b|\bpromo(?:tion)?s?\b|\bclearance\b"
             r"|\bspecial offer\b", r"sale|discount|deal|coupon|promo|clearance|special|% off|\boff\b"),
    "deadline": (r"\blimited[- ]time\b|\b(?:today|this week|this weekend|this month) only\b|\bends? (?:soon|today"
                 r"|tonight|sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b|\blast chance\b|\bhurry\b"
                 r"|\bexpires?\b", None),
    "stock": (r"\bwhile supplies last\b|\bonly \d+ left\b|\blimited stock\b|\bselling fast\b",
              r"supplies|left|stock|selling"),
}
TRIGGER_RE = {k: re.compile(v[0], re.IGNORECASE) for k, v in TRIGGERS.items()}
SUPPORT_RE = {k: re.compile(v[1], re.IGNORECASE) for k, v in TRIGGERS.items() if v[1]}
ANY_TRIGGER_RE = re.compile("|".join(f"(?:{v[0]})" for v in TRIGGERS.values()), re.IGNORECASE)
NEEDS_PAGE_PROOF = {"superlative", "comparison"}
NO_WINDOW = {"credential", "rating", "award", "stock"}   # the trigger is enough for these
WEEKDAY_RE = re.compile(r"sunday|monday|tuesday|wednesday|thursday|friday|saturday", re.IGNORECASE)
ODD_CASE_OK = {"WiFi", "SoFi", "HiFi", "LoJack"}

NUM_RE = re.compile(
    r"(?P<cur>[$\u20ac\u00a3\u00a5\u20b9]\s?)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<mult>[kKmM](?![A-Za-z]))?(?P<plus>\+)?(?P<pct>\s?%|\s?percent\b)?")
FRACTION_RE = re.compile(r"(?<![\d.])(\d(?:\.\d+)?)\s?/\s?(5|10)\b")
ALWAYS_RE = re.compile(r"\b24\s?[/-]\s?7\b|\b24\s?hours? a day\b", re.IGNORECASE)
SPELLED_RE = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")[- ](" + "|".join(sorted(UNIT_WORDS)) + r")s?\b",
                        re.IGNORECASE)
CURRENCY_AFTER_RE = re.compile(r"^\s?(dollars?|usd|eur|euros?|gbp|pounds?)\b", re.IGNORECASE)
DATE_RES = [
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    re.compile(r"\b" + "(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
               r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)" + r"\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
]
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
MONTH_NAME = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
              r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
AD_DATE_RES = [
    re.compile(r"\b" + MONTH_NAME + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+\d{4})?", re.I),
    re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])"),
]
END_WORDS_RE = re.compile(r"(until|through|thru|ends?|ending|expires?|expiry|valid to|valid until|to|by)\W*$", re.I)
URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.I)

# ---------------------------------------------------------------- editorial patterns

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u2604\u2607-\u26FF\u2700-\u27BF\u2B50\u2B55\uFE0F\u200D]")
DECOR_RE = re.compile("[\u2190-\u21FF\u25A0-\u25FF\u2022\u2023\u2043\u2219\u27A4\u2794\u279C]")
STAR_RE = re.compile("[\u2605\u2606]")
MARK_RE = re.compile("[\u2122\u00AE\u00A9]")
HALF_KATAKANA_RE = re.compile("[\uFF65-\uFF9F]")
REPEAT_PUNCT_RE = re.compile(r"([!?.,;:*\-])\1|[!?][!?]")
DECOR_ASTERISK_RE = re.compile(r"\*[^*\s][^*]*\*")
SPACED_LETTERS_RE = re.compile(r"\b(?:[A-Za-z][ .]){3,}[A-Za-z]\b")
SUBST_SYMBOL_RE = re.compile(r"\b[A-Za-z]+[@$][A-Za-z]+\b")
SUBST_DIGIT_RE = re.compile(r"\b[A-Za-z]+[0-9]+[A-Za-z]+\b")
REPEAT_WORD_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
LEAD_PUNCT_RE = re.compile(r"^[!?.,;:\-\u2013\u2014*\u2022~^/|\\>]")
VANITY_RE = re.compile(r"\b1[\s.\-]?8[0-9]{2}[\s.\-]?[A-Z0-9]{3}[\s.\-]?[A-Z0-9]{4}\b")
PHONE_CANDIDATE_RE = re.compile(r"\+?\(?\d[\d\s().\-]{5,}\d")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOKEN_RE = re.compile(r"\{([^{}]*)\}")
COUNTDOWN_RE = re.compile(r"\{(?:GLOBAL_)?COUNTDOWN\([^)]*\)\}", re.IGNORECASE)


def width(text: str) -> int:
    """Characters as Google counts them: wide and full-width characters count double."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower().replace("\u2019", "'"))


def stem(word: str) -> str:
    w = word.lower().strip("'")
    if w.endswith("'s"):
        w = w[:-2]
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    s, l = sorted((a, b), key=len)
    if l in (s + "s", s + "es") or (s.endswith("y") and l == s[:-1] + "ies"):
        return True
    p = 0
    for x, y in zip(a, b):
        if x != y:
            break
        p += 1
    return p >= 5 or (p >= 4 and p == len(s))


def word_in(word: str, pool) -> bool:
    return any(same_word(word, w) for w in pool)


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS]


def norm_key(text: str) -> str:
    return " ".join(words(text))


def norm_number(raw: str, mult: str | None = None) -> str:
    value = float(raw.replace(",", ""))
    if mult:
        value *= 1000 if mult.lower() == "k" else 1_000_000
    return str(int(value)) if value.is_integer() else f"{value:g}"


# ---------------------------------------------------------------- tokens (keyword insertion, customizers)

def render(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace Google Ads tokens with the text they show by default, as Copycat does."""
    notes: list[tuple[str, str]] = []

    def countdown(_m):
        notes.append(("warning", "countdown token counted as 8 characters ('00 hours'); check the ad preview"))
        return "00 hours"

    text = COUNTDOWN_RE.sub(countdown, text)

    def token(m):
        inner = m.group(1)
        name, _, default = inner.partition(":")
        key = name.strip()
        low = key.lower()
        if low == "keyword":
            d = default.strip()
            if not d:
                notes.append(("error", f"keyword insertion '{m.group(0)}' has no default text"))
                return ""
            if key == "KeyWord":
                return d.title()
            if key == "Keyword":
                return d[:1].upper() + d[1:].lower()
            if key == "keyword":
                return d.lower()
            if key == "KEYWord":
                parts = d.split()
                return " ".join([parts[0].upper()] + [p.title() for p in parts[1:]])
            if key == "KeyWORD":
                parts = d.split()
                return " ".join([p.title() for p in parts[:-1]] + [parts[-1].upper()])
            return d
        if low.startswith("customizer."):
            notes.append(("warning", f"customizer '{key}': only the default text was checked; check every value "
                                     "against the approved claims before uploading"))
            if not default.strip():
                notes.append(("error", f"customizer '{m.group(0)}' has no default text"))
            return default
        if low.startswith("location("):
            if not default.strip():
                notes.append(("warning", f"location insertion '{m.group(0)}' has no default text"))
            return default
        notes.append(("warning", f"unrecognized token '{m.group(0)}'; check it in the ad preview"))
        return default if default else m.group(0)

    return TOKEN_RE.sub(token, text), notes


# ---------------------------------------------------------------- context file

def read_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def skip_value(value: str) -> bool:
    v = value.strip().strip(".").lower()
    return (not v or v.startswith("missing") or v in ("none", "n/a", "not applicable", "no", "-")
            or (value.strip().startswith("[") and value.strip().endswith("]")))


def split_list(value: str, seps: str = ";") -> list[str]:
    out = []
    for quoted, plain in re.findall(r'"([^"]+)"|([^' + re.escape(seps) + r']+)', value):
        item = (quoted or plain).strip().strip("'\u201c\u201d")
        if item and not skip_value(item):
            out.append(item)
    return out


def label_kind(label: str) -> str:
    l = label.lower()
    if "disclaimer" in l:
        return "disclaimer"
    if "price" in l:
        return "price"
    if "proof" in l:
        return "proof"
    if "offer" in l or "promotion" in l:
        return "offer"
    if "restricted" in l:
        return "restricted"
    if "sell" in l or "service" in l or "product" in l:
        return "business"
    return "other"


def parse_date(match, pattern_index: int):
    try:
        if pattern_index == 0:
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if pattern_index == 1:
            return dt.date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        return dt.date(int(match.group(3)), MONTHS[match.group(1).lower()[:3]], int(match.group(2)))
    except ValueError:
        return None


def make_item(text: str, kind: str, source: str) -> dict:
    end = None
    for i, rx in enumerate(DATE_RES):
        for m in rx.finditer(text):
            if END_WORDS_RE.search(text[max(0, m.start() - 30):m.start()]):
                d = parse_date(m, i)
                if d and (end is None or d < end):
                    end = d
    clean = URL_RE.sub(" ", text)
    for rx in DATE_RES:
        clean = rx.sub(" ", clean)
    return {
        "text": text, "kind": kind, "source": source, "end": end,
        "confirm": bool(re.search(r"\bconfirm\b", text, re.IGNORECASE)),
        "lower": clean.lower(), "words": [stem(w) for w in words(clean)],
        "numbers": numeric_claims(clean),
    }


def parse_context(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8-sig")
    sections = read_sections(text)
    ctx = {"items": [], "protected": [], "unwanted": [], "competitors": [], "competitors_allowed": False,
           "competitor_policy": "MISSING", "avoid": [], "use": [], "restricted": "", "path": path}
    label = None
    for line in sections.get("business and offer", "").splitlines():
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if not m:
            continue
        indent, body = len(m.group(1).replace("\t", "    ")), m.group(2).strip()
        if indent == 0 or label is None:
            label, _, value = body.partition(":") if ":" in body else (body, "", "")
            label = label.strip()
            kind = label_kind(label)
            if kind == "restricted":
                ctx["restricted"] = value.strip()
                continue
            for part in split_list(value):
                ctx["items"].append(make_item(part, kind, f"context: {label}"))
        elif not skip_value(body):
            ctx["items"].append(make_item(body, label_kind(label), f"context: {label}"))
    for name, key in (("protected terms", "protected"), ("terms we don't want", "unwanted")):
        for line in sections.get(name, "").splitlines():
            m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if m and not skip_value(m.group(1)):
                ctx[key].append(m.group(1).strip())
    for line in sections.get("competitor policy", "").splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?):\s*(.*)$", line)
        if not m:
            continue
        label, value = m.group(1).lower(), m.group(2).strip()
        if "name competitors" in label:
            ctx["competitor_policy"] = value or "MISSING"
            ctx["competitors_allowed"] = value.lower().startswith("yes")
        elif "main competitors" in label:
            ctx["competitors"] = split_list(value, ",;")
    for line in sections.get("brand voice and copy rules", "").splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?):\s*(.*)$", line)
        if not m:
            continue
        label = m.group(1).lower()
        if "avoid" in label:
            ctx["avoid"] = split_list(m.group(2), ",;")
        elif "use" in label:
            ctx["use"] = split_list(m.group(2), ",;")
    return ctx


def parse_claims_file(path: str) -> list[dict]:
    items = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        m = re.match(r"^(offer|price|proof|disclaimer)\s*:\s*(.+)$", line, re.IGNORECASE)
        kind, text = (m.group(1).lower(), m.group(2)) if m else ("proof", line)
        items.append(make_item(text, kind, f"claims file: {Path(path).name}"))
    return items


# ---------------------------------------------------------------- claims

def numeric_claims(text: str) -> list[dict]:
    claims: list[dict] = []
    used: list[tuple[int, int]] = []

    def free(span):
        return all(span[1] <= a or span[0] >= b for a, b in used)

    for m in FRACTION_RE.finditer(text):
        if not free(m.span()):
            continue
        claims.append({"category": "rating", "text": m.group(0), "number": norm_number(m.group(1)),
                       "unit": "rating", "span": m.span()})
        used.append(m.span())
    for i, rx in enumerate(AD_DATE_RES):
        for m in rx.finditer(text):
            if not free(m.span()):
                continue
            if i == 0:
                month, day = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
            else:
                month, day = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                claims.append({"category": "date", "text": m.group(0), "date": (month, day), "span": m.span()})
                used.append(m.span())
    for m in ALWAYS_RE.finditer(text):
        claims.append({"category": "number", "text": m.group(0), "number": "24/7", "unit": None, "span": m.span()})
        used.append(m.span())
    for m in SPELLED_RE.finditer(text):
        if free(m.span()):
            claims.append({"category": "number", "text": m.group(0), "number": str(NUMBER_WORDS[m.group(1).lower()]),
                           "unit": stem(m.group(2)), "span": m.span()})
            used.append(m.span())
    for m in NUM_RE.finditer(text):
        start, end = m.span()
        if not free((start, end)) or not m.group("num"):
            continue
        num_start = m.start("num")
        before = text[:start] if m.group("cur") else text[:num_start]
        after = text[end:]
        if before.endswith("#") or (before[-1:].isalnum()) or re.match(r"(st|nd|rd|th)\b", after, re.I):
            continue
        if after[:1].isalpha() and not m.group("mult"):
            glued = re.match(r"([A-Za-z]+)", after).group(1)
            if stem(glued) not in UNIT_WORDS and glued.lower() not in ("hr", "hrs", "yr", "yrs", "min", "mins"):
                continue
        unit = None
        if m.group("pct"):
            unit = "%"
        elif m.group("cur") or CURRENCY_AFTER_RE.match(after):
            unit = "currency"
        else:
            nxt = re.match(r"\s*[+\-]?\s*([A-Za-z]+)", after)
            if nxt:
                w = stem(nxt.group(1))
                w = {"hr": "hour", "yr": "year", "min": "minute"}.get(w, w)
                if w in UNIT_WORDS:
                    unit = w
        category = {"%": "percent", "currency": "price"}.get(unit or "", "number")
        if unit in ("star", "review", "rating"):
            category = "rating"
        span_end = end
        if unit not in (None, "%", "currency"):
            nxt = re.match(r"\s*[+\-]?\s*[A-Za-z]+", after)
            span_end = end + (nxt.end() if nxt else 0)
        claims.append({"category": category, "text": text[start:span_end].strip(), "number": norm_number(
            m.group("num"), m.group("mult")), "unit": unit, "span": (start, span_end)})
        used.append((start, span_end))
    return claims


PRICE_FRAME = set("""off save saving savings from starting start only just up per each price prices pricing cost
costs low great""".split())


def window_words(text: str, span: tuple[int, int], size: int = 3) -> list[str]:
    """Content words around a claim, used to check the claim is about the same thing as the approved item."""
    left = words(text[:span[0]])[-size:]
    right = words(text[span[1]:])[:size]
    out = []
    for w in left + right:
        if w in STOPWORDS or w in CTA_WORDS or w in PRICE_FRAME or w.isdigit() or ANY_TRIGGER_RE.fullmatch(w):
            continue
        out.append(stem(w))
    return out


def find_claims(text: str, exempt: list[str]) -> list[dict]:
    """Every claim in one piece of ad text: numbers first, then trigger words."""
    phones = phone_spans(text)
    claims = [c for c in numeric_claims(text)
              if not any(a <= c["span"][0] and c["span"][1] <= b for a, b in phones)]
    for c in claims:
        if c.get("unit") in ("%", "currency"):
            c["window"] = window_words(text, c["span"])
    taken = [c["span"] for c in claims] + phones
    for category, rx in TRIGGER_RE.items():
        for m in rx.finditer(text):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            claims.append({"category": category, "text": m.group(0), "trigger": m.group(0).lower(),
                           "window": window_words(text, m.span()), "span": m.span()})
            taken.append(m.span())
    # Drop claims that sit inside a protected name (brand or product names with numbers or "free").
    lower = text.lower()
    keep = []
    for c in claims:
        inside = False
        for term in exempt:
            t = term.lower()
            for m in re.finditer(re.escape(t), lower):
                if m.start() <= c["span"][0] and c["span"][1] <= m.end():
                    inside = True
        if not inside:
            keep.append(c)
    return sorted(keep, key=lambda c: c["span"])


def deadline_ok(trigger: str, end, today: dt.date) -> bool:
    """A deadline in the ad must match a real end date on an approved offer."""
    if not end or end < today:
        return False
    days = (end - today).days
    t = trigger.lower()
    if "today" in t or "tonight" in t:
        return days == 0
    if "week" in t or WEEKDAY_RE.search(t):
        return days <= 7
    if "month" in t:
        return (end.year, end.month) == (today.year, today.month)
    if "soon" in t or "last chance" in t or "hurry" in t:
        return days <= ENDING_SOON_DAYS
    return True


def item_supports(item: dict, claim: dict) -> bool:
    if claim["category"] == "deadline":
        return item["kind"] in ("offer", "price") and deadline_ok(claim["trigger"], item["end"], claim["_today"])
    if "date" in claim:
        return bool(item["end"]) and (item["end"].month, item["end"].day) == claim["date"]
    if "number" in claim:
        nums = [n for n in item["numbers"] if n["number"] == claim["number"]]
        if not nums:
            return False
        unit = claim["unit"]
        if unit in ("%", "currency"):
            if not any(n["unit"] == unit for n in nums):
                return False
            return not claim.get("window") or any(word_in(w, item["words"]) for w in claim["window"])
        if unit == "rating":
            return bool(re.search(r"rat|star|review|/\s?(5|10)|out of", item["lower"]))
        if unit:
            return any(n["unit"] == unit for n in nums) or word_in(unit, item["words"])
        return True
    category = claim["category"]
    if category in SUPPORT_RE:
        if not SUPPORT_RE[category].search(item["lower"]):
            return False
    else:
        trigger = claim["trigger"]
        if re.fullmatch(r"#\s?1|no\.?\s?1|number one", trigger):
            if not re.search(r"#\s?1\b|\bno\.?\s?1\b|number one", item["lower"]):
                return False
        else:
            pattern = r"[\s-]+".join(re.escape(part) for part in re.split(r"[\s-]+", trigger) if part)
            if not re.search(r"(?<!\w)" + pattern + r"(?!\w)", item["lower"]):
                return False
    if claim["window"] and category not in NO_WINDOW:
        return any(word_in(w, item["words"]) for w in claim["window"])
    return True


def judge_claim(claim: dict, items: list[dict], today: dt.date) -> tuple[str, dict | None]:
    claim["_today"] = today
    matches = [i for i in items if i["kind"] in ("offer", "price", "proof") and item_supports(i, claim)]
    good = [i for i in matches if not i["confirm"] and not (i["end"] and i["end"] < today)]
    if good:
        return "approved", good[0]
    if any(i["confirm"] for i in matches):
        return "needs confirmation", next(i for i in matches if i["confirm"])
    if matches:
        return "expired", matches[0]
    return "unapproved", None


def closest_item(text: str, items: list[dict]) -> dict | None:
    pool = set(stem(w) for w in content_words(text))
    best, score = None, 0
    for item in items:
        if item["kind"] not in ("offer", "price", "proof"):
            continue
        s = sum(1 for w in pool if word_in(w, item["words"]))
        if s > score:
            best, score = item, s
    return best


# ---------------------------------------------------------------- existing ads and assets

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
    if value in (None, ""):
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(value)) or "x")
    except ValueError:
        return None


FIELD_NAMES = {"headline": "headline", "description": "description", "sitelink": "sitelink_text",
               "callout": "callout", "structured_snippet": "snippet_value", "structured snippet": "snippet_value"}
COLS = {
    "text": ["asset.text_asset.text", "asset", "asset text", "text", "headline/description"],
    "field": ["ad_group_ad_asset_view.field_type", "asset type", "field type", "asset field type", "type"],
    "campaign": ["campaign.name", "campaign"],
    "ad_group": ["ad_group.name", "ad group", "ad_group"],
    "ad_id": ["ad_group_ad.ad.id", "ad id", "ad_id"],
    "status": ["ad_group_ad.status", "ad status", "ad state", "status", "ad_status"],
    "impressions": ["metrics.impressions", "impr.", "impressions", "impr"],
    "clicks": ["metrics.clicks", "clicks"],
    "conversions": ["metrics.conversions", "conversions", "conv."],
    "pinned": ["ad_group_ad_asset_view.pinned_field", "pinned field", "pinned", "pin"],
}


def pick(row: dict, key: str):
    lower = {k.strip().lower(): v for k, v in row.items()}
    for name in COLS[key]:
        if name in lower and lower[name] not in (None, ""):
            return lower[name]
    return None


def field_of(value) -> str | None:
    v = str(value or "").strip().lower().replace("_", " ")
    for name, field in FIELD_NAMES.items():
        if v.startswith(name.replace("_", " ")):
            return field
    return None


def text_list(value) -> list[tuple[str, str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [(value, "")] if value.strip() else []
    out = []
    for v in value or []:
        if isinstance(v, dict):
            out.append((str(v.get("text", "")), str(v.get("pinned_field") or v.get("pinnedField") or "")))
        elif str(v).strip():
            out.append((str(v), ""))
    return out


def load_existing(paths: list[str]) -> list[dict]:
    rows_out: list[dict] = []

    def add(text, field, row, pinned=""):
        text = str(text or "").strip()
        if not text or text in ("--",) or not field:
            return
        rows_out.append({
            "text": text, "field": field, "campaign": str(pick(row, "campaign") or ""),
            "ad_group": str(pick(row, "ad_group") or ""), "ad_id": str(pick(row, "ad_id") or ""),
            "status": str(pick(row, "status") or "").lower(),
            "impressions": num(pick(row, "impressions")), "clicks": num(pick(row, "clicks")),
            "conversions": num(pick(row, "conversions")), "pinned": pinned or str(pick(row, "pinned") or ""),
        })

    for path in paths:
        text = decode(Path(path).read_bytes())
        if text.lstrip().startswith(("[", "{")):
            data = json.loads(text)
            if isinstance(data, dict):
                data = next((data[k] for k in ("results", "rows", "data") if isinstance(data.get(k), list)), [data])
            for raw in data:
                row = flatten(raw) if isinstance(raw, dict) else {}
                for key, value in row.items():
                    if "responsive_search_ad.headlines" in key:
                        for t, p in text_list(value):
                            add(t, "headline", row, p)
                    elif "responsive_search_ad.descriptions" in key:
                        for t, p in text_list(value):
                            add(t, "description", row, p)
                if row.get("asset.text_asset.text"):
                    add(row["asset.text_asset.text"], field_of(row.get("ad_group_ad_asset_view.field_type")), row)
                if row.get("asset.sitelink_asset.link_text"):
                    add(row["asset.sitelink_asset.link_text"], "sitelink_text", row)
                if row.get("asset.callout_asset.callout_text"):
                    add(row["asset.callout_asset.callout_text"], "callout", row)
                for t, _ in text_list(row.get("asset.structured_snippet_asset.values") or []):
                    add(t, "snippet_value", row)
            continue
        sample = "\n".join(text.splitlines()[:20])
        delim = max((",", "\t", ";"), key=sample.count)
        table = list(csv.reader(io.StringIO(text), delimiter=delim))
        start = 0
        for i, r in enumerate(table[:15]):
            cells = {c.strip().lower() for c in r}
            if "headline 1" in cells or cells & set(COLS["text"]) or any("responsive_search_ad" in c for c in cells):
                start = i
                break
        header = [h.strip() for h in table[start]] if table else []
        for r in table[start + 1:]:
            if not any(c.strip() for c in r) or any(c.strip().lower().startswith("total") for c in r[:3]):
                continue
            row = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
            lower = {k.lower(): v for k, v in row.items()}
            for i in range(1, 16):
                add(lower.get(f"headline {i}"), "headline", row, lower.get(f"headline {i} position", ""))
            for i in range(1, 5):
                add(lower.get(f"description {i}"), "description", row, lower.get(f"description {i} position", ""))
            for key, value in lower.items():
                if "responsive_search_ad" in key and "headline" in key:
                    for t, p in text_list(value):
                        add(t, "headline", row, p)
                elif "responsive_search_ad" in key and "description" in key:
                    for t, p in text_list(value):
                        add(t, "description", row, p)
            if pick(row, "text") and "headline 1" not in lower:
                add(pick(row, "text"), field_of(pick(row, "field")) or "headline", row)
    return rows_out


def summarize_existing(rows: list[dict]) -> list[dict]:
    """Per ad group and field: impressions, clicks, CTR, conversions, and serving share for each line."""
    groups: dict = {}
    for r in rows:
        if r["impressions"] is None:
            continue
        key = (r["ad_group"], r["field"], r["text"])
        g = groups.setdefault(key, {"ad_group": r["ad_group"], "field": r["field"], "text": r["text"],
                                    "impressions": 0.0, "clicks": 0.0, "conversions": 0.0})
        for m in ("impressions", "clicks", "conversions"):
            g[m] += r[m] or 0.0
    out = list(groups.values())
    top: dict = {}
    for g in out:
        k = (g["ad_group"], g["field"])
        top[k] = max(top.get(k, 0.0), g["impressions"])
    for g in out:
        k = (g["ad_group"], g["field"])
        g["ctr"] = g["clicks"] / g["impressions"] if g["impressions"] else None
        g["conv_rate"] = g["conversions"] / g["clicks"] if g["clicks"] else None
        g["serving_share"] = g["impressions"] / top[k] if top[k] else None
        g["low_serving"] = bool(g["serving_share"] is not None and g["serving_share"] < LOW_SERVING_SHARE
                                and g["conversions"] == 0)
    return sorted(out, key=lambda g: (g["ad_group"], g["field"], -g["impressions"]))


def load_keywords(path: str) -> list[dict]:
    """Positive keywords from a normalized CSV, a Google Ads keyword download, or an Editor export."""
    text = decode(Path(path).read_bytes())
    delim = max((",", "\t", ";"), key="\n".join(text.splitlines()[:20]).count)
    table = list(csv.reader(io.StringIO(text), delimiter=delim))
    start = next((i for i, r in enumerate(table[:15])
                  if {c.strip().lower() for c in r} & {"keyword", "search keyword"}), 0)
    header = [h.strip().lower() for h in table[start]] if table else []
    out = []
    for r in table[start + 1:]:
        low = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        kw = low.get("keyword") or low.get("search keyword") or ""
        criterion = (low.get("criterion type") or low.get("match_type") or "").lower()
        if not kw or kw.strip().lower().startswith("total") or kw.strip().startswith("-") \
                or low.get("is_negative", "").lower() == "true" or "negative" in criterion:
            continue
        out.append({"campaign": low.get("campaign", ""), "ad_group": low.get("ad_group") or low.get("ad group", ""),
                    "text": kw.strip().strip('[]"'), "conversions": num(low.get("conversions") or low.get("conv.")) or 0,
                    "clicks": num(low.get("clicks")) or 0})
    return out


# ---------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, level: str, where: str, message: str):
        entry = {"level": level, "where": where, "message": message}
        if entry not in self.items:
            self.items.append(entry)

    def level(self, name: str) -> list[dict]:
        return [i for i in self.items if i["level"] == name]


def as_items(values, kind: str) -> list[dict]:
    out = []
    for v in values or []:
        out.append({"text": v} if isinstance(v, str) else dict(v))
    return out


# ---------------------------------------------------------------- checks

def lint(report: Report, where: str, field: str, text: str, allow_caps: set[str]):
    label = LABELS[field]
    asset = field in ASSET_TEXT
    if text != text.strip():
        report.add("warning", where, f"{label} has leading or trailing spaces")
    if "  " in text:
        report.add("error", where, f"{label} has a double space (Google disallows extra spaces)")
    if re.search(r"\s[!?.,;:](?!\w)", text):
        report.add("warning", where, f"{label} has a space before punctuation")
    if REPEAT_PUNCT_RE.search(text):
        report.add("error", where, f"{label} repeats punctuation ('{REPEAT_PUNCT_RE.search(text).group(0)}'); "
                                   "Google's punctuation policy disallows it")
    if EMOJI_RE.search(text) or DECOR_RE.search(text):
        report.add("error", where, f"{label} has an emoji or decorative symbol; Google disallows them")
    if HALF_KATAKANA_RE.search(text):
        report.add("error", where, f"{label} has single-byte katakana, which Google disallows")
    if STAR_RE.search(text):
        report.add("warning", where, f"{label} uses a star symbol; Google reviews symbol use case by case, "
                                     "so write '4.9 stars' instead")
    if MARK_RE.search(text):
        report.add("warning", where, f"{label} uses a trademark symbol; keep it only if the landing page uses it too")
    if DECOR_ASTERISK_RE.search(text):
        report.add("error", where, f"{label} uses asterisks as decoration")
    elif "*" in text:
        report.add("warning", where, f"{label} has an asterisk; Google allows it only to flag a condition "
                                     "that is shown on the landing page")
    if SPACED_LETTERS_RE.search(text):
        report.add("error", where, f"{label} spells a word with gimmicky spacing or periods")
    if SUBST_SYMBOL_RE.search(text):
        report.add("error", where, f"{label} replaces letters with symbols ('{SUBST_SYMBOL_RE.search(text).group(0)}')")
    for m in SUBST_DIGIT_RE.finditer(text):
        if m.group(0).upper() not in allow_caps and m.group(0) not in allow_caps:
            report.add("warning", where, f"{label} mixes digits into a word ('{m.group(0)}'); "
                                         "fine for a model or brand name, not for replacing letters")
    rep = REPEAT_WORD_RE.search(text)
    if rep:
        report.add("error", where, f"{label} repeats a word ('{rep.group(0)}'); Google disallows gimmicky repetition")
    letters = re.findall(r"[A-Za-z][A-Za-z'\u2019]*", text)
    caps = [w for w in letters if len(w) >= 2 and w.isupper()]
    if len(letters) >= 2 and len(caps) == len(letters) and not all(w in allow_caps for w in caps):
        report.add("error", where, f"{label} is written in all capitals")
    else:
        for w in caps:
            if w in PROMO_CAPS and w not in allow_caps:
                report.add("error", where, f"{label} capitalizes '{w}' for emphasis; Google disallows "
                                           "gimmicky capitalization")
            elif len(w) >= 3 and w not in allow_caps and w not in ACRONYMS:
                report.add("warning", where, f"{label} has an all-caps word '{w}'; fine for an acronym, "
                                             "not for emphasis")
    for w in letters:
        runs = len(re.findall(r"[A-Z]+|[a-z]+", w))
        if len(w) >= 4 and runs >= 4 and max(len(r) for r in re.findall(r"[A-Z]+|[a-z]+", w)) <= 2 \
                and w not in allow_caps and w not in ODD_CASE_OK:
            report.add("warning", where, f"{label} has odd capitalization in '{w}'")
    if phone_spans(text):
        report.add("error", where, f"{label} contains a phone number; Google disallows phone numbers in ad text "
                                   "(use a call asset)")
    bangs = text.count("!")
    if asset and bangs:
        report.add("error", where, f"{label} has an exclamation mark; Google's {label.split()[0]} rules disallow it")
    elif field == "headline" and bangs:
        report.add("warning", where, "headline has an exclamation mark; Google has disapproved these in "
                                     "headlines, so drop it")
    elif field == "description" and bangs > 1:
        report.add("warning", where, "description has more than one exclamation mark")
    if asset and LEAD_PUNCT_RE.search(text):
        report.add("error", where, f"{label} starts with punctuation; Google disallows it for this asset")
    low = text.lower()
    if "click here" in low:
        report.add("warning", where, f"{label} says 'click here'; name the action instead")
    for tell in AI_TELLS:
        if re.search(r"\b" + re.escape(tell) + r"\b", low):
            report.add("warning", where, f"{label} uses the stock phrase '{tell}', which reads as generated")
    if "\u2014" in text:
        report.add("warning", where, f"{label} has an em dash, which reads as generated; use a comma or colon")


def phone_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in VANITY_RE.finditer(text)]
    for m in PHONE_CANDIDATE_RE.finditer(text):
        cand = m.group(0).strip()
        digits = re.sub(r"\D", "", cand)
        if ISO_DATE_RE.match(cand):
            continue
        if len(digits) >= 10 or (len(digits) >= 7 and re.search(r"\d{3}[\s.\-]\d{4}\b", cand)):
            spans.append(m.span())
    return spans


def phrase_in(phrase: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", text.lower()))


def jaccard(a: str, b: str) -> float:
    x, y = set(stem(w) for w in content_words(a)), set(stem(w) for w in content_words(b))
    return len(x & y) / len(x | y) if x and y else 0.0


def near_duplicates(report: Report, where: str, label: str, texts: list[str]):
    keys = [norm_key(t) for t in texts]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if not keys[i] or not keys[j]:
                continue
            if keys[i] == keys[j]:
                report.add("error", where, f"duplicate {label}: '{texts[i]}' and '{texts[j]}'")
            elif jaccard(texts[i], texts[j]) >= 0.8 or (len(keys[i]) >= 20 and keys[i][:20] == keys[j][:20]):
                report.add("warning", where, f"near-duplicate {label}s: '{texts[i]}' and '{texts[j]}'; "
                                             "they waste a slot and limit what Google can test")


def run(copy: dict, ctx: dict, claim_items: list[dict], existing: list[dict], keyword_rows: list[dict],
        landing_default: str | None, copy_dir: Path, today: dt.date) -> dict:
    report = Report()
    items = ctx["items"] + claim_items
    protected = ctx["protected"]
    competitors = ctx["competitors"]
    allow_caps = set(ACRONYMS)
    for term in protected:
        allow_caps.update(re.findall(r"[A-Za-z0-9+&]+", term))
    for term in [i["text"] for i in items] + [copy.get("campaign", "")]:
        allow_caps.update(w for w in re.findall(r"[A-Za-z0-9+&]+", term) if w.isupper() or re.search(r"\d", w))
    assets: list[dict] = []
    claims_out: list[dict] = []
    coverage: list[dict] = []
    pins_out: list[dict] = []
    campaign = copy.get("campaign", "")

    def check_text(where: str, field: str, raw: str, group: dict | None, meta: dict) -> dict:
        rendered, notes = render(raw)
        for level, msg in notes:
            report.add(level, where, msg)
        n = width(rendered)
        limit = LIMITS[field]
        if n > limit:
            report.add("error", where, f"{LABELS[field]} is {n} characters, over {limit}: '{raw}'")
        if not rendered.strip():
            report.add("error", where, f"{LABELS[field]} is empty")
        lint(report, where, field, rendered, allow_caps)
        for phrase in ctx["avoid"]:
            if phrase_in(phrase, rendered):
                report.add("error", where, f"uses '{phrase}', which the context file's copy rules say to avoid")
        for name in competitors:
            if phrase_in(name, rendered) and not any(phrase_in(name, p) for p in protected):
                if ctx["competitors_allowed"]:
                    report.add("warning", where, f"names competitor '{name}'; allowed by the context file, "
                                                 "but it can draw trademark complaints")
                else:
                    report.add("error", where, f"names competitor '{name}'; the context file's competitor "
                                               f"policy says: {ctx['competitor_policy']}")
        for term in ctx["unwanted"]:
            if phrase_in(term, rendered):
                report.add("warning", where, f"mentions '{term}', listed under Terms we don't want")
        kw_text = " ".join(k["text"] for k in (group or {}).get("_keywords", []))
        found = []
        for claim in find_claims(rendered, protected):
            status, item = judge_claim(claim, items, today)
            if status == "unapproved" and "number" in claim and claim["category"] == "number" \
                    and phrase_in(claim["text"], kw_text):
                status = "from keyword"
            entry = {"where": where, "text": claim["text"], "category": claim["category"], "status": status,
                     "item": item["text"] if item else "", "source": item["source"] if item else "",
                     "kind": item["kind"] if item else ""}
            found.append(entry)
            claims_out.append(entry)
            if status == "approved":
                if item["end"] and (item["end"] - today).days <= ENDING_SOON_DAYS:
                    report.add("warning", where, f"'{claim['text']}' relies on an offer that ends {item['end']}; "
                                                 "plan to pause or edit the ad by then")
                if claim["category"] in NEEDS_PAGE_PROOF:
                    report.add("warning", where, f"'{claim['text']}' is a {claim['category']} claim; Google has "
                                                 "required visible third-party proof for these, so check the "
                                                 "landing page shows the source")
            elif status == "from keyword":
                report.add("warning", where, f"'{claim['text']}' comes from a keyword, not an approved claim; "
                                             "confirm it's true for this business or add it to approved claims")
            elif status == "needs confirmation":
                report.add("error", where, f"'{claim['text']}' ({claim['category']}) matches an item still marked "
                                           f"confirm: '{item['text']}'. Get it confirmed first")
            elif status == "expired":
                report.add("error", where, f"'{claim['text']}' ({claim['category']}) matches an offer that ended "
                                           f"{item['end']}: '{item['text']}'")
            else:
                near = closest_item(rendered, items)
                hint = f" Closest approved item: '{near['text']}'." if near else ""
                report.add("error", where, f"'{claim['text']}' ({claim['category']}) is not an approved claim.{hint} "
                                           "Use approved wording, drop it, or get it approved")
        rec = {"where": where, "field": field, "text": raw, "rendered": rendered, "chars": n, "limit": limit,
               "claims": found}
        rec.update(meta)
        assets.append(rec)
        return rec

    # Ad groups and RSAs.
    ad_groups = copy.get("ad_groups") or []
    if not ad_groups and not any(copy.get(k) for k in ("sitelinks", "callouts", "snippets")):
        report.add("error", "-", "the copy file has no ad_groups and no assets")
    all_ad_text: dict[str, list[str]] = {}
    for g_index, group in enumerate(ad_groups, 1):
        gname = group.get("ad_group") or f"ad group {g_index}"
        kws = []
        for k in group.get("keywords") or []:
            kws.append({"text": k, "conversions": 0, "clicks": 0} if isinstance(k, str) else
                       {"text": k.get("text", ""), "conversions": k.get("conversions") or 0, "clicks": k.get("clicks") or 0})
        for row in keyword_rows:
            if row["ad_group"].strip().lower() == gname.strip().lower() and \
                    (not row["campaign"] or not campaign or row["campaign"].strip().lower() == campaign.strip().lower()):
                if not any(k["text"].lower() == row["text"].lower() for k in kws):
                    kws.append(row)
        kws.sort(key=lambda k: (-(k["conversions"] or 0), -(k["clicks"] or 0)))
        group["_keywords"] = kws
        landing_file = group.get("landing_page_file")
        landing = None
        if landing_file:
            p = Path(landing_file)
            p = p if p.is_absolute() else copy_dir / p
            landing = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
            if landing is None:
                report.add("warning", gname, f"landing page file not found: {landing_file}")
        elif landing_default:
            landing = landing_default
        group_texts: list[str] = []
        rsas = group.get("rsas") or []
        if len(rsas) > MAX_ENABLED_RSAS:
            report.add("warning", gname, f"{len(rsas)} RSAs for one ad group; Google allows {MAX_ENABLED_RSAS} "
                                         "enabled per ad group")
        enabled_existing = {r["ad_id"] for r in existing if r["ad_group"].strip().lower() == gname.lower()
                            and r["ad_id"] and r["status"] in ("enabled", "active", "eligible")}
        if enabled_existing and len(enabled_existing) + len(rsas) > MAX_ENABLED_RSAS:
            report.add("warning", gname, f"the ad group already has {len(enabled_existing)} enabled RSA(s); with "
                                         f"{len(rsas)} new, pause one before enabling so it stays at "
                                         f"{MAX_ENABLED_RSAS} or fewer")
        headline_sets = []
        for r_index, rsa in enumerate(rsas, 1):
            rid = rsa.get("id") or f"rsa{r_index}"
            base = f"{gname} / {rid}"
            heads = as_items(rsa.get("headlines"), "headline")
            descs = as_items(rsa.get("descriptions"), "description")
            if not HEADLINES[0] <= len(heads) <= HEADLINES[1]:
                report.add("error", base, f"needs {HEADLINES[0]} to {HEADLINES[1]} headlines, has {len(heads)}")
            elif len(heads) < HEADLINES_GOOD:
                report.add("warning", base, f"{len(heads)} headlines; this skill aims for {HEADLINES_GOOD} or more "
                                            "unique headlines so Google has combinations to test")
            if not DESCRIPTIONS[0] <= len(descs) <= DESCRIPTIONS[1]:
                report.add("error", base, f"needs {DESCRIPTIONS[0]} to {DESCRIPTIONS[1]} descriptions, has {len(descs)}")
            recs_h, recs_d = [], []
            for i, h in enumerate(heads, 1):
                recs_h.append(check_text(f"{base} / headline {i}", "headline", str(h.get("text", "")), group,
                                         {"group": gname, "rsa": rid, "index": i, "pin": h.get("pin"),
                                          "role": h.get("role", ""), "source": h.get("source", "")}))
            for i, d in enumerate(descs, 1):
                recs_d.append(check_text(f"{base} / description {i}", "description", str(d.get("text", "")), group,
                                         {"group": gname, "rsa": rid, "index": i, "pin": d.get("pin"),
                                          "role": d.get("role", ""), "source": d.get("source", "")}))
            for key in ("path1", "path2"):
                value = str(rsa.get(key) or "")
                if value:
                    check_text(f"{base} / {key}", "path", value, group, {"group": gname, "rsa": rid, "index": key})
                    if " " in value.strip():
                        report.add("warning", f"{base} / {key}", "path has a space; use a hyphen")
                    if "/" in value:
                        report.add("error", f"{base} / {key}", "path can't contain '/'")
            if rsa.get("path2") and not rsa.get("path1"):
                report.add("error", base, "path2 is set without path1; Google only accepts path2 when path1 is set")
            url = str(rsa.get("final_url") or group.get("final_url") or copy.get("final_url") or "")
            if not url:
                report.add("error", base, "no final_url")
            elif not url.startswith(("http://", "https://")):
                report.add("error", base, f"final_url must start with https://: '{url}'")
            elif url.startswith("http://"):
                report.add("warning", base, "final_url uses http://; use https:// if the site supports it")
            rsa["_url"] = url
            near_duplicates(report, base, "headline", [r["rendered"] for r in recs_h])
            near_duplicates(report, base, "description", [r["rendered"] for r in recs_d])
            group_texts += [r["rendered"] for r in recs_h + recs_d]
            headline_sets.append((rid, {norm_key(r["rendered"]) for r in recs_h}))

            # Pinning.
            pinned = {}
            for r, field, allowed in [(r, "headline", (1, 2, 3)) for r in recs_h] + \
                                     [(r, "description", (1, 2)) for r in recs_d]:
                pin = r.get("pin")
                if pin in (None, "", 0):
                    continue
                try:
                    pin = int(str(pin).lower().replace("headline_", "").replace("description_", ""))
                except ValueError:
                    pin = -1
                if pin not in allowed:
                    report.add("error", r["where"], f"{field} pin must be one of {allowed}, not '{r.get('pin')}'")
                    continue
                pinned.setdefault((field, pin), []).append(r)
            n_pinned_h = sum(len(v) for (f, _), v in pinned.items() if f == "headline")
            summary = {"rsa": base, "pinned_headlines": n_pinned_h,
                       "pinned_descriptions": sum(len(v) for (f, _), v in pinned.items() if f == "description"),
                       "positions": {f"{f[0].upper()}{p}": len(v) for (f, p), v in sorted(pinned.items())}}
            pins_out.append(summary)
            for (field, pos), rs in pinned.items():
                if len(rs) == 1:
                    report.add("warning", base, f"only one {field} pinned to position {pos}; that position never "
                                                "varies. Google suggests 2 or 3 options per pinned position")
                if (field, pos) in (("headline", 3), ("description", 2)):
                    for r in rs:
                        if r.get("role") == "disclaimer":
                            report.add("warning", r["where"], f"disclaimer pinned to {field} position {pos}, which "
                                                              "isn't guaranteed to show; use Headline 1 or 2 or "
                                                              "Description 1")
            heavy = []
            if heads and n_pinned_h > len(heads) / 2:
                heavy.append(f"{n_pinned_h} of {len(heads)} headlines pinned")
            if all(("headline", p) in pinned for p in (1, 2, 3)):
                heavy.append("all three headline positions pinned")
            if heads and n_pinned_h == len(heads):
                heavy.append("every headline pinned, so unpinned variety is gone")
            if heavy:
                report.add("warning", base, "heavy pinning (" + "; ".join(heavy) + "); Google says pinning isn't "
                                            "recommended for most advertisers and it lowers Ad Strength")

            # Coverage.
            cov = {"rsa": base}
            h_words = [set(stem(w) for w in content_words(r["rendered"])) for r in recs_h]
            d_words = [set(stem(w) for w in content_words(r["rendered"])) for r in recs_d]
            if kws:
                top = kws[:3]
                hits = []
                for k in top:
                    kw_words = [stem(w) for w in content_words(k["text"])]
                    if not kw_words:
                        continue
                    need = len(kw_words) - (1 if width(k["text"]) > LIMITS["headline"] and len(kw_words) > 1 else 0)
                    in_h = [i for i, hw in enumerate(h_words, 1) if sum(word_in(w, hw) for w in kw_words) >= need]
                    in_d = any(all(word_in(w, dw) for w in kw_words) for dw in d_words)
                    if in_h or (width(k["text"]) > LIMITS["headline"] and in_d):
                        hits.append(f"'{k['text']}'" + (f" (H{in_h[0]})" if in_h else " (description)"))
                cov["keyword"] = ("pass" if hits else "warn",
                                  f"{len(hits)} of {len(top)} top keywords in a headline" +
                                  (": " + ", ".join(hits) if hits else ""))
            else:
                cov["keyword"] = ("missing", "no keywords given (add them to the copy file or pass --keywords)")
            rsa_claims = [c for r in recs_h + recs_d for c in r["claims"] if c["status"] == "approved"]
            for kind_name, kinds in (("offer", ("offer", "price")), ("proof", ("proof",))):
                have_items = any(i["kind"] in kinds and not i["confirm"] for i in items)
                used = sorted({c["text"].lower(): c["text"] for c in rsa_claims if c["kind"] in kinds}.values(),
                              key=str.lower)
                if used:
                    shown = ", ".join(f"'{u}'" for u in used[:6]) + (f", and {len(used) - 6} more" if len(used) > 6 else "")
                    cov[kind_name] = ("pass", f"{len(used)} approved: {shown}")
                elif have_items:
                    cov[kind_name] = ("warn", f"no approved {kind_name} used")
                else:
                    cov[kind_name] = ("missing", f"no approved {kind_name} in the context file or claims file")
            cta_h = sum(1 for r in recs_h if set(words(r["rendered"])) & CTA_WORDS)
            cta_d = sum(1 for r in recs_d if set(words(r["rendered"])) & CTA_WORDS)
            cov["cta"] = ("pass" if cta_h and cta_d else "warn", f"{cta_h} headlines and {cta_d} descriptions with a call to action")
            for key in ("keyword", "offer", "proof", "cta"):
                if cov[key][0] == "warn":
                    report.add("warning", base, f"coverage: {key}: {cov[key][1]}")
            coverage.append(cov)

            # Required disclaimers.
            for item in items:
                if item["kind"] != "disclaimer":
                    continue
                dw = [stem(w) for w in content_words(item["text"])]
                carried = [r for r in recs_d if dw and sum(word_in(w, set(stem(x) for x in content_words(r["rendered"])))
                                                           for w in dw) >= 0.6 * len(dw)]
                if not carried:
                    report.add("warning", base, f"the context lists a required disclaimer ('{item['text']}') that no "
                                                "description carries; if it applies, add it as a description pinned "
                                                "to Description 1, or use a text disclaimer in AI Max campaigns")

            # Landing page checks for offers and superlatives.
            if landing:
                page = landing.lower()
                for c in [c for r in recs_h + recs_d for c in r["claims"]]:
                    if c["status"] != "approved":
                        continue
                    if c["kind"] in ("offer", "price"):
                        nums = re.findall(r"\d+(?:\.\d+)?", c["text"].replace(",", ""))
                        if nums and not all(n in page.replace(",", "") for n in nums):
                            report.add("warning", c["where"], f"offer '{c['text']}' isn't on the landing page text; "
                                                              "Google disapproves offers the page doesn't show")
                        elif not nums and not phrase_in(c["text"], page):
                            report.add("warning", c["where"], f"'{c['text']}' isn't on the landing page text; check "
                                                              "the page shows this offer")
                    if c["category"] in NEEDS_PAGE_PROOF and not phrase_in(c["text"], page):
                        report.add("warning", c["where"], f"'{c['text']}' doesn't appear on the landing page, so the "
                                                          "proof Google expects isn't visible there")

            # Existing ads: duplicates and the memorization check.
            same_group = [e for e in existing if e["field"] in ("headline", "description") and
                          (not e["ad_group"] or e["ad_group"].strip().lower() == gname.strip().lower())]
            known = {(e["field"], norm_key(e["text"])) for e in same_group}
            for r in recs_h + recs_d:
                if (r["field"], norm_key(r["rendered"])) in known and r.get("source") != "kept":
                    report.add("warning", r["where"], f"'{r['rendered']}' is already running in this ad group; mark "
                                                      "it source 'kept' if that's intended, or write something new")
            if recs_h and same_group and all(("headline", norm_key(r["rendered"])) in known for r in recs_h):
                report.add("warning", base, "every headline already runs in this ad group, so this RSA tests nothing new")
        for i in range(len(headline_sets)):
            for j in range(i + 1, len(headline_sets)):
                a, b = headline_sets[i][1], headline_sets[j][1]
                if a and b and len(a & b) > min(len(a), len(b)) / 2:
                    report.add("warning", gname, f"{headline_sets[i][0]} and {headline_sets[j][0]} share "
                                                 f"{len(a & b)} headlines; give each RSA its own angle")
        all_ad_text[gname] = group_texts

    # Assets: sitelinks, callouts, snippets, at each level.
    scopes = [("campaign", None, copy)] + [("ad_group", g, g) for g in ad_groups]
    domain = None
    first_url = next((r.get("_url") for g in ad_groups for r in (g.get("rsas") or []) if r.get("_url")), "")
    if first_url:
        domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", first_url).split("/")[0].lower())
    for kind in ("sitelinks", "callouts", "snippets"):
        for a in as_items(copy.get(kind), kind):
            if (a.get("level") or "campaign") not in ("account", "campaign"):
                report.add("error", f"{kind}", f"top-level {kind} take level 'account' or 'campaign', not "
                                               f"'{a.get('level')}'; put ad group assets inside the ad group")
    existing_assets = {(e["field"], norm_key(e["text"])) for e in existing
                       if e["field"] in ("sitelink_text", "callout", "snippet_value")}
    for scope, group, holder in scopes:
        gname = group.get("ad_group") if group else None
        for level_name in ("account", "campaign") if scope == "campaign" else ("ad_group",):
            sls = [s for s in as_items(holder.get("sitelinks"), "sitelink")
                   if scope != "campaign" or (s.get("level") or "campaign") == level_name]
            cos = [c for c in as_items(holder.get("callouts"), "callout")
                   if scope != "campaign" or (c.get("level") or "campaign") == level_name]
            sns = [s for s in as_items(holder.get("snippets"), "snippet")
                   if scope != "campaign" or (s.get("level") or "campaign") == level_name]
            if not (sls or cos or sns):
                continue
            where0 = {"account": "account", "campaign": f"campaign {campaign}"}.get(level_name, f"ad group {gname}")
            ad_text = (all_ad_text.get(gname, []) if gname else [t for ts in all_ad_text.values() for t in ts])
            link_texts = []
            urls = []
            for i, s in enumerate(sls, 1):
                w = f"{where0} / sitelink {i}"
                rec = check_text(w, "sitelink_text", str(s.get("link_text", "")), group,
                                 {"group": gname, "level": level_name, "index": i, "kind": "sitelink"})
                link_texts.append(rec["rendered"])
                if ("sitelink_text", norm_key(rec["rendered"])) in existing_assets:
                    report.add("warning", w, f"a sitelink '{rec['rendered']}' already exists in the account; "
                                             "reuse it rather than adding a copy")
                d1, d2 = str(s.get("description1") or ""), str(s.get("description2") or "")
                if bool(d1) != bool(d2):
                    report.add("error", w, "sitelink needs both description lines or neither (Google requires the pair)")
                for key, val in (("description1", d1), ("description2", d2)):
                    if val:
                        check_text(f"{w} / {key}", "sitelink_description", val, group,
                                   {"group": gname, "level": level_name, "index": i, "kind": "sitelink_" + key})
                if d1 and d2 and norm_key(d1) == norm_key(d2):
                    report.add("error", w, "sitelink description lines are the same")
                url = str(s.get("final_url") or "")
                urls.append(url)
                if not url:
                    report.add("error", w, "sitelink has no final_url")
                elif not url.startswith(("http://", "https://")):
                    report.add("error", w, f"sitelink final_url must start with https://: '{url}'")
                else:
                    d = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0].lower())
                    if domain and d != domain:
                        report.add("warning", w, f"sitelink goes to {d}, not the ad's domain {domain}; Google allows "
                                                 "other domains only in limited cases")
                    if url.rstrip("/") in {(r.get("_url") or "").rstrip("/") for g in ad_groups for r in g.get("rsas") or []}:
                        report.add("warning", w, "sitelink goes to the ad's own landing page; send it to a different page")
                for t in ad_text:
                    if norm_key(t) == norm_key(rec["rendered"]):
                        report.add("warning", w, f"sitelink text repeats a headline or description: '{t}'")
            if sls:
                lt = [norm_key(t) for t in link_texts]
                for t in sorted({t for t in lt if lt.count(t) > 1}):
                    report.add("error", f"{where0} / sitelinks", f"link text '{t}' is used more than once; Google "
                                                                 "disallows reusing link text")
                for u in sorted({u for u in urls if u and urls.count(u) > 1}):
                    report.add("warning", f"{where0} / sitelinks", f"several sitelinks go to {u}")
                if len(sls) < SITELINKS_TO_SHOW:
                    report.add("warning", f"{where0} / sitelinks", f"{len(sls)} sitelink(s); Google needs at least "
                                                                   f"{SITELINKS_TO_SHOW} to show any")
                elif len(sls) < SITELINKS_GOOD:
                    report.add("warning", f"{where0} / sitelinks", f"{len(sls)} sitelinks; Google suggests at least "
                                                                   f"{SITELINKS_GOOD}, and 6 with descriptions for busy ad groups")
                if len(sls) > SITELINKS_MAX:
                    report.add("warning", f"{where0} / sitelinks", f"{len(sls)} sitelinks; {SITELINKS_MAX} is the most per level")
            callout_texts = []
            for i, c in enumerate(cos, 1):
                w = f"{where0} / callout {i}"
                rec = check_text(w, "callout", str(c.get("text", "")), group,
                                 {"group": gname, "level": level_name, "index": i, "kind": "callout"})
                callout_texts.append(rec["rendered"])
                if ("callout", norm_key(rec["rendered"])) in existing_assets:
                    report.add("warning", w, f"the callout '{rec['rendered']}' already exists in the account")
                for t in ad_text + link_texts:
                    if norm_key(rec["rendered"]) and phrase_in(norm_key(rec["rendered"]), norm_key(t)):
                        report.add("error", w, f"callout '{rec['rendered']}' repeats ad or sitelink text ('{t}'); "
                                               "Google's callout rules disallow it")
                        break
            if cos:
                near_duplicates(report, f"{where0} / callouts", "callout", callout_texts)
                if len(cos) < CALLOUTS_GOOD:
                    report.add("warning", f"{where0} / callouts", f"{len(cos)} callouts; this skill aims for "
                                                                  f"{CALLOUTS_GOOD} or more")
            all_values = []
            for i, s in enumerate(sns, 1):
                w = f"{where0} / snippet {i}"
                header = str(s.get("header", ""))
                match = [h for h in SNIPPET_HEADERS if h.lower() == header.strip().lower()]
                if not match:
                    report.add("error", w, f"'{header}' isn't a Google snippet header; use one of: "
                                           + ", ".join(SNIPPET_HEADERS))
                values = [str(v) for v in s.get("values") or []]
                if not SNIPPET_VALUES[0] <= len(values) <= SNIPPET_VALUES[1]:
                    report.add("error", w, f"needs {SNIPPET_VALUES[0]} to {SNIPPET_VALUES[1]} values, has {len(values)}")
                for j, v in enumerate(values, 1):
                    rec = check_text(f"{w} / value {j}", "snippet_value", v, group,
                                     {"group": gname, "level": level_name, "index": f"{i}.{j}", "kind": "snippet",
                                      "header": header})
                    all_values.append(rec["rendered"])
                    if re.search(r"\b(free|sale|discounts?|deals?|offers?|save|savings|cheap\w*|coupons?|promo\w*|"
                                 r"clearance|limited)\b|%|[$\u20ac\u00a3]", v, re.IGNORECASE):
                        report.add("error", f"{w} / value {j}", f"snippet value '{v}' is promotional; Google's snippet "
                                                                "rules allow only plain items")
                    if re.search(r",|\s&\s|\band\b|/", v):
                        report.add("warning", f"{w} / value {j}", f"snippet value '{v}' may hold more than one item; "
                                                                  "put each item in its own value")
            if sns:
                keys = [norm_key(v) for v in all_values]
                for t in sorted({k for k in keys if k and keys.count(k) > 1}):
                    report.add("error", f"{where0} / snippets", f"snippet value '{t}' repeats; Google disallows "
                                                                "repeated values in or across headers")

    if not ctx.get("path") and not claim_items:
        report.add("warning", "-", "no context file or claims file was given, so every claim counts as unapproved")
    return {"report": report, "assets": assets, "claims": claims_out, "coverage": coverage, "pins": pins_out,
            "existing": summarize_existing(existing), "items": items}


# ---------------------------------------------------------------- output

def md(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_markdown(path: str, copy: dict, result: dict):
    report = result["report"]
    by_where: dict = {}
    for i in report.items:
        by_where.setdefault(i["where"], []).append(i["level"])

    def status(where_prefix: str) -> str:
        levels = [l for w, ls in by_where.items() if w == where_prefix or w.startswith(where_prefix + " / ") for l in ls]
        e, w = levels.count("error"), levels.count("warning")
        return "ok" if not (e or w) else ", ".join(x for x in (f"{e} error" if e else "", f"{w} warning" if w else "") if x)

    def claims_cell(rec) -> str:
        return "; ".join(f"{c['text']} ({c['status']})" for c in rec["claims"]) or ""

    lines = [f"# Ad copy: {md(copy.get('name', ''))}", "",
             f"Campaign: {md(copy.get('campaign', ''))}. Character counts and checks come from check_ad_copy.py.", ""]
    assets = result["assets"]
    for group in copy.get("ad_groups") or []:
        gname = group.get("ad_group", "")
        lines += [f"## Ad group: {md(gname)}", ""]
        for r_index, rsa in enumerate(group.get("rsas") or [], 1):
            rid = rsa.get("id") or f"rsa{r_index}"
            base = f"{gname} / {rid}"
            p1, p2 = rsa.get("path1") or "", rsa.get("path2") or ""
            lines += [f"### {md(rid)}", "", f"Final URL: {md(rsa.get('_url', ''))}  ",
                      f"Display path: /{md(p1)}" + (f"/{md(p2)}" if p2 else "") +
                      f" ({width(p1)}, {width(p2)} of 15 characters)", ""]
            for field, title in (("headline", "Headline"), ("description", "Description")):
                lines += [f"| # | {title} | Chars | Role | Pin | Claims | Check |", "|---|---|---|---|---|---|---|"]
                for rec in [a for a in assets if a.get("group") == gname and a.get("rsa") == rid and a["field"] == field]:
                    lines.append(f"| {rec['index']} | {md(rec['text'])} | {rec['chars']}/{rec['limit']} | "
                                 f"{md(rec.get('role') or '')} | {md(rec.get('pin') or '')} | {md(claims_cell(rec))} | "
                                 f"{status(rec['where'])} |")
                lines.append("")
            cov = next((c for c in result["coverage"] if c["rsa"] == base), None)
            if cov:
                lines += ["| Coverage | Result | Detail |", "|---|---|---|"]
                for key in ("keyword", "offer", "proof", "cta"):
                    lines.append(f"| {key} | {cov[key][0]} | {md(cov[key][1])} |")
                lines.append("")
    sl = [a for a in assets if a.get("kind") == "sitelink"]
    if sl:
        lines += ["## Sitelinks", "", "| Level | Link text | Chars | Description 1 | Chars | Description 2 | Chars | Check |",
                  "|---|---|---|---|---|---|---|---|"]
        for rec in sl:
            d1 = next((a for a in assets if a.get("kind") == "sitelink_description1" and a["where"].startswith(rec["where"] + " /")), None)
            d2 = next((a for a in assets if a.get("kind") == "sitelink_description2" and a["where"].startswith(rec["where"] + " /")), None)
            lines.append(f"| {md(rec['level'] if rec['level'] != 'ad_group' else 'ad group ' + str(rec['group']))} | "
                         f"{md(rec['text'])} | {rec['chars']}/25 | {md(d1['text'] if d1 else '')} | "
                         f"{(str(d1['chars']) + '/35') if d1 else ''} | {md(d2['text'] if d2 else '')} | "
                         f"{(str(d2['chars']) + '/35') if d2 else ''} | {status(rec['where'])} |")
        lines.append("")
    co = [a for a in assets if a.get("kind") == "callout"]
    if co:
        lines += ["## Callouts", "", "| Level | Callout | Chars | Check |", "|---|---|---|---|"]
        for rec in co:
            lines.append(f"| {md(rec['level'])} | {md(rec['text'])} | {rec['chars']}/25 | {status(rec['where'])} |")
        lines.append("")
    sn = [a for a in assets if a.get("kind") == "snippet"]
    if sn:
        lines += ["## Structured snippets", "", "| Level | Header | Value | Chars | Check |", "|---|---|---|---|---|"]
        for rec in sn:
            lines.append(f"| {md(rec['level'])} | {md(rec.get('header', ''))} | {md(rec['text'])} | {rec['chars']}/25 | "
                         f"{status(rec['where'])} |")
        lines.append("")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def pct(x) -> str:
    return "MISSING" if x is None else f"{x * 100:.1f}%"


def print_existing(summary: list[dict]):
    if not summary:
        print("\nExisting assets: no impression data in the files, so no performance summary")
        return
    print("\nExisting assets (metrics overlap across lines, so compare lines, never add them up):")
    for g in summary:
        flag = "  low serving, 0 conversions" if g["low_serving"] else ""
        print(f"  [{g['ad_group'] or '-'} / {g['field']}] '{g['text']}': {g['impressions']:g} impr, "
              f"{g['clicks']:g} clicks, CTR {pct(g['ctr'])}, {g['conversions']:g} conv, "
              f"serving share {pct(g['serving_share'])}{flag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("copy", nargs="?", help="the copy file; leave out to summarize --existing only")
    parser.add_argument("--context")
    parser.add_argument("--claims", action="append", default=[])
    parser.add_argument("--existing", nargs="*", default=[])
    parser.add_argument("--keywords")
    parser.add_argument("--landing-page")
    parser.add_argument("--today")
    parser.add_argument("--markdown")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.copy:
        if not args.existing:
            parser.error("give a copy file, or --existing files to summarize")
        rows = load_existing(args.existing)
        summary = summarize_existing(rows)
        if args.json:
            print(json.dumps({"existing_lines": len(rows), "summary": summary}, indent=2))
            return 0
        print(f"Existing lines read: {len(rows)} ({len({(r['field'], r['text']) for r in rows})} unique)")
        print_existing(summary)
        return 0
    copy_path = Path(args.copy)
    copy = json.loads(copy_path.read_text(encoding="utf-8-sig"))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    ctx = {"items": [], "protected": [], "unwanted": [], "competitors": [], "competitors_allowed": False,
           "competitor_policy": "MISSING", "avoid": [], "use": [], "restricted": "", "path": None}
    notes = []
    if args.context:
        if Path(args.context).exists():
            ctx = parse_context(args.context)
        else:
            notes.append(f"context file not found: {args.context}")
    claim_items = []
    for path in args.claims:
        claim_items += parse_claims_file(path)
    existing = load_existing(args.existing) if args.existing else []
    keyword_rows = load_keywords(args.keywords) if args.keywords else []
    landing = Path(args.landing_page).read_text(encoding="utf-8", errors="replace") if args.landing_page else None

    result = run(copy, ctx, claim_items, existing, keyword_rows, landing, copy_path.parent, today)
    report = result["report"]
    for n in notes:
        report.add("warning", "-", n)
    if ctx.get("restricted") and not skip_value(ctx["restricted"]):
        report.add("warning", "-", f"restricted category in the context file: {ctx['restricted']}; claims about "
                                   "outcomes need extra review under Google's policies for that category")
    if args.markdown:
        write_markdown(args.markdown, copy, result)

    if args.json:
        out = {k: v for k, v in result.items() if k not in ("report", "items")}
        out["errors"] = report.level("error")
        out["warnings"] = report.level("warning")
        print(json.dumps(out, indent=2, default=str))
        return 1 if report.level("error") else 0

    items = result["items"]
    groups = copy.get("ad_groups") or []
    n_rsa = sum(len(g.get("rsas") or []) for g in groups)
    kinds = {}
    for i in items:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print(f"Copy file: {copy.get('name', args.copy)} ({len(groups)} ad group(s), {n_rsa} RSA(s), "
          f"{sum(1 for a in result['assets'] if a.get('kind') == 'sitelink')} sitelinks, "
          f"{sum(1 for a in result['assets'] if a.get('kind') == 'callout')} callouts, "
          f"{len({(a['where'].rsplit(' / value', 1)[0]) for a in result['assets'] if a.get('kind') == 'snippet'})} snippet sets)")
    if ctx.get("path"):
        print(f"Context: {ctx['path']}: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) +
              f"; {sum(1 for i in items if i['confirm'])} still marked confirm; "
              f"{sum(1 for i in items if i['end'] and i['end'] < today)} past their end date")
    else:
        print("Context: none given")
    print(f"\nErrors: {len(report.level('error'))}")
    for i in report.level("error"):
        print(f"  [{i['where']}] {i['message']}")
    print(f"\nWarnings: {len(report.level('warning'))}")
    for i in report.level("warning"):
        print(f"  [{i['where']}] {i['message']}")
    print("\nCoverage:")
    for c in result["coverage"]:
        print(f"  [{c['rsa']}] " + "; ".join(f"{k}: {c[k][0]} ({c[k][1]})" for k in ("keyword", "offer", "proof", "cta")))
    print("\nPins:")
    for p in result["pins"]:
        print(f"  [{p['rsa']}] " + (", ".join(f"{k} x{v}" for k, v in p["positions"].items()) or "none"))
    print(f"\nClaims found: {len(result['claims'])}")
    for c in result["claims"]:
        detail = f" -> '{c['item']}' ({c['source']})" if c["item"] else ""
        print(f"  [{c['where']}] '{c['text']}' {c['category']}: {c['status']}{detail}")
    if result["existing"]:
        print_existing(result["existing"])
    if args.markdown:
        print(f"\nwrote {args.markdown}")
    return 1 if report.level("error") else 0


if __name__ == "__main__":
    sys.exit(main())
