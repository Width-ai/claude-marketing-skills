Adapted in part from the ad-creative skill in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines) and rsa-ad-copy-writer in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe).

# Writing rules

Read this before writing any copy. The limits and policy points were checked against Google Ads Help, the Google Ads policy pages, and the Google Ads API reference on 2026-11-15. Google changes them now and then: when a connector has a metadata tool, or when Google rejects something, trust the account over this page.

## Limits

| Item | Limit | Count | Source |
|---|---|---|---|
| RSA headline | 30 characters | 3 to 15 | Google Ads Help, About responsive search ads |
| RSA description | 90 characters | 2 to 4 | same |
| Display path | 15 characters each | path 2 needs path 1 | same; API reference (ResponsiveSearchAdInfo) |
| Enabled RSAs | | 3 per ad group | Google Ads Help, account limits |
| Sitelink text | 25 characters (12 in double-width languages) | at least 2 to show; keep 4 or more; 6 with descriptions for busy ad groups | Help, About sitelink assets; API reference (SitelinkAsset) |
| Sitelink description lines | 35 characters each | both lines or neither | API reference (SitelinkAsset) |
| Callout | 25 characters | | API reference (CalloutAsset) |
| Structured snippet value | 25 characters | 3 to 10 values per header | API reference (StructuredSnippetAsset) |

Chinese, Japanese, and Korean characters count as 2. The checker counts this way, and it counts keyword insertion and customizer tokens by their default text.

Structured snippet headers (exact English names): Amenities, Brands, Courses, Degree programs, Destinations, Featured hotels, Insurance coverage, Models, Neighborhoods, Service catalog, Shows, Styles, Types.

## Claims: the rule that matters most

A claim is anything a customer could hold the business to:

- a number of any kind: years, hours, customers, reviews, steps, minutes
- a percentage, a price, or a discount
- "free", "complimentary", "no cost"
- a guarantee, warranty, refund, money-back promise, or price match
- a superlative ("best", "#1", "top-rated", "fastest", "cheapest", "leading") or a comparison ("better than", "unlike", "vs")
- a rating, review count, or star score
- an award, "voted", "as seen on", or "featured in"
- a credential: licensed, insured, bonded, certified, accredited, BBB
- a sale, a deal, or a deadline ("ends Friday", "this week only", "limited time"), and stock claims ("only 3 left")

Every claim must come from an approved item: the context file's "Business and offer" section (offers, prices, proof points), or the approved-claims file. Nothing else counts:

- **Landing page facts aren't approved yet.** A page can be out of date or claim things the business can't back up in an ad. List them as "seen on the page, needs approval" and ask. If the person approves one in the chat, add it to the approved-claims file with who approved it and when.
- **Items marked "confirm" aren't approved.** The context skill marks site-sourced facts this way until the person confirms them.
- **Ended offers aren't approved.** The checker reads end dates and rejects claims that rely on an offer past its date, and it warns two weeks before an offer ends.
- **Deadlines must be real.** "This week only" needs an approved offer that ends within a week. Never invent urgency.
- **Use approved wording.** "Free in-home estimates" doesn't approve "Free shipping"; "$149 drain cleaning" doesn't approve "Installs from $149". The checker compares the words around each claim with the approved item.
- **Numbers that come from a keyword** ("24 hour plumber") still make a claim. Confirm the business really offers it.

The checker can't catch every claim. "Same-day service", "background-checked techs", and "family-owned" carry no trigger word, but they are still claims. Use them only when they're approved, the same as anything else.

### What Google's policies say

- **Guarantees:** Google's Unreliable claims policy requires a clear, easy-to-find refund (money-back) policy when an ad guarantees results.
- **Testimonials with results:** need a visible disclaimer that results aren't guaranteed. Testimonials implying typical results need third-party verification or a noticeable disclaimer.
- **Offers:** Google's Misrepresentation policy disallows promising offers the landing page doesn't deliver. An offer in the ad must be on the page; the checker warns when it isn't, given the page text.
- **Superlatives and comparisons:** Google's current Misrepresentation and Unreliable claims pages don't mention "best" or "#1". Google has required visible third-party proof for them in the past, and this skill keeps that bar: use one only when it's an approved claim with a source, and only when the landing page shows the proof. The checker warns on every approved superlative or comparison.
- **Competitors:** follow the context file's competitor policy. If it doesn't say "yes" to naming competitors in ad copy, don't. Trademark owners can complain about their names in ad text.
- **Required disclaimers:** text that must show in every ad goes in a description pinned to Description 1. In campaigns using AI Max text customization, Google's text disclaimers are the way to guarantee required text; set those in Google Ads.

## Writing an RSA

Every headline must make sense on its own and next to any other headline, because Google mixes them. Description 1 must make sense alone, because only Headline 1 and Description 1 are sure to show.

Aim for 10 to 15 headlines and all 4 descriptions. A starting mix for 15 headlines:

| Angle | How many | Where it comes from |
|---|---|---|
| Keyword | 4 to 5 | The ad group's top converting keywords and search terms, so the searcher sees their own words |
| Benefit or problem solved | 3 | The landing page's promise, or lines that already serve well |
| Proof | 2 to 3 | Approved proof points |
| Offer | 2 | Approved offers and prices |
| Call to action | 2 | A verb plus what happens next ("Book Your Repair Today") |

