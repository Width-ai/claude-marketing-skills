# GAQL query pack

Adapted in part from the analysis recipes in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines) and the GAQL notes in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici).

Run these through any connector tool that accepts GAQL (Google's official Google Ads MCP server calls it `search`, with arguments `customer_id` and `query`). Replace `<START>` and `<END>` with explicit dates in `YYYY-MM-DD` form. Customer IDs go without hyphens.

Before you run them:
- Field names change between API versions, and Google ships a major version roughly every quarter. If the connector has a metadata tool (`get_resource_metadata` on the official server), check unfamiliar fields first. On `UNRECOGNIZED_FIELD`, look the field up; don't drop the dataset silently.
- Adding a segment (date, device, network) changes the row grain. Campaign plus date rows are not campaign totals; normalize with `--group-by` or sum in code.
- Money fields ending in `_micros` are divided by 1,000,000 by `normalize.py`. Impression share can come back as a decimal or as a string such as `"< 0.10"`; the normalizer keeps the number and flags the bound.

## Accounts

**Which accounts this login can reach.** Use the connector's list-accounts tool (`list_accessible_customers` on the official server), then list client accounts under a manager:

```sql
SELECT customer_client.id, customer_client.descriptive_name, customer_client.status,
       customer_client.manager, customer_client.currency_code, customer_client.time_zone
FROM customer_client
WHERE customer_client.status = 'ENABLED' AND customer_client.manager = FALSE
```

Query performance only on enabled client accounts, not manager accounts.

**Account basics** (currency, time zone, auto-tagging):

```sql
SELECT customer.id, customer.descriptive_name, customer.currency_code,
       customer.time_zone, customer.auto_tagging_enabled
FROM customer
```

## Campaigns

**Campaign inventory.** Answers: what's running, what's in learning, which "duplicates" are experiment arms.

```sql
SELECT campaign.id, campaign.name, campaign.status, campaign.serving_status,
       campaign.primary_status, campaign.primary_status_reasons,
       campaign.experiment_type, campaign.advertising_channel_type,
       campaign.bidding_strategy_type, campaign_budget.amount_micros,
       campaign_budget.explicitly_shared
FROM campaign
WHERE campaign.status != 'REMOVED'
```

**Campaign settings.** Answers: are Search campaigns leaking into Display or search partners, and is location targeting set to presence.

```sql
SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
       campaign.network_settings.target_google_search,
       campaign.network_settings.target_search_network,
       campaign.network_settings.target_content_network,
       campaign.geo_target_type_setting.positive_geo_target_type
FROM campaign
WHERE campaign.status = 'ENABLED'
```

**Campaign performance for a window.** Answers: spend, traffic, and results by campaign. Add `segments.date` to the SELECT for daily rows (needed for `metrics.py compare` in one-file mode).

```sql
SELECT campaign.id, campaign.name, campaign.status, metrics.impressions,
       metrics.clicks, metrics.cost_micros, metrics.conversions,
       metrics.conversions_value, metrics.all_conversions
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.status != 'REMOVED'
```

For device or network splits, add `segments.device` or `segments.ad_network_type` to the SELECT.

**Monthly history since launch.** Answers: how long a campaign has run, and whether recent CPA differs from its long-run CPA. Only months with activity come back, so the first row is the first month with spend. Run this before quoting any CPA.

```sql
SELECT campaign.name, segments.month, metrics.impressions, metrics.clicks,
       metrics.cost_micros, metrics.conversions, metrics.conversions_value
FROM campaign
WHERE campaign.id = <ID>
  AND segments.date BETWEEN '<EARLY_DATE>' AND '<END>'
```

**Impression share.** Answers: are we losing visibility to budget or to rank.

```sql
SELECT campaign.id, campaign.name, metrics.search_impression_share,
       metrics.search_budget_lost_impression_share,
       metrics.search_rank_lost_impression_share,
       metrics.search_top_impression_share
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.advertising_channel_type = 'SEARCH'
```

High budget-lost share means budget is the limit. High rank-lost share means bids or quality are.

## Conversions

**Conversions by action.** Answers: what "conversions" is actually made of. `metrics.cost_micros` can't be selected with `segments.conversion_action_name`, so pull cost separately with the campaign query.

```sql
SELECT campaign.name, segments.conversion_action_name,
       segments.conversion_action_category, metrics.conversions,
       metrics.conversions_value, metrics.all_conversions
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND metrics.all_conversions > 0
```

**Conversion action settings.** Answers: which actions drive bidding, how they count, and their lookback windows.

```sql
SELECT conversion_action.id, conversion_action.name, conversion_action.status,
       conversion_action.category, conversion_action.type,
       conversion_action.primary_for_goal, conversion_action.counting_type,
       conversion_action.click_through_lookback_window_days
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
```

## Ad groups and keywords

**Ad group performance.**

```sql
SELECT campaign.name, ad_group.id, ad_group.name, ad_group.status,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM ad_group
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND ad_group.status != 'REMOVED'
```

**Positive keywords with performance and Quality Score.** `keyword_view` also returns negatives; this query filters them out. Without `segments.date` in the SELECT there's one row per keyword for the whole window, so no deduplication is needed.

```sql
SELECT campaign.name, ad_group.name, ad_group_criterion.criterion_id,
       ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
       ad_group_criterion.status, ad_group_criterion.cpc_bid_micros,
       ad_group_criterion.quality_info.quality_score,
       ad_group_criterion.quality_info.creative_quality_score,
       ad_group_criterion.quality_info.post_click_quality_score,
       ad_group_criterion.quality_info.search_predicted_ctr,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM keyword_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND ad_group_criterion.negative = FALSE
  AND ad_group_criterion.status != 'REMOVED'
```

If you do add `segments.date`, collapse the daily rows with `normalize.py --group-by campaign,ad_group,keyword,match_type`.

## Negative keywords

Negatives live in four places. Pull all that apply and keep them in a separate inventory from positives. Never count a negative as a positive keyword.

**Ad group negatives.**

```sql
SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = TRUE
  AND ad_group_criterion.status != 'REMOVED'
```

**Campaign negatives.**

```sql
SELECT campaign.name, campaign_criterion.keyword.text,
       campaign_criterion.keyword.match_type, campaign_criterion.negative
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD'
  AND campaign_criterion.negative = TRUE
```

**Negative keyword lists and their keywords.**

```sql
SELECT shared_set.id, shared_set.name, shared_criterion.keyword.text,
       shared_criterion.keyword.match_type
FROM shared_criterion
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
  AND shared_set.status = 'ENABLED'
```

**Which campaigns each list is attached to.** A list that isn't attached blocks nothing.

```sql
SELECT campaign.name, shared_set.name, campaign_shared_set.status
FROM campaign_shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
  AND campaign_shared_set.status = 'ENABLED'
```

Account-level negative keywords, where an account uses them, are stored apart from the three above. Look them up with the metadata tool before concluding there are none.

## Search terms

**Search terms, unfiltered.** Answers: what queries the ads actually showed for. Don't filter on clicks (that hides impression-only terms), and raise the limit until disclosed clicks stop growing.

```sql
SELECT search_term_view.search_term, search_term_view.status,
       segments.search_term_match_type, campaign.id, campaign.name, ad_group.name,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM search_term_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
ORDER BY metrics.impressions DESC
LIMIT 10000
```

Then run `metrics.py coverage` against the campaign query for the same window to get the share of clicks the report discloses. Performance Max search terms come from different reports; check the connector's metadata tool for the current resource.

## Ads and landing pages

**Ads with their text and destinations.** Answers: which ads serve, where they send people, ad strength, and approval.

```sql
SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.type,
       ad_group_ad.status, ad_group_ad.ad_strength,
       ad_group_ad.policy_summary.approval_status, ad_group_ad.ad.final_urls,
       ad_group_ad.ad.responsive_search_ad.headlines,
       ad_group_ad.ad.responsive_search_ad.descriptions,
       ad_group_ad.ad.responsive_search_ad.path1,
       ad_group_ad.ad.responsive_search_ad.path2,
       metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
FROM ad_group_ad
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND ad_group_ad.status != 'REMOVED'
```

**Landing pages.** Answers: which pages get the traffic and how each converts.

```sql
SELECT landing_page_view.unexpanded_final_url, metrics.clicks,
       metrics.cost_micros, metrics.conversions
FROM landing_page_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
ORDER BY metrics.clicks DESC
```

## Change history

**Who changed what.** At most 30 days back (pad the start by a day to avoid `START_DATE_TOO_OLD`), `LIMIT` is required and capped at 10,000, and no `metrics` fields are allowed. Google Ads Editor changes don't appear here.

```sql
SELECT change_event.change_date_time, change_event.change_resource_type,
       change_event.change_resource_name, change_event.resource_change_operation,
       change_event.client_type, change_event.user_email,
       change_event.changed_fields, change_event.campaign
FROM change_event
WHERE change_event.change_date_time >= '<29_DAYS_AGO> 00:00:00'
  AND change_event.change_date_time <= '<TOMORROW> 00:00:00'
ORDER BY change_event.change_date_time DESC
LIMIT 10000
```

## Common errors

| Error | Fix |
|---|---|
| `UNRECOGNIZED_FIELD` | The field was renamed or isn't selectable with this resource. Check the metadata tool. |
| `INVALID_VALUE_WITH_DURING_OPERATOR` | Only some `DURING` literals exist. Use `BETWEEN` with explicit dates. |
| `PROHIBITED_SEGMENT_WITH_METRIC_IN_SELECT_OR_WHERE_CLAUSE` | That segment can't be combined with that metric (for example conversion action with cost). Split the query. |
| `START_DATE_TOO_OLD` on change history | The 30-day limit is strict. Start a day later. |
| Cost a million times too big | The value is in micros and wasn't divided. Run it through `normalize.py`. |
