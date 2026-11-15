Adapted in part from google-ads-recommendations-reviewer in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe), the recommendation boundary in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici), and "Account Audits, Scoring & Recommendation Guardrails" in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines).

# Recommendation rule table

`scripts/triage.py` applies these rules. Read this file to explain a verdict, to judge a recommendation the script put on hold, or to change a rule. If you change a rule here, change the script to match.

## How to think about Google's recommendations

- **They are suggestions, not a health check.** Google writes them, and Google is paid by the click. Many of them mainly raise spend: budgets, looser targets, broad match, AI Max, new networks and audiences, Performance Max. Not adopting one is never a failure.
- **The account's own numbers decide.** Google's estimate of extra clicks or conversions is shown for reference and used for one calculation (the cost of the extra conversions, below). It is never the reason to accept.
- **Every verdict names its evidence.** The reason says which numbers decided it, against which target, over which window. A verdict that can't name its numbers is a hold.
- **Missing means MISSING.** If the target, break-even, or campaign data is missing, the verdict is hold, with what's needed. The script never fills a gap with a benchmark.

## The inputs every rule uses

| Input | Where it comes from | How it's used |
|---|---|---|
| Target and break-even CPA or ROAS | Context file, "Economics" | "At or under target" is good. Past break-even loses money. If break-even is MISSING, the target is used as the limit, and the reason says so. If both are MISSING, anything that raises spend is held. |
| Primary conversions and known problems | Context file, "Conversions" | A known problem on a primary conversion (spam, double counting, refunds not subtracted) holds anything that leans on conversion data: bidding switches, targets, broad match, AI Max, Performance Max. The longest "typical delay" among primary actions is the conversion delay. |
| Limits per batch | Context file, "Permissions and limits" | Accepted budget and target changes are capped at the max change per batch (defaults 20% and 15%). The reason says when Google's suggestion was bigger. |
| Terms | Context file, "Protected terms" and "Terms we don't want" | Suggested keywords containing an unwanted term are rejected. Conflicting negatives that block a protected term are removed. |
| Offers, prices, disclaimers, restricted category | Context file, "Business and offer" | Copy and asset items are held when there's nothing approved to write from. Google-written content and URL expansion are rejected when there are required disclaimers or a restricted category. |
| Campaign numbers for the window | Connector or exports, normalized | Cost, clicks, conversions, conversion value, budget, bid strategy, budget-lost impression share, primary status. |

### Efficiency of a campaign

`triage.py` computes CPA (cost / conversions) or ROAS (value / cost) from summed numbers and labels it:

