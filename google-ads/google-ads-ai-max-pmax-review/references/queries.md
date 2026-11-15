Queries adapted from the GAQL examples in Google's [Google Ads API documentation](https://developers.google.com/google-ads/api/docs/start) (code samples Apache-2.0, Copyright Google LLC) and the keyword inventory notes in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici), checked against the v26 docs on 2026-11-15.

# Queries for the review

Run these through any connector tool that accepts GAQL (`search` on Google's official Google Ads MCP server, with `customer_id` and `query`). Replace `<START>` and `<END>` with explicit dates (`YYYY-MM-DD`); Google's examples use `DURING LAST_30_DAYS`, but explicit dates make the pull repeatable. Customer IDs go without hyphens.

Each query is marked:
- **Confirmed:** the resource and fields appear in Google's documentation as of November 2026.
- **Check with the metadata tool:** not confirmed. Before running it, check the fields with the connector's metadata tool (`get_resource_metadata` on the official server). If a field doesn't exist, drop it and mark that part of the review MISSING. Never show a failed query as zero.

Save each raw result in `google-ads-data/<END>/` under the file name given, then run it through `scripts/normalize.py`. If no connector is available, use `references/exports.md` instead.

## 1. Campaign inventory and settings: `campaigns`

**Confirmed** for `campaign.ai_max_setting.enable_ai_max` (Google's AI Max guide). The target and budget fields are long-standing campaign fields; if one errors, drop it and check with the metadata tool.

```sql
SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
       campaign.bidding_strategy_type, campaign.primary_status, campaign.primary_status_reasons,
       campaign.ai_max_setting.enable_ai_max,
       campaign.maximize_conversions.target_cpa_micros, campaign.target_cpa.target_cpa_micros,
       campaign.maximize_conversion_value.target_roas, campaign.target_roas.target_roas,
       campaign_budget.amount_micros, campaign_budget.explicitly_shared
FROM campaign
WHERE campaign.status != 'REMOVED'
  AND campaign.advertising_channel_type IN ('SEARCH', 'PERFORMANCE_MAX')
```

Include every Search campaign, not only AI Max ones: the brand campaign and exact-match campaigns are what Performance Max and AI Max overlap with. `primary_status_reasons` shows `BUDGET_CONSTRAINED` and learning states.

**Text customization and final URL expansion: check with the metadata tool.** Google documents the settings (`campaign.asset_automation_settings`, with types `TEXT_ASSET_AUTOMATION` and `FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION` and an opted-in or opted-out status) but gives no read query. Try selecting `campaign.asset_automation_settings` with `campaign.name`. If it isn't selectable, ask the person to read the AI Max and Asset optimization sections of each campaign's settings.

## 2. Spend by channel and network: `channels`

**Confirmed** (Google's Performance Max campaign reporting guide; channel values need API v23 or later and exist only from 2025-06-01).

```sql
SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
       segments.ad_network_type, segments.date,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign
WHERE campaign.advertising_channel_type IN ('PERFORMANCE_MAX', 'SEARCH')
  AND segments.date BETWEEN '<START>' AND '<END>'
```

For AI Max Search campaigns this splits Google Search from Search partners. Optional segments from Google's example: `segments.ad_using_product_data` and `segments.ad_using_video` (v22 or later). By asset group (**confirmed**, API only): `FROM asset_group` with `asset_group.name`, `segments.ad_network_type`, and the same metrics, `WHERE campaign.id = <ID>`.

## 3. Campaign totals for the window: `campaign_perf`

Same as section 2 without `segments.ad_network_type` and `segments.date`. Used for the disclosed share of search terms and for the budget check.

## 4. Performance Max search terms: `pmax_terms`

**Confirmed.** Google lists `campaign_search_term_view` as the Performance Max search terms resource. It has `search_term`, cost metrics, and the `search_term_match_source` segment.

```sql
SELECT campaign.id, campaign.name, campaign_search_term_view.search_term,
       segments.search_term_match_source,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign_search_term_view
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date BETWEEN '<START>' AND '<END>'
ORDER BY metrics.impressions DESC
LIMIT 10000
```

Raise the `LIMIT` until disclosed clicks stop growing. Don't also pull `search_term_view` for the same campaigns: one source per campaign, or the terms double count (`scripts/review.py` refuses that).

**Search term insights (categories): check with the metadata tool.** `campaign_search_term_insight` groups terms into categories (`category_label`) with clicks, impressions, and conversions but no cost. Developers report it needs a filter on one `campaign_search_term_insight.campaign_id`, and a single insight `id` to return the terms in a category. Optional; use it only to describe themes.

## 5. AI Max search terms: `aimax_terms`

**Confirmed** (Google's AI Max reporting guide). Pull every match source for the AI Max campaigns, not only AI Max matches, so keyword-matched traffic is there to compare.

```sql
SELECT campaign.id, campaign.name, ad_group.name, search_term_view.search_term,
       segments.search_term_match_source,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM search_term_view
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.date BETWEEN '<START>' AND '<END>'
ORDER BY metrics.impressions DESC
LIMIT 10000
```

`AI_MAX_KEYWORDLESS` and `AI_MAX_BROAD_MATCH` are AI Max; `ADVERTISER_PROVIDED_KEYWORD` is your keywords.

**Search term, headline, and landing page together: confirmed.** Review on its own; never add it to the query above.

```sql
SELECT campaign.id, campaign.name,
       ai_max_search_term_ad_combination_view.search_term,
       ai_max_search_term_ad_combination_view.headline,
       ai_max_search_term_ad_combination_view.landing_page,
       metrics.impressions, metrics.clicks, metrics.conversions
FROM ai_max_search_term_ad_combination_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
```

Only `segments.date` can segment it.

## 6. Keywords and search themes: `keywords`, `search_themes`

**Positive keywords, confirmed** (same fields as the google-ads-data-pull query pack):

```sql
SELECT campaign.name, campaign.status, ad_group.name,
       ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
       ad_group_criterion.status, ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = FALSE
  AND ad_group_criterion.status = 'ENABLED'
  AND campaign.status = 'ENABLED'
```

**Performance Max search themes: check with the metadata tool.** Google documents search themes as `asset_group_signal.search_theme` (a `SearchThemeInfo` with `text`) but gives no read query.

```sql
SELECT campaign.name, asset_group.name, asset_group_signal.search_theme.text
FROM asset_group_signal
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
```

## 7. Exclusions already in place: `negatives`, `brand_lists`, `url_exclusions`

**Campaign negative keywords, confirmed** (Performance Max campaigns can have them too):

```sql
SELECT campaign.name, campaign.advertising_channel_type, campaign_criterion.keyword.text,
       campaign_criterion.keyword.match_type, campaign_criterion.negative
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD'
  AND campaign_criterion.negative = TRUE
```

**Negative keyword lists attached to campaigns, confirmed:**

```sql
SELECT campaign.name, shared_set.name, shared_set.type, campaign_shared_set.status
FROM campaign_shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
  AND campaign_shared_set.status = 'ENABLED'
```

**Brand lists attached to campaigns, confirmed** (query given by the Google Ads API team; brand exclusions are `brand_list` criteria with `negative = TRUE` per the AI Max guide):

```sql
SELECT campaign.name, campaign.advertising_channel_type, campaign_criterion.type,
       campaign_criterion.negative, campaign_criterion.brand_list.shared_set
FROM campaign_criterion
WHERE campaign_criterion.type = 'BRAND_LIST'
```

No rows for a Performance Max or AI Max campaign means no brand list is attached. Google's Performance Max criteria guide also lists single `BRAND` criteria (exclusion only); check with the metadata tool for their fields if the account uses them.

**Brands in each brand list: check with the metadata tool.** `shared_criterion.brand.display_name` appears in the field reference; shared sets of brands have type `BRANDS`.

```sql
SELECT shared_set.id, shared_set.name, shared_criterion.brand.display_name
FROM shared_criterion
WHERE shared_set.type = 'BRANDS'
```

**URL exclusions: check with the metadata tool.** They are campaign `WEBPAGE` criteria with `negative = TRUE`. Try `SELECT campaign.name, campaign_criterion.negative, campaign_criterion.webpage.conditions FROM campaign_criterion WHERE campaign_criterion.type = 'WEBPAGE'`. If it fails, ask the person to read the exclusions in campaign settings.

**Placement exclusions: check in the Google Ads interface.** Google said in January 2025 that placement exclusions made through the API don't apply to Performance Max, and account-level placement exclusions arrived in the interface in January 2026. Don't infer "no exclusions" from an empty API result.

## 8. Landing pages: `landing`, `pmax_url_assets`, `ads`, `asset_group_urls`

**AI Max expanded landing pages, confirmed** (Google's AI Max reporting guide filters on the AI Max setting). The metrics are the standard ones for landing page views.

```sql
SELECT campaign.id, campaign.name, expanded_landing_page_view.expanded_final_url,
       metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value
FROM expanded_landing_page_view
WHERE campaign.ai_max_setting.enable_ai_max = TRUE
  AND segments.date BETWEEN '<START>' AND '<END>'
```

For Performance Max, try the same query with `WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'` (**check with the metadata tool**: Google documents it for AI Max only).

**Performance Max final URL expansion assets, confirmed** for the resource and its fields (`asset`, `field_type`, `final_url`, `status`); it needs an equals filter on one channel type. The asset group field is **check with the metadata tool** (Google says Search and Shopping must use `ad_group`).

```sql
SELECT campaign.id, campaign.name, asset_group.name,
       final_url_expansion_asset_view.final_url, final_url_expansion_asset_view.field_type,
       final_url_expansion_asset_view.asset,
       metrics.impressions, metrics.clicks, metrics.conversions
FROM final_url_expansion_asset_view
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND segments.date BETWEEN '<START>' AND '<END>'
```

Each row is an asset and URL pair, and one ad shows several assets, so summing clicks by URL can count a click more than once. Use it to see which URLs and generated text were used, not to total traffic by page. `expanded_landing_page_view` cannot say which asset produced a URL.

**Your own final URLs, confirmed:** `ad_group_ad.ad.final_urls` from the ads query in google-ads-data-pull (Search), and `asset_group.final_urls` with `asset_group.name` from `asset_group` (Performance Max; long-standing field, check if it errors). `landing_page_view.unexpanded_final_url` with clicks, cost, and conversions shows traffic by the URL you set.

## 9. Performance Max placements: `placements`

**Confirmed.** Impressions are the only metric.

```sql
SELECT campaign.id, campaign.name,
       performance_max_placement_view.display_name, performance_max_placement_view.placement,
       performance_max_placement_view.placement_type, performance_max_placement_view.target_url,
       metrics.impressions
FROM performance_max_placement_view
WHERE campaign.id = <CAMPAIGN_ID>
  AND segments.date BETWEEN '<START>' AND '<END>'
```

Run once per Performance Max campaign, as Google's example does. Placement types for Performance Max are `WEBSITE`, `MOBILE_APPLICATION`, and `YOUTUBE_VIDEO`.

## 10. Asset groups and assets: `asset_groups`, `asset_group_assets`, `campaign_assets`

**Confirmed** (Google's asset group and asset reporting guides):

```sql
SELECT campaign.name, asset_group.id, asset_group.name, asset_group.status,
       asset_group.primary_status, asset_group.ad_strength
FROM asset_group
WHERE asset_group.status = 'ENABLED'
  AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
```

```sql
SELECT campaign.name, asset_group.name, asset_group_asset.field_type,
       asset_group_asset.status, asset.type, asset.text_asset.text
FROM asset_group_asset
WHERE asset_group_asset.status != 'REMOVED'
  AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
```

Google's guide adds `asset_group_asset.primary_status`, `primary_status_reasons`, and full metrics (impressions, clicks, cost, conversions) at asset level. **Check with the metadata tool:** `asset_group_asset.source`, which would separate your assets from Google-created ones.

**Campaign-level business name and logo: check with the metadata tool.** Brand guidelines move these to the campaign. Try `SELECT campaign.name, campaign_asset.field_type, campaign_asset.status FROM campaign_asset WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'`.

## 11. Conversions: `conversions`, `conversion_actions`, `campaign_goals`

**Conversions by action, confirmed** (google-ads-data-pull query pack). Cost can't be selected with the conversion action segment.

```sql
SELECT campaign.name, segments.conversion_action_name, segments.conversion_action_category,
       metrics.conversions, metrics.conversions_value, metrics.all_conversions
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND metrics.all_conversions > 0
```

**Conversion action settings, confirmed:**

```sql
SELECT conversion_action.name, conversion_action.category, conversion_action.primary_for_goal,
       conversion_action.counting_type, conversion_action.status
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
```

**Campaign goals, confirmed resource:** `SELECT campaign.name, campaign_conversion_goal.category, campaign_conversion_goal.origin, campaign_conversion_goal.biddable FROM campaign_conversion_goal`. Shows which goal categories each campaign bids on, including campaign-specific goals that override the account default.

## 12. Recent changes: `events`

Use the change log (`.agents/google-ads-change-log.csv`) if one exists. Otherwise pull `change_event` with the query in google-ads-data-pull (30 days at most, `LIMIT` required, no metrics), and ask the person about older changes: when AI Max was turned on (or migrated in September 2026), the last target, budget, and asset changes, and when the campaign launched. Write them as `campaign,event,date` rows for `review.py timing`.
