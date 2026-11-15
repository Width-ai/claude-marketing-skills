Adapted from the RSA output spec in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines), the claims rule in the campaign builder in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe), and the RSA and asset notes in [thalesholleben/skill-google-ads](https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors).

# Responsive search ads, sitelinks, and callouts

Limits and guidance checked against Google Ads Help and the Google Ads API reference (v26) in November 2026. If the google-ads-rsa-asset-writer skill is installed, it can draft the copy; this skill's validator still checks every line.

## Limits the validator enforces

| Item | Limit | Source |
|---|---|---|
| Headlines per responsive search ad | 3 to 15, each up to 30 characters | Google Ads Help, About responsive search ads |
| Descriptions per ad | 2 to 4, each up to 90 characters | Same |
| Display paths | 2, each up to 15 characters | Same |
| Wide characters (Chinese, Japanese, Korean) | Count as 2 | Same |
| Enabled responsive search ads per ad group | 3 | Google Ads Help, account limits |
| Sitelink text | 25 characters | Google Ads Help, sitelinks; API SitelinkAsset |
| Sitelink description lines | 35 characters each; set both or neither | API SitelinkAsset |
| Sitelinks needed to show at all | 2 | Google Ads Help, sitelinks |
| Callout text | 25 characters | Google Ads Help, callouts |

## Responsive search ads

**How many.** Write **2 ads per ad group** (Google recommends at least 2 rated Good or Excellent; it allows 3 enabled). Give the second ad a real difference: a different angle, a different set of headlines, or a different relevant landing page if the site has one. Two ads that share most headlines test nothing, and the validator warns.

**How many lines.** Google's Ad Strength guidance is to provide up to 15 headlines and 4 descriptions. Aim for that, but only with lines that are true and different. A shorter honest ad beats a full one with filler or invented claims. The validator warns when an ad has fewer than 15 and 4; that's a prompt, not a reason to invent.

**What goes in them.** A mix, so Google can combine lines for different searches:

- 3 to 5 headlines with the ad group's keywords. Put at least one keyword entirely within a headline (Google's Ad Strength guidance; the validator checks). A keyword longer than 30 characters goes in a description.
- Headlines with approved proof points (license, rating, years in business), each citing its source.
- The approved offer, if there is one, with its source and end date.
- Location headlines (the city or area), which make no claim.
- 2 or 3 calls to action ("Book a Visit Online", "Schedule Your Install").
- Descriptions that each make sense on their own, because any description can show alone. Description 1 shows most often.

**No pins by default.** Google says pinning isn't recommended for most advertisers and lowers Ad Strength. Pin only legally required text, to Headline 1 or Description 1, and note it as a by-hand step: pins are set in Editor after import. With AI Max final URL expansion on, pins can be ignored; legally required text then needs AI Max's text disclaimers instead.

**Editorial rules** (Google Ads editorial policy; the validator warns):
- no repeated punctuation ("!!"), and no exclamation mark in headlines
- no emoji or decorative symbols
- no all-caps words except real acronyms
- no phone numbers in ad text (use a call asset)
- no words the context file lists under words to avoid
- no competitor names when the competitor policy says no

## Every claim needs a source

A claim is anything a customer could hold the business to: a number, a price, a percentage, a rating, a review count, years in business, a guarantee or warranty, "licensed", "certified", "insured", "free", "same-day", "best", "top", "#1", "fastest", "trusted", an offer, a discount. The validator treats any line with a digit, a currency symbol, a percent sign, or one of these words as a claim.

Every claim line cites a source ID from the build spec's `sources`:

| Source type | What it is | Rule |
|---|---|---|
| `context` | An approved offer, price, or proof point in the context file's Business and offer section | Copy the wording exactly into `text` |
| `person` | Something the person stated and approved in this conversation | Quote their words |
| `page` | Something seen on the website | Starts `confirmed: false`. The plan marks it CONFIRM. The Editor builder refuses it until the person confirms and you set `confirmed: true`. |

Rules the validator checks:

- A claim line with no source is an error. Reword it to remove the claim, or find an approved source.
- Every number in the line must appear in the source's text. "4.9 stars" against a source that says 4.8 is an error.
- A source with `expires` in the past is an error. Offers with end dates carry `expires`.
- Lines that make no claim ("Water Heater Installation", "Book a Visit Online", "Serving Richmond and Henrico") need no source.

Never invent an offer, a price, a statistic, a rating, a review, a testimonial, a guarantee, or a service the business doesn't list. If the ads feel thin without one, say what proof would help and ask for it.

Claims with extra policy rules (Google's unreliable claims policy): "guaranteed" results need a clear money-back or guarantee policy the customer can see, and testimonials with specific results need a "results vary" disclaimer. If a claim needs a disclaimer, the disclaimer goes in the same line or Description 1.

## Sitelinks

- Write **6** if the site has enough real pages; Google says 6 or more improve Ad Strength. At least 2 are needed for any to show.
- Each sitelink goes to a real page other than the ads' landing page: booking, reviews, about, offers, a related service. Check the page exists.
- Text up to 25 characters; two description lines up to 35 each. Fill both lines or neither. Descriptions follow the same claim rules as ads; a sitelink's `source` covers its text and both lines.
- Build them at the campaign level. They show in every ad group of the campaign.

## Callouts

- Write **4 or more**, each up to 25 characters. Google can show up to 10 at once, depending on space.
- Callouts are short facts: "Book Online Anytime", "Family-Owned Since 1998". Same claim rules as ads.
- Build them at the campaign level. Ad group callouts would replace campaign callouts in that ad group.

## Not built here

Structured snippets, call assets, images, price, promotion, and lead form assets are not in this version. Mention in the plan any the business should add by hand, such as a call asset when calls matter (call-only ads can't be created since February 2026; a call asset on a responsive search ad replaces them).

## Output in the plan

`render_plan.py` prints every headline, description, sitelink, and callout with its character count against the limit and its source, and lists every source with where it came from and whether it's confirmed. The person approves the copy from that table.
