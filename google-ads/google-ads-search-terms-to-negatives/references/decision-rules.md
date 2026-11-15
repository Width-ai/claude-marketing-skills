Adapted in part from the cut gates and n-gram guard in [thalesholleben/skill-google-ads](https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors) and "Reading Google Ads Data Without False Conclusions" in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines). Thresholds published by Nils Rooijmans, Adalysis, Brainlabs, and Lionel Fenestraz are described in our own words; none of their code is copied.

# Decision rules

`scripts/review_terms.py` applies every rule here. Read this file to explain a call, to choose the economics, or when the person asks why a search was or wasn't flagged.

## The break-even test (the primary test)

A search loses money when it converts below its **break-even conversion rate**:

> break-even conversion rate = CPC / break-even CPA

With zero conversions in N clicks, the highest conversion rate the data still allows (one-sided, 95% confidence) is `1 - 0.05^(1/N)`. A search is **proven waste** only when that upper bound is below its break-even rate. Put the other way, it needs at least `floor(ln 0.05 / ln(1 - break-even rate)) + 1` clicks with no conversion.

A rule of thumb follows, because `-ln 0.05` is about 3.0: **a search is proven to lose money once it has spent about three times the break-even CPA without converting.** Examples, computed by the script's own functions:

| CPC | Break-even CPA | Break-even rate | Clicks needed | Spend needed |
|---|---|---|---|---|
| $1.50 | $40 | 3.8% | 79 | $118.50 |
| $2.00 | $60 | 3.3% | 89 | $178.00 |
| $7.00 | $150 | 4.7% | 63 | $441.00 |
| $12.00 | $400 | 3.0% | 99 | $1,188.00 |

The same test runs on n-grams, where many small searches add up to enough clicks.

**Which CPA.** In order of preference:

1. **Break-even CPA** from the context's Economics section. This is the fair line: a search that costs less than break-even still makes money, even if it misses the target.
2. **Break-even ROAS**, turned into a CPA in code: average value per conversion (campaign totals) divided by the ROAS.
3. **Target CPA or ROAS**, labeled. It calls waste sooner than break-even would, so the review says so and asks for the break-even point.
4. **None:** the fixed defaults below, labeled.

If campaigns have very different economics (brand and non-brand, two product lines), run the script once per group of campaigns with that group's number.

**Why 95% is safe enough.** A search that really converts at exactly break-even gets flagged at most 5% of the time, and negating a break-even search loses no profit by definition. A search converting at twice break-even almost never gets flagged: about 0.2% at the clicks needed in the $7 / $150 row above. So the calls that cost money stay rare even across hundreds of searches. `--confidence 0.99` raises the bar to about 4.6 times the CPA.

**Several conversions per click.** Google counts conversions, not clicks that converted. If one click can produce more than one primary conversion (a call and a form), pass `--actions-per-click` with the most primary conversions one click can produce. That lowers the break-even rate and asks for more clicks before calling waste.

**Fractional conversions.** Data-driven attribution gives partial credit, such as 0.3. Any credit above zero counts as a conversion: that search is never negated on performance, and it protects itself from new negatives. For the bounds, conversions are rounded up for the upper bound and down for the lower bound, both on the cautious side.

**Conversion delay.** End the window one delay before today (see `references/data-and-queries.md`). With `--conversion-lag` and `--today`, the script warns when the window ends too late.

## Fixed defaults (only when economics are MISSING)

| Applies to | Default | Source | What it quietly assumes |
|---|---|---|---|
| Single searches | More than 60 clicks, cost over 5 (account currency), no conversions | Nils Rooijmans' negative keyword suggestions script (90-day lookback; he allows under 0.5 conversions, this skill requires zero) | 60 clicks with no conversion rule out about 4.9%, so it's only right when break-even is above that |
| N-grams | More than 150 clicks, no conversions | Adalysis n-gram guidance | 150 clicks rule out about 2.0% |
| Promotions | 2 or more conversions | Lionel Fenestraz | Nothing about cost |

Every finding made this way says "fixed default" in its evidence, and the review lists the missing economics under MISSING.

