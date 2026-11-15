#!/usr/bin/env python3
# Adapted in part from n_gram_analysis.py and negatives.py in thalesholleben/skill-google-ads (https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors).
"""Review a Google Ads search terms report and propose negatives and keyword promotions.

Every number comes from this script. It reads CSVs written by normalize.py and:

  1. Totals each search term per campaign and per ad group, and 1 to 3 word
     n-grams inside the first 16 words (the part of a search negatives see).
  2. Tests zero-conversion terms and n-grams against the break-even conversion
     rate (CPC divided by break-even CPA). A term is only called wasted when its
     clicks rule out converting at break-even at 95% confidence. Without
     economics it falls back to labeled fixed defaults (Nils Rooijmans for
     terms, Adalysis for n-grams).
  3. Turns "Terms we don't want" from the account context and an optional
     intent file (clear mismatches judged against the offer) into candidates.
  4. Checks every candidate against existing negatives at all levels, live
     positive keywords, converting search terms (window plus an optional longer
     history), and the context's protected terms. A candidate that fails at
     campaign level is retried at ad group level; one that fails everywhere is
     reported, never proposed.
  5. Proposes converting terms as exact keywords (2 or more conversions at or
     under break-even CPA), lists what to watch with the clicks still needed,
     and flags converting terms the data shows are losing money for review.

Usage:
  python3 review_terms.py --search-terms ST.csv [ST2.csv ...] --window 2026-10-18:2026-11-14
      [--campaigns campaigns.csv] [--keywords keywords.csv] [--negatives neg.csv ...]
      [--list-attachments list_campaigns.csv] [--history converting_terms.csv ...]
      [--context .agents/google-ads-context.md] [--intent intent.csv]
      [--breakeven-cpa N | --target-cpa N | --breakeven-roas N | --target-roas N]
      [--conversion-lag DAYS] [--confidence 0.95] [--actions-per-click 1]
      [--shared-list "List name"] [--list-campaigns "Campaign A,Campaign B"]
      [--currency USD] [--today YYYY-MM-DD] --out FOLDER

Writes to FOLDER: review.md, terms.csv, ngrams.csv, proposals.csv, rejected.csv.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import sys
import unicodedata
from collections import OrderedDict, defaultdict
from pathlib import Path

MAX_QUERY_WORDS = 16          # Google ignores a broad or phrase negative past the 16th word of a search
KEYWORD_MAX_CHARS, KEYWORD_MAX_WORDS = 80, 10
NO_NEGATIVES = {"demand_gen": "Demand Gen campaigns don't accept negative keywords",
                "display": "Display campaigns use negative keywords as topic exclusions, not search terms",
                "video": "Video campaigns use negative keywords as topic exclusions, not search terms"}
NO_AD_GROUPS = {"performance_max"}
AI_MAX_SOURCES = {"ai_max_keywordless", "ai_max_broad_match"}
# Function words are never proposed as negatives on their own.
STOPWORDS = {"a", "an", "the", "for", "to", "of", "in", "on", "at", "by", "with", "and", "or", "near", "me",
             "my", "i", "you", "your", "is", "are", "be", "do", "does", "from", "it", "this", "that", "vs"}
# Fixed defaults, used only when no break-even or target is available.
FIXED_TERM = {"clicks": 60, "cost": 5.0, "label": "fixed default (Nils Rooijmans): more than 60 clicks, cost over 5, no conversions"}
FIXED_GRAM = {"clicks": 150, "cost": 0.0, "label": "fixed default (Adalysis n-grams): more than 150 clicks, no conversions"}
FIXED_PROMOTE = 2  # conversions (Lionel Fenestraz); also the floor with economics
SYMBOLS = {"USD": "$", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹"}


# ----------------------------------------------------------------------------- text and matching

def tokens(text: str) -> list[str]:
    """Words as a negative sees them: lower case, accents kept, '&' kept as a word, other punctuation dropped."""
    text = unicodedata.normalize("NFC", str(text or "")).casefold()
    return re.findall(r"&|[^\W_]+", text)


def blocks(neg: list[str], match: str, query: list[str]) -> bool:
    """Whether a negative blocks a search. Negatives don't match close variants, plurals, or synonyms."""
    if not neg or not query:
        return False
    if match == "exact":
        return neg == query
    window = query[:MAX_QUERY_WORDS]
    if match == "phrase":
        n = len(neg)
        return any(window[i:i + n] == neg for i in range(len(window) - n + 1))
    return set(neg) <= set(window)


