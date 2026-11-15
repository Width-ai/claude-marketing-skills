Adapted in part from references/exclusion-checks.md in [treboutat/google-ads-search-term-scorer](https://github.com/treboutat/google-ads-search-term-scorer) (MIT, Copyright (c) 2026 TNT Growth) and the negative keyword sections of references/google-search-playbook.md in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines). Platform facts checked against Google Ads Help and the Google Ads API docs in November 2026.

# Negatives: matching, match types, levels, and checks

## How negative keywords match

| Negative | Match | Blocks | Doesn't block |
|---|---|---|---|
| `running shoes` | Broad | blue running shoes, shoes running | running shoe |
| `running shoes` | Phrase | blue running shoes | shoes running |
| `running shoes` | Exact | running shoes | blue running shoes |

- Negatives don't match close variants, plurals, or synonyms. `flowers` doesn't block "red flower".
- Google handles casing and misspellings of a negative automatically, so real blocking can be a little wider than the script's check.
- A broad or phrase negative is ignored past the 16th word of a search. The script only looks at the first 16 words.
- Accented and unaccented words are different negatives, and `&` is not `and`.
- A one-word phrase negative blocks exactly what the same one-word broad negative blocks.
- In Google Ads' text boxes, `[exact]` and `"phrase"` set the match type and no marks means broad. A Google Ads Editor import with no match type can default to broad, so the files this skill writes always set it.

Source: Google Ads Help, "About negative keywords" (answer 2453972).

## Choosing the match type

Use the narrowest negative that covers what should be blocked.

| Match | The skill uses it for | Why |
|---|---|---|
| Exact | One search proven to lose money on its own | Blocks that search and nothing else |
| Phrase | N-gram patterns, and intent words from Terms we don't want or the intent file | Blocks every search containing those words in that order, which is exactly what the n-gram measured |
| Broad | Only when the intent file asks for it, because every word order of that combination is unwanted | It blocks searches the data never measured, so it's never generated from performance |

AI Max and Performance Max searches: Google reports some searches (from AI Mode, Lens, AI Overviews) as a best approximation of intent rather than the exact words typed. An exact negative on such a search may not stop the same intent arriving under different words next week. When the same unwanted intent shows up in several searches, prefer the phrase pattern. The script warns on exact negatives for these searches.

## Choosing the level

| Level | When the script picks it | Notes |
|---|---|---|
| Shared list | Only with `--shared-list`. Intent negatives that are safe in every campaign the list covers, and performance negatives proven on the pooled data of those campaigns and safe in all of them | Editing a list changes every campaign attached to it. Creating a list doesn't apply it. Up to 5,000 negatives per list and 20 lists per account |
| Campaign | The default | Up to 10,000 negatives per campaign |
| Ad group | When the campaign-level negative would block a live keyword or a converting search in another ad group of the same campaign, and the ad group where the waste is has its own proof (performance) or the intent applies (intent) | This is routing: block the search where it does badly so the right ad group gets it. Not available in Performance Max, which has no ad groups |
| Account | Never proposed | It applies to search and shopping inventory in every Search, Performance Max, App, Shopping, Smart, and Local campaign, including future ones, up to 1,000 negatives. If the person wants one, they add it under **Admin > Account settings > Negative keywords** |

Brand and competitor routing are business decisions, not search term findings. Don't make own-brand, competitor, or offer-specific negatives account-wide because several campaigns need them. A negative in one campaign doesn't make another campaign win the search: check the campaign meant to get it is running and eligible.

## The checks every candidate goes through

**Hard stops.** The negative isn't proposed at that level:

- It would block a protected term itself. For broad and phrase that means every search containing the protected term; for exact, the bare protected term. Once a negative fails this, it's not tried at any other level.
- It would block a live or paused positive keyword in scope (the keyword's own text, under the negative's match type).
- It would block a search that converted, in this window or in the longer history, in scope.
- It's longer than Google allows for a keyword (10 words, 80 characters).
- It blocks no search that isn't already blocked or already covered by an earlier proposal.
- Performance negatives only: it isn't proven at that level. An n-gram negative also needs 2 or more searches.

**Warnings.** The negative is proposed, and the warning goes in the table and the change set for the person to judge:

- It blocks longer searches that contain a protected term ("jobs" blocks "riverside plumbing jobs"). The protected term itself is still reachable.
- A phrase or broad negative shares a word with a protected term. The warning says which other words a search must contain to be blocked.
- It blocks searches that had secondary conversions only.
- It's an exact negative on an AI Max or Performance Max search.

The google-ads-apply-changes validator runs its own checks again before anything is applied. It also warns when a negative shares any word with a protected term, exact negatives included.

**Blocks and must not block.** Every proposed negative shows the costliest search it blocks and a nearby search it must not block: a converting search, then a keyword, then a protected term that shares a word with the negative but isn't blocked by it. If the "must not block" example looks like something the negative should block, or the "blocks" example looks like a buyer, drop the line.

## Campaign types

| Type | Negative keywords | Levels | Search terms come from |
|---|---|---|---|
| Search | Yes: broad, phrase, exact | Ad group, campaign, list, account | `search_term_view` |
| AI Max for Search (a setting on a Search campaign) | Yes. Google says negatives are still respected | Same as Search | `search_term_view`, with `segments.search_term_match_source` showing `AI_MAX_KEYWORDLESS` or `AI_MAX_BROAD_MATCH` |
| Shopping | Yes | Ad group, campaign, list, account | `search_term_view` |
| Performance Max | Yes, for Search and Shopping inventory only | Campaign (up to 10,000 since March 2025), negative keyword lists, account | `campaign_search_term_view` |
| Demand Gen | Not eligible (Google Ads Help) | None | Skipped by the script |
| Display and Video | Work as topic exclusions, not search matching | Out of scope | Skipped by the script |

Google advises waiting at least two weeks after turning on AI Max before making some optimization changes. Intent negatives for clear mismatches can still go in; for performance negatives in a campaign where AI Max was turned on less than two weeks ago, say so in the review.

Google Ads Editor 2.11 and later can add negative keyword lists to Performance Max campaigns. If an Editor import rejects a Performance Max negative, update Editor or add it in the Google Ads interface.

## Words that need checking before they become negatives

These are prompts to check against the offer, not a list to paste. Each can be buyer language for some business.

| Words | Exclude only when |
|---|---|
| jobs, careers, salary, hiring | The search is about getting a job. For home services, "jobs" can mean booked work ("how to get more hvac jobs"); for recruiting or payroll products it's the product |
| how to, tutorial, course, diy, template, examples | Learning or doing it yourself is outside the goal. Tutorials and templates are part of many buying journeys |
| login, support, not working, error | The search is outside the offer. Repair services and support software win customers on problem searches |
| free, cheap, discount, coupon | It's an unwanted free substitute. The business may have a free trial, free estimate, or free shipping |
| wrong product or audience | The business really doesn't sell it or serve them. Confirm the limit with the person |
| fraud, spam, privacy, compliance | Never infer a bad customer from a worrying word: these can be the product category |
| conditions, cost, insurance, place names (health, legal, local services) | Verified that the service or area isn't offered |
| competitor names | The Competitor policy section says to exclude them |
| the brand itself | The campaign is non-brand and brand searches belong in the brand campaign, per the person |

## Writing the intent file

The intent file is where Claude records clear mismatches judged against the offer. It's a CSV:

```csv
negative,match_type,campaign,ad_group,reason
septic,phrase,,,"Septic services aren't offered (Business and offer: drains, water heaters, emergency repairs)"
yourself,phrase,,,"Do-it-yourself searches; the business sells repair visits"
```

- Leave `campaign` and `ad_group` blank to apply wherever the negative matches a search in the report. Fill them to limit it.
- Only clear mismatches with the offer as written in the context or said by the person. The reason names what the business doesn't do.
- Only from searches in the report. The script refuses an intent negative that matches no search, because negatives without evidence belong to a starter list, not a search terms review.
- Use the narrowest words that capture the unwanted intent: "plumbing school", not "school", if "school" could also be "school district contract".
- Never for a search that converted; the script refuses those anyway.
- If you're unsure, leave it out. It stays on watch, and the data will decide.