Cost floors such as "$10 to $20 spent with no conversion" (Fenestraz) or "one target CPA spent with no conversion" are review triggers, not proof. At one CPA of spend, a search converting exactly at break-even shows zero conversions about 37% of the time. This skill doesn't negate on them.

## What each status means

| Status | Rule | What happens |
|---|---|---|
| already blocked | An existing negative in scope already matches it (account level, an attached list, the campaign, or every ad group it appeared in), or the report marks it excluded | Nothing; listed for completeness |
| negate (intent) | Matches a "Terms we don't want" entry or a clear mismatch in the intent file, and passes every check | Proposed. No click count needed: you don't have to pay for a click to know a search is wrong |
| negate (performance) | Zero conversions and proven waste on the break-even test, at the level the negative goes on, and passes every check | Proposed |
| promote | 2 or more conversions at or under break-even CPA, not already an exact keyword anywhere in the account | Proposed as an exact keyword, created paused |
| review | Converts but the data proves it loses money; or matches Terms we don't want but converted; or proven waste but its negative failed a check | Listed for a person; never negated automatically |
| watch | Not enough data yet | Listed with the clicks and spend still needed, and roughly when at the current pace |
| keep | Converting and fine, or already an exact keyword | Nothing |

## The promotion threshold

A search becomes a keyword proposal when it has **2 or more conversions at a CPA at or under break-even**.

- Two is the floor because one conversion on one click proves nothing, and it matches Fenestraz's published rule.
- The bar is lower than for negatives on purpose. A new keyword is created paused and changes nothing until someone enables it, so a wrong promotion costs little. A wrong negative silently blocks buyers.
- Each promotion carries a confidence label. **Proven** means the lower 95% bound on its conversion rate is at or above break-even. **Early** means it qualifies but the data can't prove it yet. Proven ones are listed first, so a batch split by the change limit starts with them.
- Not promoted: searches already an exact keyword anywhere in the account (it notes where), searches longer than 10 words or 80 characters, and Performance Max searches (no keywords there; they're listed for a Search ad group the person picks).

## Review rules

- **Converting, but losing money with proof.** One or more conversions, and the upper bound on its conversion rate is below break-even. A negative would block a converting search, so it goes to a person. Better fixes come first: the bid, the ad, the landing page, or a check of what the conversion was.
- **Pattern losing money that includes converting searches.** An n-gram proven to lose money whose searches include a converting one (the converting searches are named). Narrower n-grams and exact negatives for the non-converting searches are still tested on their own.
- **Proven waste whose negative failed a check.** Usually because the negative would also block a keyword or a converting search. The rejected list says which.

## Watch

Each watched search gets the clicks still needed with no conversion, the spend that implies at its current CPC, and the days at the current pace. More than a year at the current pace usually means it will never be worth acting on unless its intent is clearly wrong.

Searches with impressions but no clicks use the campaign's CPC for the clicks needed.

## N-grams

- Each search is split into 1, 2, and 3 word sequences from its first 16 words, the part a negative can see. Each sequence counts once per search. Clicks, cost, and conversions are summed, and rates are recomputed from the sums (the Brainlabs search query mining method).
- An n-gram needs 2 or more different searches. One search is handled by an exact negative.
- Searches already blocked are left out, since they won't come back.
- Function words alone ("near me", "for", "the") are never proposed.
- When a shorter n-gram covers exactly the same searches as a longer one, the longer one wins: same evidence, narrower negative.
- Order of evaluation: pooled across a shared list's campaigns (only with `--shared-list`), then each campaign, then each ad group. Within each, 1 word before 2 before 3. Single searches come last.
- A search already covered by an earlier proposal doesn't count as evidence for a later one.
- N-grams overlap, so their totals don't add up to the account total.

N-grams catch what single searches can't. In a test account, "manual" appeared in 175 searches with three or four clicks each. No single search could be proven, but together they had 676 clicks and no conversions.

## What the statistics don't decide

Intent. Whether a search fits the offer comes from the context's "Business and offer" section and the person, never from a click count. A search can be relevant and still lose money (performance), or irrelevant at one impression (intent). Uncertain intent stays on watch until the data decides it.
