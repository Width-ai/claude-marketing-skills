Query notes adapted in part from google-ads-recommendations-reviewer in [Insightful-Pipe/google-ads-skills](https://github.com/Insightful-Pipe/google-ads-skills) (MIT, Copyright (c) 2026 InsightfulPipe), and the GAQL query pack in the google-ads-data-pull skill.

# Getting the data

Pull everything for the same window: the last 30 complete days unless the person asks otherwise, ending yesterday in the account's time zone. Save raw results to `google-ads-data/<end-date>/` and normalize them before use.

## What the Google Ads API offers (checked November 2026, API v26)

These facts come from Google's API reference and guides. Field names change with each API version, roughly every quarter. Before an unfamiliar query, check fields with the connector's metadata tool (`get_resource_metadata` on Google's official server). An `UNRECOGNIZED_FIELD` error means the query needs fixing, not that there's no data.

**The `recommendation` resource.** No metrics. Selectable and filterable: `recommendation.resource_name`, `recommendation.type`, `recommendation.campaign`, `recommendation.campaigns` (repeated), `recommendation.ad_group`, `recommendation.campaign_budget`, `recommendation.dismissed`. Selectable message fields: `recommendation.impact` and one details field per type, named after the type, such as `recommendation.campaign_budget_recommendation` or `recommendation.keyword_recommendation`. Only the details field matching a row's type comes back filled.

- Select whole detail objects. Insightful-Pipe reports that sub-fields such as `recommendation.campaign_budget_recommendation.current_budget_amount_micros` are refused.
- The resource also returns dismissed recommendations, so filter with `recommendation.dismissed = FALSE`.
- `recommendation.impact` holds `base_metrics` and `potential_metrics`, each with `impressions`, `clicks`, `cost_micros`, `conversions`, `conversions_value`, and `video_views`. Google fills it only for some types, and which metrics come back varies by type and campaign type. The API reference doesn't state the period; the interface shows weekly estimates. `triage.py` uses only the difference between them, which doesn't depend on the period.
- Details used by the triage: budget types carry `current_budget_amount_micros` and `recommended_budget_amount_micros`; target adjustments carry `target_adjustment.current_average_target_micros` and `recommended_target_multiplier` (the "bid too low" type uses `average_target_cpa_micros`); opt-ins carry `recommended_target_cpa_micros` or `recommended_target_roas`; `keyword_recommendation` carries `keyword` and `search_terms`; `use_broad_match_keyword_recommendation` carries a keyword sample, `suggested_keywords_count`, `campaign_uses_shared_budget`, and `required_campaign_budget_amount_micros`; `move_unused_budget_recommendation` carries `excess_campaign_budget` and `budget_recommendation`.
- The v26 `recommendation.type` enum has no type for AI Max, removing redundant or non-serving keywords, removing conflicting negatives, optimized targeting, enhanced conversions setup, or Smart Bidding Exploration. Those appear only in the interface. Get them from an export.

**Optimization score.** `customer.optimization_score` and `customer.optimization_score_weight` on `customer`; `campaign.optimization_score` on `campaign`. Scores are fractions from 0 to 1. To combine accounts, weight each score by its `optimization_score_weight`. `metrics.optimization_score_uplift` segmented by `segments.recommendation_type` shows which types carry the score.

**Auto-apply.** The `recommendation_subscription` resource has `type`, `status` (`ENABLED` or `PAUSED`), `create_date_time`, and `modify_date_time`. Only some types can be subscribed through the API. Google's auto-apply help page lists interface types the API can't show, such as removing redundant, non-serving, or conflicting keywords, targeting expansion, and audiences. So always ask the person to check the interface too.

**What recommendations changed.** In `change_event`, `client_type` = `GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` means auto-apply made the change, and `GOOGLE_ADS_RECOMMENDATIONS` means someone applied a recommendation. History reaches back at most 30 days.

**Applying and dismissing.** The API's `RecommendationService` can apply and dismiss recommendations, and some connectors expose that as a tool. This skill never calls it, or any connector tool that applies, dismisses, or changes auto-apply. Google's official Google Ads MCP server (v0.0.6) reads all of the queries below with its `search` tool; it can't apply or dismiss recommendations or change budgets, bids, keywords, or settings.

## Queries for a connector

Run these through any tool that accepts GAQL (`search` on Google's official server, with `customer_id` and `query`). Use explicit dates for `<START>` and `<END>`. Customer IDs go without hyphens. Query client accounts, not manager accounts.

**1. Open recommendations.** Add the details field for any other type you meet, named the same way. If one is refused, drop it and read that recommendation's suggestion from the card.

```sql
SELECT recommendation.resource_name, recommendation.type, recommendation.campaign,
       recommendation.ad_group, recommendation.campaign_budget, recommendation.dismissed,
       recommendation.impact,
       recommendation.campaign_budget_recommendation,
       recommendation.forecasting_campaign_budget_recommendation,
       recommendation.marginal_roi_campaign_budget_recommendation,
       recommendation.raise_budget_performance_too_low_recommendation,
       recommendation.move_unused_budget_recommendation,
       recommendation.raise_target_cpa_recommendation,
       recommendation.raise_target_cpa_bid_too_low_recommendation,
       recommendation.lower_target_roas_recommendation,
       recommendation.set_target_cpa_recommendation,
       recommendation.set_target_roas_recommendation,
       recommendation.forecasting_set_target_cpa_recommendation,
       recommendation.forecasting_set_target_roas_recommendation,
       recommendation.target_cpa_opt_in_recommendation,
       recommendation.target_roas_opt_in_recommendation,
       recommendation.keyword_recommendation,
       recommendation.use_broad_match_keyword_recommendation
FROM recommendation
WHERE recommendation.dismissed = FALSE
```

**2. Campaign numbers and settings for the window.** Campaigns on a portfolio bid strategy keep their target on the `bidding_strategy` resource instead.

```sql
SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
       campaign.bidding_strategy_type, campaign.primary_status, campaign.primary_status_reasons,
       campaign.target_cpa.target_cpa_micros, campaign.maximize_conversions.target_cpa_micros,
       campaign.target_roas.target_roas, campaign.maximize_conversion_value.target_roas,
       campaign.network_settings.target_search_network,
       campaign.network_settings.target_content_network,
       campaign.campaign_budget, campaign_budget.amount_micros, campaign_budget.explicitly_shared,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.status = 'ENABLED'
```

**3. Impression share (Search campaigns).**

```sql
SELECT campaign.id, campaign.name, metrics.search_impression_share,
       metrics.search_budget_lost_impression_share,
       metrics.search_rank_lost_impression_share
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.advertising_channel_type = 'SEARCH'
  AND campaign.status = 'ENABLED'
```

**4. Optimization score.**

```sql
SELECT customer.id, customer.descriptive_name, customer.optimization_score,
       customer.optimization_score_weight
FROM customer
```

```sql
SELECT campaign.id, campaign.name, campaign.optimization_score
FROM campaign
WHERE campaign.status = 'ENABLED'
```

**5. Auto-apply settings.**

```sql
SELECT recommendation_subscription.type, recommendation_subscription.status,
       recommendation_subscription.create_date_time, recommendation_subscription.modify_date_time
FROM recommendation_subscription
```

A type of `UNKNOWN` is one this API version can't name. Report it and point the person to the interface.

**6. Changes made by recommendations.** At most 30 days back: pad the start by a day. `LIMIT` is required.

```sql
SELECT change_event.change_date_time, change_event.client_type,
       change_event.change_resource_type, change_event.resource_change_operation,
       change_event.changed_fields, change_event.campaign
FROM change_event
WHERE change_event.change_date_time >= '<29_DAYS_AGO> 00:00:00'
  AND change_event.change_date_time <= '<TOMORROW> 00:00:00'
  AND change_event.client_type IN ('GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION', 'GOOGLE_ADS_RECOMMENDATIONS')
ORDER BY change_event.change_date_time DESC
LIMIT 10000
```

**7. Keywords, only when there are keyword recommendations.** Positives with IDs (the IDs fill in ad group names) and performance:

```sql
SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
       ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
       ad_group_criterion.status, metrics.impressions, metrics.clicks,
       metrics.cost_micros, metrics.conversions
FROM keyword_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND ad_group_criterion.negative = FALSE
  AND ad_group_criterion.status != 'REMOVED'
```

Negatives, from campaigns and ad groups:

```sql
SELECT campaign.name, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type,
       campaign_criterion.negative
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD' AND campaign_criterion.negative = TRUE
```

```sql
SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = TRUE
  AND ad_group_criterion.status != 'REMOVED'
```

Negative keyword lists aren't checked by `triage.py`. If the account relies on them, check suggested keywords against the lists by hand.

**8. Ads, only when there are ad recommendations.**

```sql
SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.type,
       ad_group_ad.status, ad_group_ad.ad_strength
FROM ad_group_ad
WHERE ad_group_ad.status != 'REMOVED'
  AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
```

## Normalizing

Run every raw result through `scripts/normalize.py`, then the recommendations through `scripts/prepare_recommendations.py`:

```bash
python3 scripts/normalize.py google-ads-data/2026-11-14/campaigns_raw.json --out google-ads-data/2026-11-14/campaigns.csv
python3 scripts/normalize.py google-ads-data/2026-11-14/impression_share_raw.json --out google-ads-data/2026-11-14/impression_share.csv
python3 scripts/prepare_recommendations.py google-ads-data/2026-11-14/recommendations_raw.json \
  --out google-ads-data/2026-11-14/recommendations.csv \
  --lookup google-ads-data/2026-11-14/campaigns.csv google-ads-data/2026-11-14/keywords.csv
```

`--lookup` fills campaign and ad group names from IDs. `prepare_recommendations.py` drops dismissed recommendations unless you pass `--keep-dismissed`, and prints a count by type and how many carry Google's estimate.

## Without a connector

Ask for these, all for the same 30 days. Google moves menu items now and then; if a path doesn't match, tell the person to type the page name into the search bar at the top of Google Ads.

1. **The Recommendations page.** Campaigns, Recommendations. Switch to the table view (top right) and download it as CSV. For each recommendation that changes a budget, target, or keywords, open the card (View) and note what it suggests: the current and suggested amounts, the keywords, and Google's estimate if the card shows one. Screenshots of the cards work too.
2. **A campaign report for the same 30 days.** Campaigns page, with Campaign type, Bid strategy type, Budget, Impr., Clicks, Cost, Conversions, Conv. value, Search lost IS (budget), and Search impr. share. If google-ads-data-pull is installed, its exports guide has the details.
3. **The auto-apply list.** Recommendations, Auto-apply settings, Manage tab: which types are checked. Typing them as two columns, `name` and `status` (on or off), is fine.
4. **Change history,** if the person wants to know what recommendations already changed: Change history, last 30 days, with the Tool column. Normalize it; `triage.py` reads a `tool` column whose text mentions auto-apply or recommendations.
5. **Keywords and negative keywords,** only when there are keyword recommendations.

When the download doesn't carry the details, type one row per recommendation into a CSV with any of these columns (the names `prepare_recommendations.py` understands):

| Column | What goes in it |
|---|---|
| `Recommendation` | The card's title, as Google writes it, such as "Raise your budgets" |
| `Campaign`, `Ad group` | Exact names |
| `Current budget`, `Recommended budget` | Daily amounts from the card |
| `Current target`, `Recommended target`, `Target type` | From target cards; `cpa` or `roas`, ROAS as a ratio (4 means 400%) |
| `Keyword`, `Match type` | For keyword cards: one row per keyword |
| `Negative keyword`, `Negative match type` | For conflicting negative cards, with the blocked keyword in `Keyword` |
| `Source campaign` | For "Move unused budgets": the campaign giving up budget |
| `Extra cost`, `Extra conversions`, `Extra conversion value` | Google's estimate as the card shows it, such as "+$340" and "+4.8" |
| `Optimization score uplift` | As shown, such as "+2.2%" |
| `Notes` | Anything else, such as "from a screenshot" |

Write what the card says, exactly. Never fill a column the card doesn't show.

**Suggestions from Ads Advisor or Ask Advisor** (Google's chat assistant in Google Ads) go in the same CSV: put the closest recommendation title in `Recommendation` (for example "Raise your budgets"), add "(Ask Advisor suggestion)", and put the suggestion's words in `Notes`. The same rules apply.