- **good:** at or under target CPA (at or over target ROAS)
- **between:** past target but within break-even
- **above break-even:** losing money on average
- **zero, losing:** no conversions, and the clicks are enough to rule out converting at break-even (95% confidence, the same math as the data pull skill's `metrics.py zero-conv`)
- **zero, unclear:** no conversions, too few clicks to judge

It also computes a 95% range for the CPA or ROAS from the conversion rate. When even the pessimistic end of a good campaign's range is within break-even, the result is solid; when it isn't, an accepted budget step says volume is low and must be reviewed on time.

### Budget-limited

A campaign is budget-limited when any of these holds:

- it lost 10% or more of search impression share to budget (`--budget-lost-threshold`, default 0.10, adapted from Insightful-Pipe's reviewer)
- Google's primary status reasons include `BUDGET_CONSTRAINED`
- it spent 90% or more of its daily budget on average over the window (`--budget-use-threshold`, default 0.90)

It's "not limited" when the data shows none of these, and "unknown" when there's no impression share or budget data.

### Cost of the extra conversions

When a recommendation carries Google's estimate (`impact.base_metrics` and `impact.potential_metrics`), the script works out:

- CPA accounts: extra cost divided by extra conversions, the price of each conversion the change would add
- ROAS accounts: extra conversion value divided by extra cost

This is the number that matters for a budget raise, not the average. If Google's own estimate puts the extra conversions past break-even, the extra spend loses money even when the average looks fine. If the estimate adds cost and no conversions, the reason says so.

### One change at a time

Per campaign, only one budget, bidding, matching, or reach change goes first. Accepts go before tests, then budget, then bidding, then matching (broad match, AI Max), then reach (networks, audiences, URL expansion). Each later item gets a "start after" date: the review date or experiment end of the one before it. Google runs only one experiment at a time on a campaign, and two changes inside one window can't be judged apart.

### Learning

A campaign whose primary status reasons include `BIDDING_STRATEGY_LEARNING` gets a hold on budget, bidding, matching, and reach items until learning ends.

## The table

"Raises spend" says whether the type's main effect is more spend. "Default" is the verdict before the account's numbers are checked; "depends" means the numbers decide.

| Kind | API types (v26) | Interface names | Raises spend | Default | What decides it | Accepted through |
|---|---|---|---|---|---|---|
| Raise budget | `CAMPAIGN_BUDGET`, `FORECASTING_CAMPAIGN_BUDGET`, `MARGINAL_ROI_CAMPAIGN_BUDGET`, `RAISE_BUDGET_PERFORMANCE_TOO_LOW` | Raise your budgets; Adjust your budgets; Raise your budgets for upcoming traffic increases | Yes | Depends, usually reject | Reject if CPA is past break-even, no conversions, not budget-limited, or Google's estimate puts the extra conversions past break-even. Reject if CPA is past target, unless the extra conversions beat target. Accept if budget-limited and good: one step, capped at the budget limit; half the suggested increase when the extra conversions cost more than target. | `set_budget` |
| Move unused budget | `MOVE_UNUSED_BUDGET` | Move unused budgets | No | Depends | Accept if the receiving campaign is good and budget-limited, and the giving campaign spends under 90% of its budget. Both moves are capped at the budget limit. | Two `set_budget` entries |
| Loosen target | `RAISE_TARGET_CPA`, `RAISE_TARGET_CPA_BID_TOO_LOW`, `RAISE_TARGET_CPA_PERFORMANCE_BID_TOO_LOW`, `LOWER_TARGET_ROAS`, `LOWER_TARGET_ROAS_PERFORMANCE_BID_TOO_LOW` | Adjust your CPA targets; Adjust your ROAS targets; Fix low CPA targets | Yes | Depends | New target = current target times Google's multiplier. Reject if past break-even. Test if past your target but within break-even. Accept if within your target, capped at the target limit. | `set_target` |
| Set a target | `SET_TARGET_CPA`, `SET_TARGET_ROAS`, `FORECASTING_SET_TARGET_CPA`, `FORECASTING_SET_TARGET_ROAS` | Set a target CPA; Set a target ROAS; Set a bidding strategy target | Maybe | Depends | Reject if past break-even, or (ROAS) under about 15 conversions per 30 days. Test if past your target, or tighter than the campaign's actual CPA or ROAS (it could cut volume). Otherwise accept. | `set_target` when the campaign already has a target; interface steps when it doesn't |
| Switch to conversion bidding | `TARGET_CPA_OPT_IN`, `MAXIMIZE_CONVERSIONS_OPT_IN`, `TARGET_ROAS_OPT_IN`, `MAXIMIZE_CONVERSION_VALUE_OPT_IN` | Bid more efficiently with Target CPA, Maximize conversions, Target ROAS, Maximize conversion value | Yes | Test | Reject if it already bids on conversions, has no conversions, has no conversion values (value types), has under about 15 conversions per 30 days (value types), or Google's suggested target is past break-even. Otherwise test. | Experiment |
| Clicks or visibility bidding | `MAXIMIZE_CLICKS_OPT_IN` | Bid more efficiently with Maximize clicks; Bid more efficiently with Target impression share | Yes | Reject | Maximize clicks: reject when the account tracks conversions. Target impression share: reject for non-brand, hold (your call) for brand. | Interface |
| Smart Bidding Exploration | none found in the API | Turn on Smart Bidding Exploration | Yes | Depends | Reject unless the campaign is good. Then test. | Experiment |
| Broad match | `USE_BROAD_MATCH_KEYWORD`, `KEYWORD_MATCH_TYPE` (deprecated) | Add broad match keywords | Yes | Test at most | Reject without conversion-based Smart Bidding, if past target, with no conversions, or if budget-limited. Otherwise test. The reason adds Google's own "required budget" when it's higher than today's. Never accepted outright. | Experiment |
| AI Max | none found in the API | Turn on AI Max; Turn on AI Max for Search campaigns | Yes | Test at most | Reject without conversion-based Smart Bidding, if past target, with no conversions, or if budget-limited. Otherwise test with an AI Max experiment (a custom experiment when the budget is shared, which Google's AI Max flow excludes). | Experiment |
| Add keywords | `KEYWORD` | Add new keywords | Yes | Depends | Needs the keyword list and Economics. Reject if it contains a term you don't want, is already in the campaign, is blocked by an in-scope negative, or the campaign is losing money. Accept otherwise, created paused; broad suggestions become phrase. You confirm relevance before enabling. | `add_keyword` (paused) |
| Remove redundant or non-serving keywords | none found in the API | Remove redundant keywords; Remove non-serving keywords | No | Depends | Needs keyword performance. Reject if it converted or served impressions in the window. Accept as a pause (never a delete) if it had 0 impressions. | `set_status` to paused |
| Remove conflicting negatives | none found in the API | Remove conflicting negative keywords | Maybe | Reject | Reject (keep the negative) by default, and always when the negative matches a term you don't want. Accept only when the blocked keyword contains a protected term. | `remove_negative` when the negative is in the pull |
| Networks | `SEARCH_PARTNERS_OPT_IN`, `DISPLAY_EXPANSION_OPT_IN` | Expand your reach with Google search partners; Use Display Expansion; Expand your reach with Google video partners | Yes | Reject | Reject if budget-limited or not good. Otherwise test on that one campaign and read it by network segment. | Network test |
| Audience expansion | `CUSTOM_AUDIENCE_OPT_IN` | Use optimized targeting; Use targeting expansion; Reach new audiences; Create a custom audience; Add audiences | Yes | Reject | Reject if budget-limited or not good. Otherwise test. | Experiment |
| Final URL expansion | `PERFORMANCE_MAX_FINAL_URL_OPT_IN` | (Performance Max settings) | Yes | Depends | Reject with a restricted category or required disclaimers, or if not good. Otherwise test with URL exclusions set. | Performance Max optimization experiment |
| Performance Max | `PERFORMANCE_MAX_OPT_IN`, `UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX`, `SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX`, `MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX` | Create a Performance Max campaign; Target more products with Performance Max campaigns | Yes | Test at most | Judged on the whole account. Reject if the account is past break-even or has no conversions. Otherwise test with an uplift or upgrade experiment. DSA moves note that Google moves DSA into AI Max from February 2027. | Experiment |
| New customers | `OPTIMIZE_FOR_NEW_CUSTOMERS` (v26.1) | Optimize for new customers | Maybe | Hold | Needs a value for a new customer that the context file doesn't hold. Then test. | Experiment |
| More Shopping products | `SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN`, `SHOPPING_TARGET_ALL_OFFERS` | Target all eligible Shopping products | Yes | Hold | Reject if the campaign is losing money. Otherwise hold: which products, and are they worth selling at break-even? | Interface |
| Ads and Ad Strength | `RESPONSIVE_SEARCH_AD`, `RESPONSIVE_SEARCH_AD_ASSET`, `RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH`, `IMPROVE_PERFORMANCE_MAX_AD_STRENGTH`, `IMPROVE_DEMAND_GEN_AD_STRENGTH` | Improve your responsive search ads; Add responsive search ads; Add assets to your responsive search ads; Improve your Performance Max asset groups; Improve your Demand Gen | No | Accept | Reject a new RSA when the ad group already has 2 enabled RSAs rated Good or Excellent (Google's recommendation). Hold when there are no approved offers or proof to write from. Never use Google's suggested text unchecked. Ad Strength is a guide, not a result. | `add_rsa` once the copy is written, or interface |
| Assets | `SITELINK_ASSET`, `CALLOUT_ASSET`, `CALL_ASSET`, `LEAD_FORM_ASSET` | Add sitelink, callout, call, image, structured snippet, price, location, lead form assets; add videos | No | Accept | Hold lead forms (can your team follow up?), price assets without approved prices, and text assets without approved offers or proof. Call assets get your hours as their schedule. | Interface, or a connector that creates assets |
| Google-generated assets | `DYNAMIC_IMAGE_EXTENSION_OPT_IN` | Add dynamic image assets; Add dynamic sitelink assets; Enable text customization | No | Depends | Reject with a restricted category or required disclaimers. Text customization is tested inside an AI Max experiment. Dynamic images and sitelinks are accepted with a monthly review. | Interface |
| Measurement | `IMPROVE_GOOGLE_TAG_COVERAGE` | Set up conversion tracking; Fix your conversion tracking; Set up enhanced conversions; Upgrade your conversion tracking; Turn on auto-tagging; data-driven attribution; conversion value; conversion rate drop | No | Accept | The person makes these, never an agent. Hold enhanced conversions in a restricted category until legal and consent are checked. Hold store visits and app items unless they apply. Data-driven attribution shifts conversion counts: log the date. | Interface |
| Audience lists and reporting | `REFRESH_CUSTOMER_MATCH_LIST` | Refresh or upload Customer Match lists; Set up audience sources; Add audience segments for reporting | No | Accept | Observation mode only; uploads follow Google's customer data terms. | Interface |
| Ad rotation | `OPTIMIZE_AD_ROTATION` | Use optimized ad rotation | No | Accept | Skip only during a manual ad test with even rotation. | Interface |
| Shopping feed fixes | `SHOPPING_ADD_AGE_GROUP`, `SHOPPING_ADD_COLOR`, `SHOPPING_ADD_GENDER`, `SHOPPING_ADD_GTIN`, `SHOPPING_ADD_MORE_IDENTIFIERS`, `SHOPPING_ADD_SIZE`, `SHOPPING_FIX_DISAPPROVED_PRODUCTS`, `SHOPPING_FIX_SUSPENDED_MERCHANT_CENTER_ACCOUNT`, `SHOPPING_FIX_MERCHANT_CENTER_ACCOUNT_SUSPENSION_WARNING` | Add GTIN; Fix disapproved products; Fix or prevent Merchant Center suspension | No | Accept | Fix at the feed. | Merchant Center |
| Repairs | none | Fix your ad destinations; Fix your ad text; Fix disapproved sitelinks or assets; Add ads or keywords to each ad group; Complete advertiser verification; Fix certification issues; Fix your audience targeting | No | Accept | Fix the listed items. | Interface |
| Retired | `ENHANCED_CPC_OPT_IN`, `TEXT_AD`, `UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX` | Add dynamic search ads | No | Reject | Enhanced CPC ended for Search and Display in March 2025; expanded text ads and Smart Shopping are gone; DSA creation is going (moving to AI Max). | Dismiss |
| Anything else | `CAMPAIGN_SPECIFIC_APP_GOAL`, unknown types | Use a portfolio bid strategy with a shared budget; new names | Maybe | Hold | Judge by hand with the principles above and record the verdict as an override. | Depends |

"None found in the API" means the type wasn't in the v26 `recommendation.type` enum checked in November 2026. These come from the interface or an export.

## Experiments for test verdicts

| Setting | Value | Basis |
|---|---|---|
| Split | 50% | Fastest read; Google lets you choose |
| Settle time | 14 days | Google advises about two weeks after turning on AI Max or changing Smart Bidding before judging |
| Measure time | At least 14 days, longer until each arm expects 30 conversions (`--min-test-conversions`), at most 42 | Google's Smart Bidding guidance: judge over at least two weeks. 30 and 42 are this skill's defaults. |
| Conversion delay | Added at the end | Conversions arrive after the click |
| Success metric | The trial arm gets more conversions (or value) at a CPA at or under target (ROAS at or over target) | The business's own target |
| Guardrail | The trial arm stays within break-even | Stop early if it doesn't |

The script also reports the smallest gap between the arms that the expected volume could show clearly (95% confidence, 80% power, comparing two conversion counts). With 30 conversions per arm, only about a 2 times gap is clear. Small accounts get directional results, and the report says so.

Network tests (search partners, Display, video partners) don't split traffic: the setting goes on for one campaign and the new network's rows are compared with Google Search using the Network segment. Shopping campaigns can't run custom experiments, so changes there are staged and compared with the same number of days before.

## Changing a rule

- Thresholds are flags on `triage.py`: `--budget-lost-threshold`, `--budget-use-threshold`, `--min-test-conversions`, `--max-budget-change`, `--max-target-change`.
- A verdict for one recommendation is changed with an override row (rec_id, verdict, reason, decided_by). Claude may only move a verdict toward caution (to reject or hold) for reasons code can't check, such as a keyword that names a service the business doesn't offer. Moving a verdict toward accept needs the person's name in decided_by.
- Rule changes for everyone go in both this file and `scripts/triage.py`.
