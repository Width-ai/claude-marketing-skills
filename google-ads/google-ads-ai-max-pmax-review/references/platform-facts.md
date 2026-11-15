# AI Max and Performance Max facts (checked 2026-11-15)

Google changes these features every few months. Treat every line as dated. When the account shows something different (a setting that exists or doesn't, a report that returns rows or doesn't), believe the account and say the fact below may be out of date. Sources are linked so they can be re-checked.

## AI Max for Search

- **What it is.** An optimization layer inside a standard Search campaign, not a campaign type. Three parts ([TechWyse](https://www.techwyse.com/?p=77786)):
  - **Search term matching:** broad match plus keywordless matching, using the keywords, assets, and landing pages as signals.
  - **Text customization:** generates headlines and descriptions from landing pages, ads, and keywords. Shown as "Google AI" in the "Added by" column of asset reports ([Google Ads Help](https://support.google.com/google-ads/answer/16470459?hl=en)).
  - **Final URL expansion:** sends a click to a page on the same domain that Google judges more relevant than the final URL.
- **Defaults.** In the Google Ads interface, final URL expansion is on by default once AI Max is on ([Google Ads Help](https://support.google.com/google-ads/answer/16230205?hl=en)). Through the API, enabling AI Max turns on only search term matching, and text customization and final URL expansion default to off for Search ([Google Ads API](https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/getting-started)). Read the campaign's real settings; don't assume either default.
- **Dependencies.** Final URL expansion needs text customization. Turning off text customization also turns off final URL expansion. Pinned headlines aren't used when a different URL is chosen ([Google Ads Help](https://support.google.com/google-ads/answer/16230205?hl=en)).
- **Controls.** Negative keywords (campaign or ad group), URL exclusions (campaign level only), brand inclusions and exclusions through brand lists. Brand exclusions attach at campaign level and only to Search campaigns with AI Max on ([Google Ads API reporting guide](https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/ai-max-reporting)).
- **Dates** ([Relevant Audience timeline](https://www.relevantaudience.com/google-ads-en/google-ads-deprecations-2026-2027-timeline/), a third-party compilation):
  - Out of beta in April 2026.
  - Text disclaimers added in May 2026: the way to guarantee legally required text with text customization and final URL expansion on, instead of pinning ([Google](https://business.google.com/us/accelerate/announcements/ai-max-for-search-campaigns/)).
  - Since August 3, 2026, new campaign-level broad match and legacy automatically created assets can't be created.
  - Eligible campaigns using those were moved into AI Max from September 1 to 30, 2026. A campaign can have AI Max on without anyone in the business choosing it.
  - Dynamic Search Ads: Google's August 2026 developer blog and its [DSA upgrade post](https://blog.google/products/ads-commerce/dsa-upgrade-to-ai-max-2026/) set the automatic upgrade for February 2027; some Help pages still say September 2026. Read the account's actual state.
- **Reporting.** The search terms report has an AI Max match type and a Source column; the "Search terms and ad combinations" view shows the headline and landing page used; the keywords report has total rows for AI Max expanded matches and landing page matches; the landing pages report has a "Selected by" column ([Google Ads Help](https://support.google.com/google-ads/answer/16470459?hl=en)). Google says the "AI Max" match type filter can show lower numbers than the full report.
- **Waiting period.** Google advises waiting at least two weeks after turning AI Max on before changes such as adding negatives ([Google Ads Help](https://support.google.com/google-ads/answer/16470459?hl=en)).
- **Google's claim.** Advertisers already using search term matching see 7% more conversions or conversion value on average at a similar CPA or ROAS after adding text customization and final URL expansion (Google internal data, non-retail, 2026) ([Google](https://business.google.com/us/accelerate/announcements/ai-max-for-search-campaigns/)).
- **Practitioner findings.** Context for why the review matters, never a prediction for this account:
  - Smarter Ecommerce, 250+ retail Search campaigns: AI Max converted at "roughly 35% lower ROAS" than other match types in the same campaigns. A four-month test by Xavier Mantica measured CPA of $100.37 for AI Max against $52.69 for exact and $43.97 for phrase ([PPC Land, Nov 2025](https://ppc.land/independent-tests-show-ai-max-underperforms-traditional-match-types/)).
  - Practitioners report URL exclusions that "are not accurate", specific product searches all landing on one generic page, and concern about Search Partner traffic. Google's own reporting calls search term results a "best approximation" ([PPC Land, May 2026](https://ppc.land/advertisers-push-back-as-google-sunsets-dsa-for-ai-max/)).

## How Search, AI Max, and Performance Max share a search

From [Google Ads Help: keyword matching options](https://support.google.com/google-ads/answer/7478529?hl=en-GB):

1. An exact match keyword identical to the search wins over everything else.
2. Phrase and broad keywords, including AI Max, share priority with identical Performance Max search themes.
3. Otherwise the most relevant ad group or asset group is picked, and Ad Rank breaks ties.

A keyword can still lose its search to Performance Max when the Search campaign is limited by budget, the keyword has low volume, its ads are disapproved, or its targeting isn't met. So a Performance Max search term identical to an exact keyword is a sign worth checking, not proof of a fault.

## Performance Max

- **Reporting added 2025 to 2026** ([PPC Land](https://ppc.land/google-wraps-up-performance-max-feature-rollouts-in-2025/)):
  - search terms report, with a source column showing keywordless matching or a search theme
  - channel performance (Search, Search partners, YouTube, Display, Discover, Gmail, Maps)
  - campaign-level negative keywords (API from v20, June 2025; up to 10,000 per campaign per [Google Ads API](https://developers.google.com/google-ads/api/docs/performance-max/create-campaign-criteria?hl=en)) and negative keyword lists (Google Ads Editor 2.11, November 2025, per [PPC Land](https://ppc.land/google-ads-editor-2-11-adds-performance-max-search-term-reports/))
  - brand exclusions, final URL expansion asset reporting, URL exclusions, search themes raised to 50 per asset group
- **Channel data starts June 1, 2025.** Earlier dates have no channel split, even in the API. Earlier API versions returned a single cross-network value (`MIXED`) ([Google Ads API blog, Jan 2026](https://developers.google.com/ads/blog/posts/2026/01/introducing-channel-level-reporting-for); [PPC Land](https://ppc.land/google-finally-lets-developers-see-where-performance-max-ads-actually-run/)).
- **Brand exclusions** apply to Search and Shopping inventory only. Brand lists are built at account level from Google's brand library and applied per campaign; they match across languages and variants, so misspellings don't need separate entries. Brand settings limit reach and can lower volume ([Google Ads Help](https://support.google.com/google-ads/answer/13721847?hl=en)).
- **Final URL expansion** is on by default. It can be turned off, or URLs excluded, under Asset optimization in campaign settings. Changes take 24 to 48 hours. With it on, a page feed doesn't restrict where ads go ([Google Ads Help](https://support.google.com/google-ads/answer/14337539?hl=en)).
- **Placements.** The placement report shows impressions only. Google says it's a brand safety tool, not a performance report; Google Search isn't a placement; "Google Owned & Operated" and "anonymous.google" group many placements together ([Google Ads Help](https://support.google.com/google-ads/answer/11465047?hl=en)).
- **Placement exclusions.** Account-level placement exclusions that cover Performance Max launched in January 2026 and looked like a beta in some accounts ([PPC Land](https://ppc.land/google-gives-advertisers-one-placement-list-to-rule-them-all/)). In January 2025 a Google API specialist said placement exclusions made through the API don't apply to Performance Max ([Search Engine Roundtable](https://www.seroundtable.com/google-ads-api-placement-exclusions-pmax-38671.html)). Make them in the Google Ads interface.
- **Channel opt-outs.** Switching off Search partners and Display inside Performance Max was a limited pilot in mid-2026 ([PPC Land, July 2026](https://ppc.land/google-lets-some-pmax-advertisers-switch-off-search-partners-and-display/)). Don't recommend it unless the person sees the setting.
- **Asset groups** ([Google Ads Help: specs](https://support.google.com/google-ads/answer/17091269?hl=en); [asset group best practices](https://support.google.com/google-ads/answer/14528220)):

| Asset | Required | Recommended |
|---|---|---|
| Headlines (30 characters) | 3, at least one of 15 characters or fewer | 11 or more, up to 15 |
| Long headlines (90) | 1 | 2 or more, up to 5 |
| Descriptions (90) | 2 | 4 or more, up to 5 |
| Landscape images (1.91:1) | 1 | 4 or more |
| Square images (1:1) | 1 | 4 or more |
| Portrait images (4:5) | none | 2 or more |
| Square logo | 1 | 1 |
| Landscape logo (4:1) | none | 1 |
| Video | none (Google may auto-generate one) | your own, in horizontal, square, and vertical |
| Business name (25) | yes | matches the domain or legal name |

  Brand guidelines (required for new campaigns from January 2025) can hold the business name and logo at the campaign level, so check campaign assets before calling them missing. Feed-only asset groups in Merchant Center campaigns can legitimately have no creative assets. Wait two to three weeks before replacing low performers; Ad Strength takes a few days to update after edits.

## Bidding and waiting periods

- **August 17, 2026 bidding change.** Budget-limited target CPA and target ROAS campaigns (Search, Shopping, Performance Max, Demand Gen, Travel) now spend toward their target instead of beating it. A $10 target that delivered $5 drifts toward $10. Google doesn't change targets or budgets for you. A CPA trend that breaks on that date needs a new baseline ([Google Ads Help](https://support.google.com/google-ads/answer/17061251)).
- **Smart Bidding.** Judge over at least two weeks, with the window ending at least one conversion delay in the past, outside learning periods ([Google Smart Bidding best practices](https://services.google.com/fh/files/misc/smartbiddingbestpractices1s.pdf)). After raising a budget on a target-based campaign, wait one to two conversion cycles ([Google Ads Help](https://support.google.com/google-ads/answer/17061251)).

## Google Ads API (v26, October 2026)

- Performance Max has no ad groups or ads; queries against `ad_group` or `ad_group_ad` return nothing for it. Use the resources Google lists for it ([Google Ads API](https://developers.google.com/google-ads/api/performance-max/reporting)).
- Performance Max search terms: `campaign_search_term_view`, which Google encourages in place of `search_term_view` for campaign-level search terms ([PPC Land on v21](https://ppc.land/google-ads-api-v21-introduces-ai-max-and-campaign-transparency-tools/)).
- Match source segment values: `ADVERTISER_PROVIDED_KEYWORD`, `AI_MAX_KEYWORDLESS`, `AI_MAX_BROAD_MATCH`, `DYNAMIC_SEARCH_ADS`, `PERFORMANCE_MAX`, `VERTICAL_ADS_DATA_FEED` (added v23) ([Google Ads API diff](https://developers.google.com/google-ads/api/diff-tool/v23/versus-v22/diffs/full/enums/search_term_match_source)).
- Network values: `SEARCH`, `SEARCH_PARTNERS`, `CONTENT` (Display), `YOUTUBE`, `GOOGLE_TV`, `GMAIL`, `DISCOVER`, `MAPS`, `MIXED` (cross-network), and `GOOGLE_OWNED_CHANNELS` for historical Demand Gen data only.
- Don't add `ai_max_search_term_ad_combination_view` to `search_term_view`: their traffic overlaps and the sum double counts. Terms below Google's privacy thresholds are missing from both ([Google Ads API](https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/ai-max-reporting)).