def contains(phrase: list[str], words: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(words[i:i + n] == phrase for i in range(len(words) - n + 1))


def grams(words: list[str], n: int) -> set[tuple]:
    window = words[:MAX_QUERY_WORDS]
    return {tuple(window[i:i + n]) for i in range(len(window) - n + 1)}


# ----------------------------------------------------------------------------- statistics

def _log_binom_cdf(x: int, n: int, p: float) -> float:
    """log P(X <= x) for X ~ Binomial(n, p)."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 0.0 if x >= n else -math.inf
    lp, lq = math.log(p), math.log1p(-p)
    logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
            for i in range(0, min(x, n) + 1)]
    top = max(logs)
    return top + math.log(math.fsum(math.exp(v - top) for v in logs))


def cvr_upper(x: int, n: int, conf: float):
    """One-sided upper bound on the conversion rate (Clopper-Pearson). With x = 0 it is 1 - (1 - conf)^(1/n)."""
    if n <= 0:
        return None
    if x <= 0:
        return 1 - (1 - conf) ** (1 / n)
    if x >= n:
        return 1.0
    alpha, lo, hi = math.log(1 - conf), x / n, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _log_binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def cvr_lower(x: int, n: int, conf: float):
    """One-sided lower bound on the conversion rate (Clopper-Pearson)."""
    if n <= 0:
        return None
    if x <= 0:
        return 0.0
    x = min(x, n)
    alpha, lo, hi = 1 - conf, 0.0, x / n
    for _ in range(80):
        mid = (lo + hi) / 2
        tail = 1 - math.exp(_log_binom_cdf(x - 1, n, mid))  # P(X >= x)
        if tail < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def clicks_needed(breakeven_cvr: float, conf: float) -> int:
    """Fewest clicks with zero conversions that rule out converting at break-even."""
    if breakeven_cvr >= 1:
        return 1
    limit = math.log(1 - conf) / math.log(1 - breakeven_cvr)
    return math.floor(limit) + 1


class Econ:
    def __init__(self):
        self.cpa = None          # the CPA the tests use (break-even, or target as a fallback)
        self.kind = ""           # breakeven_cpa, target_cpa, breakeven_roas, target_roas
        self.label = "MISSING"
        self.roas = None
        self.value_per_conv = None
        self.source = ""


def evaluate(clicks: float, cost: float, conv: float, econ: Econ, args, kind: str, fallback_cpc=None) -> dict:
    """Statistical verdict for one term or n-gram at one scope."""
    out = {"cpc": cost / clicks if clicks else fallback_cpc, "breakeven_cvr": None, "upper": None, "lower": None,
           "verdict": "", "needed": None, "more_clicks": None, "more_spend": None, "test": ""}
    n = int(round(clicks))
    if econ.cpa:
        out["test"] = f"break-even ({args.confidence:.0%})"
        cpc = out["cpc"]
        if cpc:
            out["breakeven_cvr"] = cpc / (econ.cpa * args.actions_per_click)
        if conv <= 0:
            out["upper"] = cvr_upper(0, n, args.confidence) if n else None
            if out["breakeven_cvr"] is None:
                out["verdict"] = "no clicks"
                return out
            needed = clicks_needed(out["breakeven_cvr"], args.confidence)
            out["needed"] = needed
            if n >= needed:
                out["verdict"] = "proven waste"
            else:
                out["verdict"] = "not enough data"
                out["more_clicks"] = needed - n
                out["more_spend"] = (needed - n) * cpc
        else:
            x_up, x_lo = min(math.ceil(conv), n), min(math.floor(conv), n)
            out["upper"] = cvr_upper(x_up, n, args.confidence) if n else None
            out["lower"] = cvr_lower(x_lo, n, args.confidence) if n else None
            be = out["breakeven_cvr"]
            if be is not None and out["upper"] is not None and out["upper"] < be:
                out["verdict"] = "converting, losing money"
            elif be is not None and out["lower"] is not None and out["lower"] >= be:
                out["verdict"] = "converting, proven profitable"
            else:
                out["verdict"] = "converting"
        return out
    rule = FIXED_TERM if kind == "term" else FIXED_GRAM
    out["test"] = rule["label"]
    if conv <= 0:
        if clicks > rule["clicks"] and cost > rule["cost"]:
            out["verdict"] = "proven waste"
        else:
            out["verdict"] = "not enough data"
            out["needed"] = rule["clicks"] + 1
            out["more_clicks"] = max(rule["clicks"] + 1 - n, 0)
    else:
        out["verdict"] = "converting"
    return out


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# ----------------------------------------------------------------------------- reading

def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def num(value) -> float:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def pick(row: dict, *names: str) -> str:
    for name in names:
        if row.get(name):
            return row[name]
    for key, value in row.items():  # columns such as segments_search_term_match_source
        if value and any(key.endswith(name) for name in names):
            return value
    return ""


def low(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def ctype_of(row: dict) -> str:
    return low(pick(row, "campaign_type", "campaign_advertising_channel_type")).replace(" ", "_")


def parse_context(path: str) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    ctx = {"protected": [], "unwanted": [], "breakeven": "", "target": "", "currency": "", "account": ""}

    def section(name):
        m = re.search(rf"(?ms)^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)", text)
        return m.group(1) if m else ""

    def bullets(block):
        out = []
        for line in block.splitlines():
            m = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if m and not m.group(1).startswith("[") and m.group(1).upper() != "MISSING":
                out.append(m.group(1))
        return out

    ctx["protected"] = [b.strip().strip('"\'') for b in bullets(section("Protected terms"))]
    for b in bullets(section("Terms we don't want")):
        for part in re.split(r"[,;]", b):
            part = part.strip().strip('"\'.').strip()
            if part and len(tokens(part)) <= 4:
                ctx["unwanted"].append(part)
    for line in section("Economics").splitlines():
        m = re.match(r"^\s*[-*]\s*(.+?):\s*(.*)$", line)
        if not m:
            continue
        label, value = m.group(1).lower(), m.group(2).strip()
        if label.startswith("break-even") or label.startswith("breakeven"):
            ctx["breakeven"] = value
        elif label.startswith("target"):
            ctx["target"] = value
    m = re.search(r"(?mi)^\s*[-*]\s*Currency:\s*([A-Za-z]{3})\b", text)
    if m:
        ctx["currency"] = m.group(1).upper()
    m = re.search(r"(?m)^\*\*Account:\*\*\s*(.+)$", text)
    if m and not m.group(1).strip().startswith("["):
        ctx["account"] = m.group(1).strip()
    return ctx


def parse_economic_value(text: str):
    """'$150' -> ('cpa', 150); '250%' or '2.5x' or 'ROAS 2.5' -> ('roas', 2.5); MISSING or blank -> None."""
    text = (text or "").strip()
    if not text or text.upper().startswith("MISSING") or text.startswith("["):
        return None
    m = re.search(r"(\d[\d,]*\.?\d*)\s*(%|x\b)?", text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    if m.group(2) == "%":
        return ("roas", value / 100)
    if (m.group(2) or "").lower() == "x" or "roas" in text.lower():
        return ("roas", value)
    return ("cpa", value)


# ----------------------------------------------------------------------------- the review

class Review:
    def __init__(self, args):
        self.args = args
        self.notes: list[str] = []
        self.missing: list[str] = []
        self.econ = Econ()
        self.ctx = {"protected": [], "unwanted": [], "breakeven": "", "target": "", "currency": "", "account": ""}
        start, _, end = args.window.partition(":")
        self.start, self.end = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        self.days = (self.end - self.start).days + 1
        self.window_text = f"{self.start.isoformat()} to {self.end.isoformat()}"
        self.proposals: list[dict] = []
        self.rejected: list[dict] = []
        self.cover: list[tuple] = []   # (proposal id, tokens, match, scope)
        self.protected_rejects: set = set()  # candidates that block a protected term at any level

    # ---------------------------------------------------------------- load

    def load(self):
        a = self.args
        if a.context:
            if Path(a.context).exists():
                self.ctx = parse_context(a.context)
            else:
                self.missing.append(f"account context file not found at {a.context}: no protected terms or Terms we don't want")
        else:
            self.missing.append("account context: no protected terms or Terms we don't want were checked")
        self.currency = (a.currency or self.ctx["currency"] or "").upper()
        self.protected = [(p, tokens(p)) for p in self.ctx["protected"] if tokens(p)]
        if a.context and not self.protected:
            self.missing.append("Protected terms: none listed in the context, so no negative was checked against them")

        # Search terms, totaled per campaign + ad group + term.
        rows: "OrderedDict[tuple, dict]" = OrderedDict()
        skipped_types = defaultdict(float)
        for path in a.search_terms:
            for r in read_csv(path):
                term = pick(r, "search_term", "campaign_search_term_view_search_term", "search_term_view_search_term")
                words = tokens(term)
                if not words:
                    continue
                ctype = ctype_of(r)
                if ctype in NO_NEGATIVES:
                    skipped_types[ctype] += num(r.get("clicks"))
                    continue
                camp, group = r.get("campaign", ""), r.get("ad_group", "")
                key = (low(camp), low(group), " ".join(words))
                row = rows.setdefault(key, {"campaign": camp, "ad_group": group, "camp": low(camp), "group": low(group),
                                             "term": " ".join(words), "words": words, "ctype": ctype,
                                             "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conv": 0.0, "value": 0.0,
                                             "all_conv": 0.0, "sources": set(), "status": set()})
                for field, col in (("impressions", "impressions"), ("clicks", "clicks"), ("cost", "cost"),
                                   ("conv", "conversions"), ("value", "conversion_value"), ("all_conv", "all_conversions")):
                    row[field] += num(r.get(col))
                source = low(pick(r, "search_term_match_source"))
                if source:
                    row["sources"].add(source)
                status = low(r.get("search_term_status", ""))
                if status:
                    row["status"].add(status)
                if ctype and not row["ctype"]:
                    row["ctype"] = ctype
        self.rows = list(rows.values())
        mixed = sorted({r["campaign"] for r in self.rows if not r["group"] and r["ctype"] not in NO_AD_GROUPS
                        and any(o["camp"] == r["camp"] and o["group"] for o in self.rows)})
        for name in mixed:
            self.notes.append(f"Campaign '{name}' has search terms with and without an ad group. If they came from both "
                              "search_term_view and campaign_search_term_view, the same clicks are counted twice: keep "
                              "campaign_search_term_view for Performance Max only.")
        for ctype, clicks in skipped_types.items():
            self.notes.append(f"Skipped {ctype} search terms ({clicks:.0f} clicks): {NO_NEGATIVES[ctype]}.")

        # Campaign totals for disclosed share, CPC, and value per conversion.
        self.camp_totals: dict[str, dict] = {}
        self.ctypes: dict[str, str] = {}
        self.names: dict[str, str] = {}
        if a.campaigns:
            for r in read_csv(a.campaigns):
                c = low(r.get("campaign"))
                if not c:
                    continue
                t = self.camp_totals.setdefault(c, {"clicks": 0.0, "cost": 0.0, "conv": 0.0, "value": 0.0})
                for field, col in (("clicks", "clicks"), ("cost", "cost"), ("conv", "conversions"), ("value", "conversion_value")):
                    t[field] += num(r.get(col))
                self.names.setdefault(c, r.get("campaign"))
                if ctype_of(r):
                    self.ctypes[c] = ctype_of(r)
        else:
            self.missing.append("campaign totals: the share of clicks the search terms report discloses is MISSING")
        for row in self.rows:
            self.names.setdefault(row["camp"], row["campaign"])
            if row["ctype"]:
                self.ctypes.setdefault(row["camp"], row["ctype"])
            elif self.ctypes.get(row["camp"]):
                row["ctype"] = self.ctypes[row["camp"]]

        # Positive keywords.
        self.positives = []
        if a.keywords:
            for r in read_csv(a.keywords):
                status = low(r.get("keyword_status") or r.get("status"))
                if not r.get("keyword") or low(r.get("is_negative")) == "true" or status == "removed" or r.get("negative_level"):
                    continue
                self.positives.append({"camp": low(r.get("campaign")), "group": low(r.get("ad_group")),
                                       "text": r["keyword"], "words": tokens(r["keyword"]),
                                       "match": low(r.get("match_type")) or "broad", "status": status or "enabled"})
        else:
            self.missing.append("positive keywords: no check that a negative would block a live keyword")

        # Negative lists and where they're attached.
        self.attached: dict[str, set] = defaultdict(set)
        if a.list_attachments:
            for r in read_csv(a.list_attachments):
                status = low(pick(r, "campaign_shared_set_status", "status"))
                if r.get("shared_set") and r.get("campaign") and status not in ("removed",):
                    self.attached[low(r["shared_set"])].add(low(r["campaign"]))

        # Existing negatives at every level.
        self.negatives = []
        list_names = {}
        if a.negatives:
            for path in a.negatives:
                for r in read_csv(path):
                    if not r.get("keyword") or low(r.get("is_negative")) == "false":
                        continue
                    level_text = low(r.get("negative_level") or r.get("level"))
                    shared = r.get("shared_set", "")
                    stype = low(r.get("shared_set_type"))
                    if "account" in level_text or "account_level" in stype:
                        level = "account"
                    elif shared:
                        level = "list"
                        list_names[low(shared)] = shared
                    elif level_text.replace(" ", "_") == "ad_group" or (r.get("ad_group") and level_text != "campaign"):
                        level = "ad_group"
                    else:
                        level = "campaign"
                    match = low(r.get("match_type")) or "broad"
                    self.negatives.append({"level": level, "camp": low(r.get("campaign")), "group": low(r.get("ad_group")),
                                           "list": low(shared), "list_name": shared, "text": r["keyword"],
                                           "words": tokens(r["keyword"]), "match": match})
        else:
            self.missing.append("existing negatives: terms already blocked can't be recognized")
        unattached = sorted(name for key, name in list_names.items() if not self.attached.get(key))
        if unattached and a.list_attachments:
            self.notes.append("Negative keyword lists not attached to any campaign (they block nothing): " + ", ".join(unattached) + ".")
        elif list_names and not a.list_attachments:
            self.missing.append("negative list attachments: list negatives were treated as blocking nothing")

        # Converting searches from a longer history.
        self.history = []
        if a.history:
            for path in a.history:
                for r in read_csv(path):
                    term = pick(r, "search_term", "campaign_search_term_view_search_term", "search_term_view_search_term")
                    if num(r.get("conversions")) > 0 and tokens(term):
                        self.history.append({"camp": low(r.get("campaign")), "group": low(r.get("ad_group")),
                                             "term": " ".join(tokens(term)), "words": tokens(term),
                                             "conv": num(r.get("conversions"))})
        else:
            self.missing.append("converting search terms history: negatives were checked against this window's conversions only")

        # Economics.
        self.set_economics()

    def set_economics(self):
        a, e = self.args, self.econ
        choice = None
        for kind in ("breakeven_cpa", "breakeven_roas", "target_cpa", "target_roas"):
            if getattr(a, kind):
                choice, e.source = (kind, getattr(a, kind)), "given"
                break
        if not choice:
            for label in ("breakeven", "target"):
                parsed = parse_economic_value(self.ctx.get(label, ""))
                if parsed:
                    choice, e.source = (f"{label}_{parsed[0]}", parsed[1]), "account context"
                    break
        if not choice:
            self.missing.append("break-even and target CPA or ROAS: zero-conversion terms were judged on fixed defaults, "
                                "not break-even")
            return
        kind, value = choice
        e.kind = kind
        if kind.endswith("cpa"):
            e.cpa = value
        else:
            e.roas = value
            conv = sum(t["conv"] for t in self.camp_totals.values()) or sum(r["conv"] for r in self.rows)
            val = sum(t["value"] for t in self.camp_totals.values()) or sum(r["value"] for r in self.rows)
            if conv > 0 and val > 0:
                e.value_per_conv = val / conv
                e.cpa = e.value_per_conv / value
            else:
                self.missing.append("conversion value: a ROAS target can't be turned into a CPA, so fixed defaults were used")
                e.kind = ""
                return
        names = {"breakeven_cpa": "break-even CPA", "target_cpa": "target CPA",
                 "breakeven_roas": "break-even ROAS", "target_roas": "target ROAS"}
        if kind.endswith("roas"):
            e.label = (f"{names[kind]} {value:g} ({e.source}), which is a CPA of {self.money(e.cpa)} at the average "
                       f"conversion value of {self.money(e.value_per_conv)}")
        else:
            e.label = f"{names[kind]} {self.money(e.cpa)} ({e.source})"
        if kind.startswith("target"):
            self.notes.append("The target was used because the break-even point is MISSING. A term can miss the target "
                              "and still make money, so add the break-even point to the context for a fairer test.")

    # ---------------------------------------------------------------- helpers

    def money(self, value) -> str:
        if value is None:
            return "MISSING"
        symbol = SYMBOLS.get(self.currency)
        if symbol:
            return f"{symbol}{value:,.2f}"
        return f"{value:,.2f} {self.currency}".strip()

    @staticmethod
    def pct(value) -> str:
        return "MISSING" if value is None else f"{value * 100:.1f}%"

    def camp_name(self, c: str) -> str:
        return self.names.get(c, c)

    def camp_cpc(self, c: str):
        t = self.camp_totals.get(c)
        if t and t["clicks"]:
            return t["cost"] / t["clicks"]
        rows = [r for r in self.rows if r["camp"] == c]
        clicks = sum(r["clicks"] for r in rows)
        return sum(r["cost"] for r in rows) / clicks if clicks else None

    def neg_in_scope(self, neg: dict, camp: str, group: str) -> bool:
        if neg["level"] == "account":
            return True
        if neg["level"] == "list":
            return camp in self.attached.get(neg["list"], set())
        if neg["level"] == "campaign":
            return neg["camp"] == camp
        return neg["camp"] == camp and neg["group"] == group

    def existing_block(self, words: list[str], camp: str, group: str):
        for neg in self.negatives:
            if self.neg_in_scope(neg, camp, group) and blocks(neg["words"], neg["match"], words):
                return neg
        return None

    @staticmethod
    def describe_neg(neg: dict) -> str:
        where = {"account": "account level", "list": f"list '{neg['list_name']}'", "campaign": "campaign",
                 "ad_group": "ad group"}[neg["level"]]
        return f"'{neg['text']}' ({neg['match']}, {where})"

    def in_scope(self, scope: tuple, camp: str, group: str) -> bool:
        if scope[0] == "list":
            return camp in scope[1]
        if scope[0] == "campaign":
            return camp == scope[1]
        return camp == scope[1] and (group == scope[2] or group == "")

    def scope_text(self, scope: tuple) -> str:
        if scope[0] == "list":
            return f"list '{self.args.shared_list}'"
        if scope[0] == "campaign":
            return f"campaign '{self.camp_name(scope[1])}'"
        group = next((r["ad_group"] for r in self.rows if r["camp"] == scope[1] and r["group"] == scope[2]), scope[2])
        return f"ad group '{group}' in '{self.camp_name(scope[1])}'"

    def covered_by(self, row: dict):
        for pid, words, match, scope in self.cover:
            if self.in_scope(scope, row["camp"], row["group"]) and (scope[0] != "ad_group" or row["group"] == scope[2]) \
                    and blocks(words, match, row["words"]):
                return pid
        return None

    # ---------------------------------------------------------------- prepare

    def prepare(self):
        """Mark rows already blocked, then build campaign-level term totals."""
        for row in self.rows:
            neg = self.existing_block(row["words"], row["camp"], row["group"])
            row["blocked_by"] = self.describe_neg(neg) if neg else ""
            if not neg and any("excluded" in s for s in row["status"]):
                row["blocked_by"] = "marked excluded in the report"
            row["protected"] = next((p for p, w in self.protected if contains(w, row["words"])), "")
        self.active = [r for r in self.rows if not r["blocked_by"]]
        camp_terms: "OrderedDict[tuple, dict]" = OrderedDict()
        for row in self.rows:
            key = (row["camp"], row["term"])
            t = camp_terms.setdefault(key, {"camp": row["camp"], "campaign": row["campaign"], "term": row["term"],
                                            "words": row["words"], "ctype": row["ctype"], "groups": [], "rows": [],
                                            "impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conv": 0.0, "value": 0.0,
                                            "all_conv": 0.0, "sources": set(), "protected": row["protected"]})
            t["rows"].append(row)
            if row["ad_group"] and row["ad_group"] not in t["groups"]:
                t["groups"].append(row["ad_group"])
            for f in ("impressions", "clicks", "cost", "conv", "value", "all_conv"):
                t[f] += row[f]
            t["sources"] |= row["sources"]
        self.terms = list(camp_terms.values())
        for t in self.terms:
            blocked = [r for r in t["rows"] if r["blocked_by"]]
            t["blocked_by"] = blocked[0]["blocked_by"] if blocked and len(blocked) == len(t["rows"]) else ""
            t["eval"] = evaluate(t["clicks"], t["cost"], t["conv"], self.econ, self.args, "term", self.camp_cpc(t["camp"]))

    # ---------------------------------------------------------------- checks

    def check(self, words: list[str], match: str, scope: tuple, basis: str) -> dict:
        """Everything a candidate would block at one scope, and whether it's safe and justified there."""
        res = {"ok": True, "hard": [], "warnings": [], "rows": [], "clicks": 0.0, "cost": 0.0, "conv": 0.0}
        camps = scope[1] if scope[0] == "list" else {scope[1]}
        for c in camps:
            if self.ctypes.get(c) in NO_AD_GROUPS and scope[0] == "ad_group":
                res["hard"].append("Performance Max has no ad groups")
        for p, pw in self.protected:
            if blocks(words, match, pw):
                res["hard"].append(f"would block protected term '{p}'")
        kw_hits = [kw for kw in self.positives
                   if self.in_scope(scope, kw["camp"], kw["group"]) and (scope[0] != "ad_group" or kw["group"] == scope[2])
                   and blocks(words, match, kw["words"])]
        for kw in kw_hits[:3]:
            res["hard"].append(f"would block {kw['status']} keyword '{kw['text']}' ({kw['match']})")
        if len(kw_hits) > 3:
            res["hard"].append(f"and {plural(len(kw_hits) - 3, 'more keyword')}")
        converting = {}
        for r in self.rows:
            if r["conv"] > 0 and self.in_scope(scope, r["camp"], r["group"]) and blocks(words, match, r["words"]):
                converting[r["term"]] = converting.get(r["term"], 0) + r["conv"]
        for h in self.history:
            if self.in_scope(scope, h["camp"], h["group"]) and blocks(words, match, h["words"]):
                converting.setdefault(h["term"], h["conv"])
        for term, conv in sorted(converting.items(), key=lambda kv: -kv[1])[:3]:
            res["hard"].append(f"would block converting search '{term}' ({conv:g} conv)")
        if len(words) > KEYWORD_MAX_WORDS or len(" ".join(words)) > KEYWORD_MAX_CHARS:
            res["hard"].append(f"longer than Google allows for a keyword ({KEYWORD_MAX_WORDS} words, {KEYWORD_MAX_CHARS} characters)")
        for r in self.active:
            if self.in_scope(scope, r["camp"], r["group"]) and (scope[0] != "ad_group" or r["group"] == scope[2]) \
                    and blocks(words, match, r["words"]) and not self.covered_by(r):
                res["rows"].append(r)
        for f in ("clicks", "cost", "conv"):
            res[f] = sum(r[f] for r in res["rows"])
        if not res["rows"]:
            res["hard"].append("blocks no search term that isn't already blocked")
        # Warnings the person should see, but that don't stop the proposal.
        for p, pw in self.protected:
            shared = [w for w in words if w in set(pw) - STOPWORDS]
            if shared and match != "exact" and not blocks(words, match, pw):
                rest = [w for w in words if w not in pw]
                res["warnings"].append(f"shares '{' '.join(shared)}' with protected term '{p}'; it only blocks searches "
                                       f"that also contain '{' '.join(rest)}'")
        hits = sorted({r["term"] for r in res["rows"] if r["protected"]})
        if hits:
            res["warnings"].append("blocks searches that contain a protected term: " + "; ".join(hits[:3]))
        secondary = sorted({r["term"] for r in res["rows"] if r["all_conv"] > 0})
        if secondary:
            res["warnings"].append("blocks searches with secondary conversions: " + "; ".join(secondary[:3]))
        approx = [r for r in res["rows"] if r["sources"] & (AI_MAX_SOURCES | {"performance_max"}) or r["ctype"] in NO_AD_GROUPS]
        if approx and match == "exact":
            res["warnings"].append("AI Max or Performance Max search: the reported term can be an approximation, "
                                   "so an exact negative may not stop the same intent")
        res["ok"] = not res["hard"]
        if res["ok"] and basis == "performance":
            n_terms = len({r["term"] for r in res["rows"]})
            ev = evaluate(res["clicks"], res["cost"], 0, self.econ, self.args, "gram" if match != "exact" else "term")
            res["eval"] = ev
            if ev["verdict"] != "proven waste":
                res["ok"] = False
                res["hard"].append("not proven at this level: " + self.need_text(ev))
            elif match != "exact" and n_terms < 2:
                res["ok"] = False
                res["hard"].append("only one search term; the exact negative covers it")
        return res

    def need_text(self, ev: dict) -> str:
        if ev.get("more_clicks") is None:
            return ev.get("verdict") or "no data"
        text = f"needs {ev['more_clicks']:.0f} more clicks with no conversion" + ("" if self.econ.cpa else " to reach the fixed default")
        if ev.get("more_spend") is not None:
            text += f" (about {self.money(ev['more_spend'])} more spend)"
        return text

    # ---------------------------------------------------------------- proposals

    def propose(self, cand: dict, scope: tuple, res: dict):
        pid = f"c{len(self.proposals) + 1}"
        level = {"list": "shared_list", "campaign": "campaign", "ad_group": "ad_group"}[scope[0]]
        groups = sorted({r["ad_group"] for r in res["rows"] if r["ad_group"]})
        n_terms = len({r["term"] for r in res["rows"]})
        worst = sorted(res["rows"], key=lambda r: -r["cost"])
        text = " ".join(cand["words"])
        if cand["basis"] == "performance":
            ev = res["eval"]
            if ev["breakeven_cvr"] is not None:
                proof = (f"With 0 conversions in {res['clicks']:.0f} clicks, conversion rates of {self.pct(ev['upper'])} and "
                         f"above are ruled out at {self.args.confidence:.0%} confidence; break-even needs "
                         f"{self.pct(ev['breakeven_cvr'])} (CPC {self.money(ev['cpc'])} / CPA {self.money(self.econ.cpa)}).")
            else:
                proof = f"Test: {ev['test']}."
            evidence = (f"{n_terms} search term{'s' if n_terms != 1 else ''}, {res['clicks']:.0f} clicks, "
                        f"{self.money(res['cost'])} cost, 0 conversions, {self.window_text}. {proof}")
            test = ev["test"]
        else:
            evidence = (f"{n_terms} search term{'s' if n_terms != 1 else ''}, {res['clicks']:.0f} clicks, "
                        f"{self.money(res['cost'])} cost, {res['conv']:g} conversions, {self.window_text}.")
            test = "intent"
        if cand.get("fallback_from"):
            evidence += f" Campaign level was rejected: {cand['fallback_from']}."
        prop = {"id": pid, "include": "yes", "action": "add_negative" if level != "shared_list" else "other",
                "level": level, "campaign": "" if level == "shared_list" else self.camp_name(scope[1]),
                "ad_group": groups[0] if level == "ad_group" and groups else "",
                "shared_set": self.args.shared_list if level == "shared_list" else "",
                "list_campaigns": "; ".join(self.camp_name(c) for c in sorted(scope[1])) if level == "shared_list" else "",
                "keyword": text, "match_type": cand["match"], "basis": cand["basis"], "source": cand["source"],
                "test": test, "reason": cand["reason"], "evidence": evidence,
                "expected_effect": (f"Stops ads showing for these searches in {self.scope_text(scope)}. In the window they cost "
                                    f"{self.money(res['cost'])} with {res['conv']:g} conversions (historical spend, not a forecast)."),
                "blocks_example": worst[0]["term"] if worst else "",
                "must_not_block": self.must_not_block(cand["words"], cand["match"], scope),
                "terms_blocked": n_terms, "clicks": f"{res['clicks']:.0f}", "cost": f"{res['cost']:.2f}",
                "conversions": f"{res['conv']:g}", "warnings": "; ".join(res["warnings"]),
                "campaign_type": self.ctypes.get(scope[1], "") if scope[0] != "list" else "",
                "target_ad_group": ""}
        self.proposals.append(prop)
        self.cover.append((pid, cand["words"], cand["match"], scope))
        return pid

    def must_not_block(self, words, match, scope) -> str:
        """A nearby search worth keeping, preferring one that shares a word with the negative but isn't blocked by it."""
        key = set(words) - STOPWORDS
        pool = [(r["term"], r["conv"]) for r in self.rows if r["conv"] > 0 and self.in_scope(scope, r["camp"], r["group"])]
        pool += [(h["term"], h["conv"]) for h in self.history if self.in_scope(scope, h["camp"], h["group"])]
        pool = [term for term, _ in sorted(pool, key=lambda x: -x[1]) if not blocks(words, match, tokens(term))]
        keywords = [kw["text"] for kw in self.positives if self.in_scope(scope, kw["camp"], kw["group"])
                    and not blocks(words, match, kw["words"])]
        protected = [p for p, pw in self.protected if not blocks(words, match, pw)]
        for options in (pool, keywords, protected):
            for text in options:
                if set(tokens(text)) & key:
                    return text
        return next(iter(pool + protected), "")

    def reject(self, cand: dict, scope: tuple, res: dict):
        key = (tuple(cand["words"]), cand["match"])
        if key in self.protected_rejects:
            return
        if any(h.startswith("would block protected term") for h in res["hard"]):
            self.protected_rejects.add(key)
        self.rejected.append({"candidate": " ".join(cand["words"]), "match_type": cand["match"], "basis": cand["basis"],
                              "source": cand["source"], "scope": self.scope_text(scope),
                              "why": "; ".join(dict.fromkeys(res["hard"])),
                              "clicks": f"{res['clicks']:.0f}", "cost": f"{res['cost']:.2f}"})

    def place(self, cand: dict, scopes_first: list[tuple] | None = None):
        """Try list, then campaign, then ad group. Propose at the first safe, justified level."""
        words, match = cand["words"], cand["match"]
        hit_rows = [r for r in self.active if blocks(words, match, r["words"]) and not self.covered_by(r)]
        if cand.get("campaign"):
            hit_rows = [r for r in hit_rows if r["camp"] == low(cand["campaign"])]
        if cand.get("ad_group"):
            hit_rows = [r for r in hit_rows if r["group"] == low(cand["ad_group"])]
        if not hit_rows:
            if cand["source"] == "intent file":
                where = cand.get("campaign") or "any campaign"
                self.rejected.append({"candidate": " ".join(words), "match_type": match, "basis": cand["basis"],
                                      "source": cand["source"], "scope": where,
                                      "why": "matches no search term in the report that isn't already blocked",
                                      "clicks": "0", "cost": "0.00"})
            return
        for scope in scopes_first or []:
            res = self.check(words, match, scope, cand["basis"])
            if res["ok"]:
                self.propose(cand, scope, res)
            else:
                self.reject(cand, scope, res)
        camps = list(OrderedDict.fromkeys(r["camp"] for r in hit_rows if not self.covered_by(r)))
        for c in camps:
            if (tuple(words), match) in self.protected_rejects:
                return
            if cand.get("ad_group"):
                scope_list = [("ad_group", c, low(cand["ad_group"]))]
            else:
                scope_list = [("campaign", c)]
            res = self.check(words, match, scope_list[0], cand["basis"])
            if res["ok"]:
                self.propose(cand, scope_list[0], res)
                continue
            self.reject(cand, scope_list[0], res)
            if cand.get("ad_group") or self.ctypes.get(c) in NO_AD_GROUPS:
                continue
            reason = "; ".join(dict.fromkeys(res["hard"]))
            groups = list(OrderedDict.fromkeys(r["group"] for r in hit_rows if r["camp"] == c and r["group"]))
            for g in groups:
                if (tuple(words), match) in self.protected_rejects:
                    return
                sub = dict(cand, fallback_from=reason)
                res2 = self.check(words, match, ("ad_group", c, g), cand["basis"])
                if res2["ok"]:
                    self.propose(sub, ("ad_group", c, g), res2)
                else:
                    self.reject(sub, ("ad_group", c, g), res2)

    # ---------------------------------------------------------------- run

    def run(self):
        self.load()
        self.prepare()
        a = self.args
        list_scope = None
        if a.shared_list:
            if a.list_campaigns:
                camps = {low(c) for c in a.list_campaigns.split(",") if c.strip()}
            else:
                camps = set(self.attached.get(low(a.shared_list), set()))
            if not camps:
                camps = {r["camp"] for r in self.rows}
                self.notes.append(f"List '{a.shared_list}' isn't attached to any campaign in the data, so it was "
                                  "treated as a new list for every campaign in the report.")
            list_scope = ("list", frozenset(c for c in camps if self.ctypes.get(c) not in NO_NEGATIVES))

        # 1. Intent: Terms we don't want, then the intent file.
        cands = []
        for term in self.ctx["unwanted"]:
            if tokens(term):
                cands.append({"words": tokens(term), "match": "phrase", "basis": "intent", "source": "terms we don't want",
                              "reason": f"Matches '{term}' under Terms we don't want in the account context"})
        if a.intent:
            for r in read_csv(a.intent):
                text = r.get("negative") or r.get("keyword") or ""
                match = low(r.get("match_type")) or "phrase"
                if not tokens(text) or match not in ("exact", "phrase", "broad"):
                    self.notes.append(f"Intent file row skipped (needs negative and match_type exact, phrase, or broad): {text}")
                    continue
                cands.append({"words": tokens(text), "match": match, "basis": "intent", "source": "intent file",
                              "reason": r.get("reason") or "Clear mismatch with the offer",
                              "campaign": r.get("campaign", ""), "ad_group": r.get("ad_group", "")})
        for cand in cands:
            first = [list_scope] if list_scope and not cand.get("campaign") and not cand.get("ad_group") else None
            self.place(cand, first)

        # 2. N-gram patterns (phrase), pooled across the list first, then per campaign, then per ad group.
        self.gram_rows = []
        units = []
        if list_scope:
            units.append(("list", list_scope, [r for r in self.active if r["camp"] in list_scope[1]]))
        by_camp, by_group = defaultdict(list), defaultdict(list)
        for r in self.active:
            by_camp[r["camp"]].append(r)
            if r["group"]:
                by_group[(r["camp"], r["group"])].append(r)
        for c, rs in by_camp.items():
            units.append(("campaign", ("campaign", c), rs))
        for (c, g), rs in by_group.items():
            if self.ctypes.get(c) not in NO_AD_GROUPS:
                units.append(("ad_group", ("ad_group", c, g), rs))
        for unit_kind, scope, rs in units:
            stats = {}
            for r in rs:
                for n in (1, 2, 3):
                    for g in grams(r["words"], n):
                        s = stats.setdefault(g, {"terms": set(), "clicks": 0.0, "cost": 0.0, "conv": 0.0, "value": 0.0})
                        s["terms"].add(r["term"])
                        s["clicks"] += r["clicks"]
                        s["cost"] += r["cost"]
                        s["conv"] += r["conv"]
                        s["value"] += r["value"]
            by_set, narrower = defaultdict(list), {}
            for g, s in stats.items():
                if len(s["terms"]) >= 2:
                    by_set[frozenset(s["terms"])].append(g)
            for same in by_set.values():
                for g in same:
                    for h in same:
                        if len(h) > len(g) and contains(list(g), list(h)) and not all(w in STOPWORDS for w in h):
                            narrower[g] = h
                            break
            for g in sorted(stats, key=lambda g: (len(g), -stats[g]["cost"])):
                s = stats[g]
                if len(s["terms"]) < 2:
                    continue
                ev = evaluate(s["clicks"], s["cost"], s["conv"], self.econ, a, "gram")
                row = {"scope": self.scope_text(scope), "level": unit_kind, "n": len(g), "ngram": " ".join(g),
                       "terms": len(s["terms"]), "clicks": s["clicks"], "cost": s["cost"], "conv": s["conv"], "eval": ev,
                       "outcome": ""}
                self.gram_rows.append(row)
                if all(w in STOPWORDS for w in g):
                    row["outcome"] = "function words only, not proposed"
                    continue
                if g in narrower:
                    row["outcome"] = f"same searches as the narrower '{' '.join(narrower[g])}'"
                    continue
                if (g, "phrase") in self.protected_rejects:
                    row["outcome"] = "not proposed: would block a protected term"
                    continue
                if ev["verdict"] == "converting, losing money":
                    conv_terms = sorted({r["term"] for r in rs if r["conv"] > 0 and contains(list(g), r["words"])})
                    row["outcome"] = "review: loses money but includes converting searches (" + "; ".join(conv_terms[:3]) + ")"
                    continue
                if ev["verdict"] != "proven waste":
                    continue
                cand = {"words": list(g), "match": "phrase", "basis": "performance", "source": "n-gram",
                        "reason": f"Searches containing '{' '.join(g)}' don't convert, and their clicks rule out converting at break-even"
                        if self.econ.cpa else f"Searches containing '{' '.join(g)}' don't convert ({FIXED_GRAM['label']})"}
                res = self.check(cand["words"], "phrase", scope, "performance")
                safety = [h for h in res["hard"] if not h.startswith(("not proven", "blocks no search term", "only one search term"))]
                if res["ok"]:
                    if scope[0] == "ad_group":
                        wide = self.check(cand["words"], "phrase", ("campaign", scope[1]), "intent")
                        reasons = [h for h in wide["hard"] if not h.startswith("blocks no search term")]
                        if reasons:
                            cand["fallback_from"] = "; ".join(dict.fromkeys(reasons))
                    row["outcome"] = f"proposed as {self.propose(cand, scope, res)}"
                elif safety:
                    self.reject(cand, scope, res)
                    row["outcome"] = "not proposed: " + "; ".join(dict.fromkeys(safety))
                elif any("blocks no search term" in h for h in res["hard"]):
                    row["outcome"] = "covered by an earlier proposal"
                else:
                    row["outcome"] = "partly covered by earlier proposals; the rest isn't proven on its own"

        # 3. Single search terms (exact), per campaign then per ad group.
        for t in sorted(self.terms, key=lambda t: -t["cost"]):
            if t["conv"] > 0:
                continue
            ev = t["eval"]
            if ev["verdict"] == "proven waste":
                cand = {"words": t["words"], "match": "exact", "basis": "performance", "source": "search term",
                        "campaign": t["campaign"],
                        "reason": "This search doesn't convert, and its clicks rule out converting at break-even"
                        if self.econ.cpa else f"This search doesn't convert ({FIXED_TERM['label']})"}
                self.place(cand)
        for r in sorted(self.active, key=lambda r: -r["cost"]):
            if r["conv"] > 0 or not r["group"] or self.covered_by(r):
                continue
            ev = evaluate(r["clicks"], r["cost"], 0, self.econ, a, "term", self.camp_cpc(r["camp"]))
            if ev["verdict"] == "proven waste":
                cand = {"words": r["words"], "match": "exact", "basis": "performance", "source": "search term",
                        "reason": "This search doesn't convert in this ad group, and its clicks rule out converting at break-even"
                        if self.econ.cpa else f"This search doesn't convert in this ad group ({FIXED_TERM['label']})"}
                scope = ("ad_group", r["camp"], r["group"])
                res = self.check(r["words"], "exact", scope, "performance")
                if res["ok"]:
                    wide = self.check(r["words"], "exact", ("campaign", r["camp"]), "intent")
                    if wide["hard"]:
                        cand["fallback_from"] = "; ".join(dict.fromkeys(wide["hard"]))
                    self.propose(cand, scope, res)

        # 4. Promotions and term statuses.
        self.promote_and_status()
        self.write()

    def promote_and_status(self):
        a = self.args
        exact_kw = defaultdict(set)
        for kw in self.positives:
            if kw["match"] == "exact":
                exact_kw[" ".join(kw["words"])].add(kw["camp"])
        promotions = []
        rejected_by_term = defaultdict(list)
        for rj in self.rejected:
            rejected_by_term[rj["candidate"]].append(rj["why"])
        for t in self.terms:
            ev, rows = t["eval"], t["rows"]
            pids = sorted({self.covered_by(r) for r in rows if not r["blocked_by"]} - {None}, key=lambda p: int(p[1:]))
            t["status"], t["proposal"], t["note"] = "", ", ".join(pids), ""
            if t["blocked_by"]:
                t["status"], t["note"] = "already blocked", t["blocked_by"]
                continue
            if pids:
                active_rows = [r for r in rows if not r["blocked_by"]]
                covered = [r for r in active_rows if self.covered_by(r)]
                if len(covered) == len(active_rows):
                    t["status"] = "negate"
                    continue
                t["prefix"] = (f"{', '.join(pids)} negates it in ad group " + ", ".join(r["ad_group"] for r in covered) + "; ")
            if t["conv"] > 0:
                cpa = t["cost"] / t["conv"]
                exact_in = exact_kw.get(t["term"], set())
                is_exact = bool(exact_in) or any("added" in s for r in rows for s in r["status"])
                wanted = [u for u in self.ctx["unwanted"] if tokens(u) and blocks(tokens(u), "phrase", t["words"])]
                if wanted:
                    t["status"] = "review"
                    t["note"] = f"matches Terms we don't want ('{wanted[0]}') but converted: check what the conversion was"
                elif ev["verdict"] == "converting, losing money":
                    t["status"] = "review"
                    t["note"] = (f"converts, but the data rules out break-even (CPA {self.money(cpa)}, upper bound "
                                 f"{self.pct(ev['upper'])} vs. break-even {self.pct(ev['breakeven_cvr'])}): fix the bid, ad, "
                                 "or page, or negate it by hand")
                elif is_exact:
                    t["status"] = "keep"
                    others = sorted(self.camp_name(c) for c in exact_in if c != t["camp"])
                    t["note"] = ("already an exact keyword in " + ", ".join(f"'{o}'" for o in others)
                                  if others and t["camp"] not in exact_in else "already an exact keyword")
                elif t["conv"] >= FIXED_PROMOTE and (self.econ.cpa is None or cpa <= self.econ.cpa):
                    t["status"] = "promote"
                    confidence = "proven" if ev["verdict"] == "converting, proven profitable" else "early"
                    t["confidence"] = confidence
                    if self.econ.cpa is None:
                        t["note"] = "2 or more conversions (fixed default from Lionel Fenestraz; break-even MISSING)"
                    else:
                        t["note"] = f"CPA {self.money(cpa)} at or under {self.money(self.econ.cpa)} ({confidence})"
                    promotions.append((t, cpa, confidence))
                elif t["conv"] < FIXED_PROMOTE:
                    t["status"] = "watch"
                    t["note"] = f"{t['conv']:g} conversion so far; promote at {FIXED_PROMOTE}" + (
                        " if CPA stays at or under break-even" if self.econ.cpa else "")
                else:
                    t["status"], t["note"] = "keep", f"converts, CPA {self.money(cpa)} is above break-even but not proven to lose money"
                continue
            why = rejected_by_term.get(t["term"])
            if ev["verdict"] == "proven waste" and why:
                t["status"], t["note"] = "review", "proven to lose money, but the negative was rejected: " + why[0]
                continue
            t["status"] = "watch"
            if ev["verdict"] == "proven waste":
                t["note"] = "proven at campaign level but not proposed; see rejected.csv"
            elif ev.get("more_clicks") is not None:
                t["note"] = self.need_text(ev)
                if t["clicks"] > 0:
                    days = ev["more_clicks"] / (t["clicks"] / self.days)
                    t["note"] += (f", about {math.ceil(days)} days at the current pace" if days <= 365
                                  else ", more than a year at the current pace")
                else:
                    t["note"] += " (no clicks yet, so no pace)"
            else:
                t["note"] = ev.get("verdict") or "not enough data"
            if t["protected"]:
                t["note"] += f" (contains protected term '{t['protected']}')"

        # Strongest first, so a batch split by the change limit starts with the best-proven keywords.
        for t, cpa, confidence in sorted(promotions, key=lambda x: (x[2] != "proven", -x[0]["conv"], x[1])):
            self.add_promotion(t, cpa, confidence)
        for t in self.terms:
            t["note"] = t.pop("prefix", "") + t["note"]

    def add_promotion(self, t: dict, cpa: float, confidence: str):
        if self.ctypes.get(t["camp"]) in NO_AD_GROUPS or not t["groups"]:
            t["note"] += "; Performance Max has no keywords, so pick a Search ad group by hand"
            return
        if len(t["words"]) > KEYWORD_MAX_WORDS or len(t["term"]) > KEYWORD_MAX_CHARS:
            t["note"] += "; too long for a keyword"
            return
        best = max(t["rows"], key=lambda r: (r["conv"], r["clicks"]))
        ev = t["eval"]
        pid = f"c{len(self.proposals) + 1}"
        if ev["breakeven_cvr"] is not None:
            proof = (f" Lower {self.args.confidence:.0%} bound on conversion rate {self.pct(ev['lower'])}; break-even needs "
                     f"{self.pct(ev['breakeven_cvr'])} ({confidence}).")
        else:
            proof = ""
        self.proposals.append({
            "id": pid, "include": "yes", "action": "add_keyword", "level": "ad_group", "campaign": t["campaign"],
            "ad_group": best["ad_group"], "shared_set": "", "list_campaigns": "", "keyword": t["term"], "match_type": "exact",
            "basis": "promote", "source": "search term", "test": f"{FIXED_PROMOTE}+ conversions at or under break-even CPA"
            if self.econ.cpa else "fixed default (Lionel Fenestraz): 2 or more conversions",
            "reason": f"Converting search that isn't an exact keyword yet: {t['conv']:g} conversions at {self.money(cpa)} CPA",
            "evidence": f"{t['clicks']:.0f} clicks, {self.money(t['cost'])} cost, {t['conv']:g} conversions, {self.window_text}.{proof}",
            "expected_effect": "Adds the search as an exact keyword, created paused, so it can get its own bid, ad, and page once enabled.",
            "blocks_example": "", "must_not_block": "", "terms_blocked": 1, "clicks": f"{t['clicks']:.0f}",
            "cost": f"{t['cost']:.2f}", "conversions": f"{t['conv']:g}", "warnings": "", "campaign_type": t["ctype"],
            "target_ad_group": best["ad_group"]})
        t["proposal"] = pid

    # ---------------------------------------------------------------- output

    def write(self):
        out = Path(self.args.out)
        out.mkdir(parents=True, exist_ok=True)
        prop_cols = ["id", "include", "action", "level", "campaign", "ad_group", "shared_set", "list_campaigns", "keyword",
                     "match_type", "basis", "source", "test", "reason", "evidence", "expected_effect", "blocks_example",
                     "must_not_block", "terms_blocked", "clicks", "cost", "conversions", "warnings", "campaign_type",
                     "target_ad_group"]
        self.write_csv(out / "proposals.csv", prop_cols, self.proposals)
        self.write_csv(out / "rejected.csv", ["candidate", "match_type", "basis", "source", "scope", "why", "clicks", "cost"],
                       self.rejected)
        term_rows = []
        for t in sorted(self.terms, key=lambda t: -t["cost"]):
            ev = t["eval"]
            term_rows.append({"campaign": t["campaign"], "campaign_type": t["ctype"], "ad_groups": "; ".join(t["groups"]),
                              "search_term": t["term"], "match_source": "; ".join(sorted(t["sources"])),
                              "impressions": f"{t['impressions']:.0f}", "clicks": f"{t['clicks']:.0f}",
                              "cost": f"{t['cost']:.2f}", "conversions": f"{t['conv']:g}",
                              "cpa": f"{t['cost'] / t['conv']:.2f}" if t["conv"] else "",
                              "breakeven_cvr": "" if ev["breakeven_cvr"] is None else f"{ev['breakeven_cvr']:.4f}",
                              "cvr_upper": "" if ev["upper"] is None else f"{ev['upper']:.4f}",
                              "cvr_lower": "" if ev["lower"] is None else f"{ev['lower']:.4f}",
                              "test": ev["test"], "verdict": ev["verdict"], "status": t["status"],
                              "proposal": t["proposal"], "note": t["note"]})
        self.write_csv(out / "terms.csv", list(term_rows[0].keys()) if term_rows else ["search_term"], term_rows)
        gram_rows = []
        for g in sorted(self.gram_rows, key=lambda g: -g["cost"]):
            ev = g["eval"]
            gram_rows.append({"scope": g["scope"], "level": g["level"], "n": g["n"], "ngram": g["ngram"],
                              "terms": g["terms"], "clicks": f"{g['clicks']:.0f}", "cost": f"{g['cost']:.2f}",
                              "conversions": f"{g['conv']:g}",
                              "breakeven_cvr": "" if ev["breakeven_cvr"] is None else f"{ev['breakeven_cvr']:.4f}",
                              "cvr_upper": "" if ev["upper"] is None else f"{ev['upper']:.4f}",
                              "verdict": ev["verdict"], "clicks_needed": "" if ev["needed"] is None else ev["needed"],
                              "outcome": g["outcome"]})
        self.write_csv(out / "ngrams.csv", list(gram_rows[0].keys()) if gram_rows else ["ngram"], gram_rows)
        (out / "review.md").write_text(self.markdown(), encoding="utf-8")
        counts = defaultdict(int)
        for t in self.terms:
            counts[t["status"]] += 1
        negs = [p for p in self.proposals if p["basis"] != "promote"]
        print(f"search terms: {len(self.rows)} rows, {len(self.terms)} campaign and term pairs")
        print("statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        print(f"proposed: {len(negs)} negatives, {len(self.proposals) - len(negs)} keywords; rejected candidates: {len(self.rejected)}")
        print(f"economics: {self.econ.label}")
        for m in self.missing:
            print(f"MISSING: {m}")
        for n in self.notes:
            print(f"note: {n}")
        print(f"wrote {out / 'review.md'}, proposals.csv, rejected.csv, terms.csv, ngrams.csv")

    @staticmethod
    def write_csv(path: Path, cols: list[str], rows: list[dict]):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def markdown(self) -> str:
        cell = lambda v: str(v).replace("|", "/").replace("\n", " ")
        a, L = self.args, []
        title = self.ctx["account"] or "Google Ads account"
        L += [f"# Search term review: {title}", "", f"Window: {self.window_text} ({self.days} days).",
              f"Economics: {self.econ.label}."]
        if self.econ.cpa:
            multiple = -math.log(1 - a.confidence) * a.actions_per_click
            L.append(f"Test: a search is called wasted only when its clicks, with zero conversions, rule out converting at "
                     f"the break-even rate at {a.confidence:.0%} confidence. That takes spend of roughly {multiple:.1f} times "
                     "the CPA above with no conversion.")
        else:
            L.append("Test: fixed defaults, because no break-even or target is available. Add one to the context for a fairer test.")
        if a.conversion_lag:
            lag_end = (dt.date.fromisoformat(a.today) if a.today else dt.date.today()) - dt.timedelta(days=a.conversion_lag)
            if self.end > lag_end:
                L.append(f"Warning: the window ends inside the {a.conversion_lag}-day conversion delay. Recent zero-conversion "
                         f"clicks may still convert; end the window on or before {lag_end.isoformat()}.")
        L += ["", "## Coverage", "", "| Campaign | Type | Total clicks | Disclosed clicks | Disclosed share | AI Max share of disclosed clicks |",
              "|---|---|---|---|---|---|"]
        for c in OrderedDict.fromkeys(r["camp"] for r in self.rows):
            rs = [r for r in self.rows if r["camp"] == c]
            disclosed = sum(r["clicks"] for r in rs)
            ai = sum(r["clicks"] for r in rs if r["sources"] & AI_MAX_SOURCES)
            total = self.camp_totals.get(c, {}).get("clicks")
            share = self.pct(disclosed / total) if total else "MISSING"
            ai_share = self.pct(ai / disclosed) if disclosed and any(r["sources"] for r in rs) else "n/a"
            L.append(f"| {cell(self.camp_name(c))} | {self.ctypes.get(c, '') or 'MISSING'} | "
                     f"{'MISSING' if total is None else f'{total:.0f}'} | {disclosed:.0f} | {share} | {ai_share} |")
        counts = defaultdict(int)
        for t in self.terms:
            counts[t["status"]] += 1
        negs = [p for p in self.proposals if p["basis"] != "promote"]
        promos = [p for p in self.proposals if p["basis"] == "promote"]
        blocked_cost = sum(float(p["cost"]) for p in negs)
        L += ["", "## Summary", "",
              f"- {len(self.terms)} search terms reviewed (campaign and term pairs): " +
              ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + ".",
              f"- Proposed: {plural(len(negs), 'negative')} ({sum(p['basis'] == 'intent' for p in negs)} on intent, "
              f"{sum(p['basis'] == 'performance' for p in negs)} on performance) and {plural(len(promos), 'keyword')} "
              "to add paused."]
        if negs:
            L.append(f"- The proposed negatives match searches that cost {self.money(blocked_cost)} in the window. That is "
                     "historical spend, not a forecast of savings.")
        L.append(f"- {plural(len(self.rejected), 'candidate negative')} failed a check and "
                 f"{'is' if len(self.rejected) == 1 else 'are'} not proposed (see below).")
        L += ["", "## Proposed negatives", ""]
        if negs:
            L += ["| ID | Negative | Match | Level | Where | Basis | Evidence | Blocks | Must not block | Warnings |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for p in negs:
                where = p["shared_set"] and f"list '{p['shared_set']}'" or (p["campaign"] + (f" / {p['ad_group']}" if p["ad_group"] else ""))
                L.append(f"| {p['id']} | {cell(p['keyword'])} | {p['match_type']} | {p['level']} | {cell(where)} | "
                         f"{p['basis']} | {cell(p['evidence'])} | {cell(p['blocks_example'])} | {cell(p['must_not_block'])} | "
                         f"{cell(p['warnings'])} |")
        else:
            L.append("None. An accurate review can propose zero negatives.")
        L += ["", "## Keywords to promote (created paused)", ""]
        if promos:
            L += ["| ID | Keyword | Match | Campaign / ad group | Evidence |", "|---|---|---|---|---|"]
            for p in promos:
                L.append(f"| {p['id']} | {cell(p['keyword'])} | exact | {cell(p['campaign'])} / {cell(p['ad_group'])} | {cell(p['evidence'])} |")
        else:
            L.append("None.")
        loose = [t for t in self.terms if t["status"] == "promote" and not t["proposal"]]
        if loose:
            L += ["", "Converting searches that can't be added here (no ad group to add them to):", ""]
            L += [f"- {t['term']} ({t['campaign']}): {t['conv']:g} conversions, {t['note']}" for t in loose]
        review = [t for t in self.terms if t["status"] == "review"]
        seen, gram_review = set(), []
        for g in self.gram_rows:
            if g["outcome"].startswith("review") and g["ngram"] not in seen:
                seen.add(g["ngram"])
                gram_review.append(g)
        L += ["", "## Review by hand", ""]
        if review or gram_review:
            L += ["| Search term or n-gram | Campaign | Clicks | Cost | Conv. | Why |", "|---|---|---|---|---|---|"]
            for t in sorted(review, key=lambda t: -t["cost"]):
                L.append(f"| {cell(t['term'])} | {cell(t['campaign'])} | {t['clicks']:.0f} | {self.money(t['cost'])} | "
                         f"{t['conv']:g} | {cell(t['note'])} |")
            for g in gram_review:
                L.append(f"| n-gram '{cell(g['ngram'])}' | {cell(g['scope'])} | {g['clicks']:.0f} | {self.money(g['cost'])} | "
                         f"{g['conv']:g} | {cell(g['outcome'])} |")
        else:
            L.append("None.")
        watch = sorted([t for t in self.terms if t["status"] == "watch"], key=lambda t: -t["cost"])
        L += ["", f"## Watch list (top {min(len(watch), 20)} of {len(watch)} by cost)", ""]
        if watch:
            L += ["| Search term | Campaign | Clicks | Cost | Conv. | What it needs |", "|---|---|---|---|---|---|"]
            for t in watch[:20]:
                L.append(f"| {cell(t['term'])} | {cell(t['campaign'])} | {t['clicks']:.0f} | {self.money(t['cost'])} | "
                         f"{t['conv']:g} | {cell(t['note'])} |")
        else:
            L.append("None.")
        L += ["", "## Not proposed (failed a check)", ""]
        if self.rejected:
            L += ["| Candidate | Match | Basis | Where | Why |", "|---|---|---|---|---|"]
            for r in self.rejected:
                L.append(f"| {cell(r['candidate'])} | {r['match_type']} | {r['basis']} | {cell(r['scope'])} | {cell(r['why'])} |")
        else:
            L.append("None.")
        blocked = [t for t in self.terms if t["status"] == "already blocked"]
        L += ["", "## Already blocked", "",
              f"{len(blocked)} search terms are already blocked by an existing negative" +
              (": " + "; ".join(f"{t['term']} by {t['note']}" for t in blocked[:5]) if blocked else "") +
              ("; and more in terms.csv." if len(blocked) > 5 else ".")]
        L += ["", "## Data notes", ""]
        L += [f"- {n}" for n in self.notes] or ["- None."]
        L += ["", "Missing data:", ""]
        L += [f"- MISSING: {m}" for m in self.missing] or ["- Nothing missing."]
        return "\n".join(L) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--search-terms", nargs="+", required=True, help="normalized search terms CSVs (Search and Performance Max)")
    parser.add_argument("--window", required=True, help="START:END dates of the search terms report")
    parser.add_argument("--campaigns", help="normalized campaign totals for the same window")
    parser.add_argument("--keywords", help="normalized positive keywords")
    parser.add_argument("--negatives", nargs="*", default=[], help="normalized negatives at every level")
    parser.add_argument("--list-attachments", help="normalized campaign and shared_set pairs for negative lists")
    parser.add_argument("--history", nargs="*", default=[], help="normalized search terms with conversions over a longer window")
    parser.add_argument("--context", help="path to .agents/google-ads-context.md")
    parser.add_argument("--intent", help="CSV of intent negatives: negative, match_type, campaign, ad_group, reason")
    parser.add_argument("--breakeven-cpa", type=float)
    parser.add_argument("--target-cpa", type=float)
    parser.add_argument("--breakeven-roas", type=float)
    parser.add_argument("--target-roas", type=float)
    parser.add_argument("--conversion-lag", type=int, default=0)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--actions-per-click", type=float, default=1.0,
                        help="most primary conversions one click can produce (lowers the break-even rate)")
    parser.add_argument("--shared-list", help="name of the negative keyword list for cross-campaign negatives")
    parser.add_argument("--list-campaigns", help="comma-separated campaigns the list covers (default: its attachments)")
    parser.add_argument("--currency")
    parser.add_argument("--today")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not 0.5 < args.confidence < 1:
        sys.exit("--confidence must be between 0.5 and 1")
    if args.actions_per_click < 1:
        sys.exit("--actions-per-click must be 1 or more")
    try:
        start, _, end = args.window.partition(":")
        dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except ValueError:
        sys.exit("--window must be START:END in YYYY-MM-DD form")
    Review(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
