# Reading Google Ads data without false conclusions

Adapted from "Reading Google Ads Data Without False Conclusions" and "Account Audits, Scoring & Recommendation Guardrails" in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines), and the GAQL keyword-inventory notes in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici).

Google Ads reports are partial by design and plausible by accident. Most wrong conclusions come from not knowing what the data leaves out, not from bad reasoning. Read this before you interpret anything.

## What the data hides

**Search terms are a sample.** Google withholds queries searched by too few people. On low-volume accounts, half or more of clicks can have no disclosed search term, and the visible terms skew toward common searches. Every claim about "what this campaign is buying" carries the ratio from `metrics.py coverage`: "of the 13 clicks Google shows, out of 33 total." Nothing recovers the withheld queries; analytics and CRMs see what a visitor did, never what they typed.

**Names describe intentions, not contents.** A campaign named "Competitor" can hold informational keywords. Read the keywords and search terms; treat names as labels someone typed once.

**"Conversions" is several things in one column.** It counts actions marked primary, plus secondary actions a campaign's custom goal pulls in. `all_conversions` adds the rest. Segment by conversion action before calling anything a lead or a sale, and check the account context for what each action really measures.

**One ad group can send traffic to several pages.** Ads carry their own final URLs, and old pages stay in rotation. Check which destinations serve before judging a landing page.

**Conversions are dated by click.** A conversion recorded today can show up dated a week earlier. Recent days undercount on any account with conversion delay; read them as incomplete and never call a trend from them alone.

**Identical campaign names are usually experiment arms.** Check `campaign.experiment_type` and `campaign.serving_status` before believing there's a duplicate.

**Change history is short.** Field-level detail covers 30 days. Google Ads Editor changes aren't in the API's history at all. A shift four months ago may have no recoverable explanation; say so instead of guessing one.

**Other people change the account.** Staff, scripts, automated rules, and recommendations Google applies automatically all leave changes. `client_type` in change history says which tool made each change. Report the tool, not a guess at who or why.

## Positive and negative keywords

Positive and negative keywords live in the same resources, separated by a negative flag. Counting negatives as positives creates fake "zero impression" keywords, fake self-blocking, and recommendations that would delete the account's negatives.

- Build two inventories. Positives: `negative = FALSE`. Negatives: ad group negatives, campaign negatives, negative keyword lists (only the ones attached to a campaign count), and account-level negatives.
- Join performance only to positives. Negatives never enter keyword counts or zero-impression findings.
- A negative blocks a positive only when it's in scope (same ad group, same campaign, an attached list, or account level) and matches under its own match type: exact means the same words in the same order and nothing else; phrase means the words appear together and in order; broad means every word appears in any order. Negatives don't match close variants, plurals, or synonyms.
- Treat a finding as suspect and rebuild the inventory if the number of "self-blocked" keywords equals the number of negatives, or if the keyword total equals positives plus negatives.

## The window is not the picture

- Find out how long something has run before quoting an efficiency number. Quote recent and lifetime CPA when they differ.
- Don't pool across configuration changes. If bids, keywords, budget, ads, or targeting changed inside the window, the window is several experiments averaged together. Split it at the change date.
- Bid strategies in learning are unreadable. If `primary_status` says learning, don't judge performance on it. Fixing a verified break (tracking down, wrong URL) still comes first.
- Budget-limited target CPA and target ROAS campaigns have spent toward their target, rather than beating it, since August 17, 2026. CPA trends that break on that date need a new baseline.

## Small numbers

Most false findings in small accounts are sample-size errors. Zero conversions in N clicks rules out only conversion rates at or above this (95% confidence):

| Clicks | Rules out CVR at or above | What you can say |
|---|---|---|
| 5 | 45% | Nothing |
| 10 | 26% | Still nothing useful |
| 30 | 10% | Can begin doubting a strong conversion rate |
| 50 | 6% | Meaningful for high-intent search |
| 100 | 3% | Underperforming if break-even CVR is above 3% |

Before calling spend wasted, work out the break-even conversion rate: CPC divided by target CPA. If the data can't rule out converting at break-even, the term isn't failing, it's unmeasured. `metrics.py zero-conv` and `summary --target-cpa` do this math. "Let it run" is only honest with a date: give the number of clicks needed and roughly when that will happen at current volume.

One conversion on one click proves no more than zero on five disproves.

## Facts, hypotheses, missing data

Label every claim:
- **Verified:** pulled this session, unfiltered, and reconciled against a total.
- **Inferred:** reasoned from verified data; could be wrong.
- **Stale:** from a document, an earlier session, or the client, with its date attached.

End every analysis that could lead to a decision with three short lists: facts (with dataset and window), hypotheses (with confidence), and missing data (and how it could change the answer). Write MISSING next to any input you didn't have and leave it out of calculations.

Before anything reaches a client, ask: could they disprove this in a minute with their own account access? Volunteer the limits first: the disclosed share of clicks, the sample size, the changes inside the window.

## Never

- Average ratios across rows. Recompute from summed numerators and denominators.
- Add conversions from different platforms or attribution windows into one number. Show them side by side.
- Treat a broad benchmark as pass or fail. It's a question to investigate, not a verdict.
- Suggest negative keywords without a search terms report and a check that they wouldn't block converting queries.
- Describe a landing page from its URL. Open it.

## Conclusions that sound right

| Sounds like | Usually |
|---|---|
| "This campaign has zero conversions" | True on the day someone wrote it down |
| "The search terms are junk" | You're seeing a fraction of the clicks |
| "That ad group is wrong-intent" | It's named that; the keywords say otherwise |
| "$X wasted on those terms" | Below any readable sample size |
| "It converted, so the term works" | One conversion on one click is noise |
| "Performance declined in August" | Bids changed three times that month |
| "It got a demo" | It got a conversion; check which action |
| "Nobody touched it last quarter" | Change history only covers 30 days |