Descriptions: each carries a different fact and ends with a reason to act. Don't repeat a headline in a description; add proof, handle an objection, or explain the offer.

Shift the mix to the evidence. With no approved offer, write more benefit and proof lines and say "no approved offer" in the output. Never fill a slot with an invented claim.

### Angles

Before writing lines, settle 3 to 5 angles, each a different reason to click: pain point, outcome, proof, identity ("for landlords"), speed, price. A second RSA in the same ad group should lead with a different angle from the first, not reword it. If two RSAs share more than half their headlines, the checker warns.

### Learning from existing ads

When existing ads and asset metrics are available (see `references/evidence-queries.md`):

1. Keep lines that serve and convert. Carry the best ones over with source `kept`.
2. Replace lines with under 10% of the impressions of the most-served line of their kind and no conversions. The checker marks these "low serving".
3. Write 4 to 6 short style notes from the most-served lines: capitalization (Title Case or sentence case), tone, recurring phrases, how calls to action are worded. Match them, unless the context file's brand voice section says otherwise.
4. Don't copy existing lines word for word into a new ad unless they're `kept`. A new RSA where every headline already runs tests nothing new; the checker flags it.

Asset metrics overlap, because one impression shows several lines. Compare lines with each other; never add them up. On low-volume ad groups, a line's numbers are noise below a few hundred impressions: judge on craft and say so.

## Pinning

Default: no pins. Google says pinning isn't recommended for most advertisers, and it lowers Ad Strength.

When a line must always show (a required disclaimer, a brand rule):

- Pin to Headline 1, Headline 2, or Description 1. Lines pinned to Headline 3 or Description 2 aren't guaranteed to show.
- Pin 2 or 3 options to the same position, never one alone.
- Leave most headlines unpinned.

The change set's `add_rsa` action can't carry pins, so the builder writes them as manual steps to do on the paused ad before it's enabled.

## Paths

Name the place and the service, such as `water-heaters` / `austin`. Use hyphens, not spaces. Take the place from the ad group's targeting or keywords, never a guess. When neither names a place, use the service alone.

## Sitelinks

- Link text up to 25 characters; each description line up to 35. Write both lines or neither.
- Send each sitelink to a different page from the ad's landing page, on the same domain. Google allows other domains only in limited cases.
- Never reuse link text, even with different URLs. Google disallows it.
- No exclamation marks, and no punctuation at the start. Google disallows both for sitelinks.
- Use pages that exist. Propose destinations only from pages the person names or the account already uses, and ask the person to confirm each is live.
- Write link text that says what's on the page ("Tankless Options"), not navigation labels ("About Us").
- Levels: account, campaign, or ad group. Sitelinks at one level don't combine with another campaign's.

## Callouts

- Up to 25 characters. No exclamation marks, no punctuation at the start.
- Don't repeat ad text, sitelink text, or other callouts in the same ad group, campaign, or account. Google disapproves a callout like "Free shipping" when the same phrase is in a headline.
- Aim for 4 or more.

## Structured snippets

- Pick the header that truly fits. Values must match it ("Service catalog" lists services sold, not features).
- 3 to 10 values of up to 25 characters, one item per value.
- No promotional words ("Sale", "Free shipping"), no exclamation marks, no repeated values.

## Google's editorial rules

The checker enforces these. Errors are rules Google states; warnings are risks.

| Rule | Level |
|---|---|
| Repeated punctuation ("!!", "??", "...") | Error |
| Emoji, arrows, bullets, decorative symbols, single-byte katakana | Error |
| Asterisks as decoration ("*flowers*") | Error; a lone asterisk is a warning (allowed only to flag a condition shown on the page) |
| Letters replaced by symbols ("fl@wers") or spelled with gimmicky spacing or periods ("F.L.O.W.E.R.S.") | Error |
| Capitalization for emphasis ("FREE", "SALE") or a whole line in capitals | Error; other all-caps words are warnings, since acronyms are fine |
| A word repeated back to back | Error |
| Phone numbers in ad text (use a call asset) | Error |
| Extra spaces | Error |
| Exclamation mark in a sitelink, callout, or snippet | Error |
| Exclamation mark in a headline | Warning: Google has disapproved them, though the current policy pages only ban repeated ones |
| Star symbols, trademark symbols | Warning |
| Duplicate lines | Error; near duplicates are warnings |

## No AI tells

Copy that reads as generated looks like every other ad on the page. Check the whole batch:

- No stock phrases: "unlock the power", "say goodbye to", "take it to the next level", "look no further", "elevate your", "seamless", "game-changer", "we've got you covered".
- No em dashes in ad text.
- No "click here"; name the action.
- No stacked negations to fill space ("No setup. No fees. No contracts."). Keep the one that matters and use the space for a fact.
- No vague calls to action ("Get started today", "Join thousands of happy customers"). Say what happens next.
- Vary sentence shapes across lines. Ten headlines that open the same way read as generated, even when each is fine alone.
- Specific beats general: "Same-Day Water Heater Repair" over "Fast, Reliable Service".
