Adapted in part from the keyword inventory notes in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici) and the search term and negative list queries in [thalesholleben/skill-google-ads](https://github.com/thalesholleben/skill-google-ads) (MIT, Copyright (c) 2026 google-ads-manager contributors).

# Getting the data

The review needs up to seven datasets for the same account. Only the search terms report is required. Each missing one turns off a check, and `review_terms.py` lists it under MISSING in the review.

| Dataset | Needed for | If missing |
|---|---|---|
| Search terms, Search and Shopping campaigns (includes AI Max) | Everything | Stop and ask for it |
| Search terms, Performance Max | Performance Max negatives | Performance Max isn't reviewed |
| Campaign totals for the same window | Disclosed share of clicks, CPC for searches with no clicks, value per conversion for ROAS | Disclosed share is MISSING |
| Positive keywords | Not blocking a live keyword; not promoting what's already a keyword | Those checks don't run |
| Negatives at every level, and which campaigns each list is attached to | Recognizing searches already blocked | Already-blocked searches look new |
| Searches that converted over a longer window (12 months or more) | Not blocking a search that converted before this window | Only this window's conversions protect searches |
| Account context | Economics, protected terms, Terms we don't want, the offer | Ask for the few facts needed |

## Pick the window

- Default to the last 90 days. Use 30 days for an account where most searches you'd act on already pass the clicks needed in 30 days.
- End the window one conversion delay before today. The delay is the "Typical delay after click" column in the context's Conversions table. Clicks inside the delay haven't had time to convert, so zero there means "not yet", not "never".
- If campaigns, keywords, match types, or bidding changed inside the window, split the window at the change date or start after it. Pooling two setups mixes two experiments.

## Through a connector (preferred)

Run these through any tool that accepts GAQL. On Google's official Google Ads MCP server that's `search`, with `customer_id` (no hyphens) and `query`. Replace `<START>` and `<END>` with explicit dates. If the google-ads-data-pull skill is installed, it can run the pulls.

Field names change between API versions (v26 as of November 2026). Before running a query for the first time, or after an `UNRECOGNIZED_FIELD` error, check fields with the connector's metadata tool (`get_resource_metadata` on the official server). A failed query is MISSING, never zero.

**1. Search terms: Search, Shopping, and AI Max.** `search_term_view` is at ad group level and has no Performance Max data. `segments.search_term_match_source` marks AI Max traffic (`AI_MAX_KEYWORDLESS`, `AI_MAX_BROAD_MATCH`) apart from `ADVERTISER_PROVIDED_KEYWORD`. If that segment errors with the others, drop it and note that AI Max traffic can't be separated. Don't filter on clicks: impression-only rows still show intent. Raise the limit until disclosed clicks stop growing.

```sql
SELECT campaign.name, campaign.advertising_channel_type, ad_group.name,
       search_term_view.search_term, search_term_view.status,
       segments.search_term_match_type, segments.search_term_match_source,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value, metrics.all_conversions
FROM search_term_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
ORDER BY metrics.impressions DESC
LIMIT 10000
```

**2. Search terms: Performance Max.** `campaign_search_term_view` is at campaign level and covers Performance Max and Search. Filter to Performance Max so Search terms aren't counted twice. Don't add keyword segments: they filter out all Performance Max rows. Search term insight categories (`campaign_search_term_insight`) are groupings, not searches people typed, so don't build negatives from them.

```sql
SELECT campaign.name, campaign.advertising_channel_type,
       campaign_search_term_view.search_term,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign_search_term_view
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.advertising_channel_type = 'PERFORMANCE_MAX'
```

**3. Campaign totals** for the same window:

```sql
SELECT campaign.name, campaign.advertising_channel_type, campaign.status,
       metrics.impressions, metrics.clicks, metrics.cost_micros,
       metrics.conversions, metrics.conversions_value
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND campaign.status != 'REMOVED'
```

**4. Positive keywords** (enabled and paused):

```sql
SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, ad_group_criterion.status,
       ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = FALSE
  AND ad_group_criterion.status != 'REMOVED'
```

**5. Negatives at every level.** Keep them apart from positives. Save each query to its own file and pass them all to `--negatives`.

```sql
SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text,
       ad_group_criterion.keyword.match_type, ad_group_criterion.negative
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = TRUE
  AND ad_group_criterion.status != 'REMOVED'
```

```sql
SELECT campaign.name, campaign_criterion.keyword.text,
       campaign_criterion.keyword.match_type, campaign_criterion.negative
FROM campaign_criterion
WHERE campaign_criterion.type = 'KEYWORD'
  AND campaign_criterion.negative = TRUE
```

```sql
SELECT shared_set.name, shared_set.type, shared_criterion.keyword.text,
       shared_criterion.keyword.match_type
FROM shared_criterion
WHERE shared_set.type IN ('NEGATIVE_KEYWORDS', 'ACCOUNT_LEVEL_NEGATIVE_KEYWORDS')
  AND shared_set.status = 'ENABLED'
```

The account-level negative list is the shared set of type `ACCOUNT_LEVEL_NEGATIVE_KEYWORDS`. If that type value errors, find the list with `SELECT customer_negative_criterion.negative_keyword_list.shared_set FROM customer_negative_criterion`, and add a `level` column set to `account` on its rows before passing them in.

**6. Which campaigns each list is attached to.** A list that isn't attached blocks nothing. Pass this file to `--list-attachments`.

```sql
SELECT campaign.name, shared_set.name, campaign_shared_set.status
FROM campaign_shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
  AND campaign_shared_set.status = 'ENABLED'
```

**7. Searches that converted over a longer window.** Use 12 months or the account's whole life, whichever is shorter. A negative that blocks a search that converted last spring would block it again. Pass the files to `--history`.

```sql
SELECT campaign.name, ad_group.name, search_term_view.search_term,
       metrics.clicks, metrics.cost_micros, metrics.conversions
FROM search_term_view
WHERE segments.date BETWEEN '<12_MONTHS_AGO>' AND '<END>'
  AND metrics.conversions > 0
```

For Performance Max, run the same over `campaign_search_term_view` with `campaign_search_term_view.search_term` and no `ad_group.name`.

## From exports (no connector)

Ask only for what's missing, all for the same dates. Google moves menu items now and then; if a path doesn't match, tell the person to type the page name into the search bar at the top of Google Ads.

| Dataset | Where | Columns to include |
|---|---|---|
| Search terms | **Insights and reports > Search terms**. Performance Max search terms are reported too since 2025; if they don't show, select the Performance Max campaign and look again. | Campaign, Ad group, Match type, Added/Excluded, Impr., Clicks, Cost, Conversions, Conv. value. Download all rows. |
| Campaign totals | **Campaigns** page | Campaign type, Impr., Clicks, Cost, Conversions, Conv. value |
| Positive keywords | **Campaigns > Keywords** (or **Audiences, keywords, and content > Search keywords**) | Match type, Status |
| Negatives | The **Negative keywords** tab on the same page | Level, Match type |
| Negative keyword lists | **Tools > Exclusion lists > Negative keywords lists**, then each list's keywords | The list's keywords, and the campaigns it's applied to |
| Converting searches, longer window | Search terms page with a 12-month date range, filtered to Conversions greater than 0 | Same as search terms |

Don't filter the search terms download for the review window. The converting-searches export is the one place where a filter is right.

Google Ads Editor exports (UTF-16, tab-separated) carry keywords and negatives at every level, including lists, and `normalize.py` reads them as they are. They don't carry search terms.

For list attachments from the interface, write a two-column CSV by hand (`campaign,shared_set`), one row per campaign a list is applied to.

## Normalize every file

```bash
python3 scripts/normalize.py google-ads-data/2026-11-07/search_terms_raw.json \
  --out google-ads-data/2026-11-07/search_terms.csv
```

Run it once per raw file. It maps column names, divides micros, drops Total rows and reported ratios, strips `[exact]` and `"phrase"` punctuation into `match_type`, and marks negatives. `review_terms.py` also understands the column names it leaves for fields it doesn't map, such as `campaign_search_term_view_search_term` and `segments_search_term_match_source`.

Suggested file names in `google-ads-data/<end-date>/`: `search_terms.csv`, `pmax_search_terms.csv`, `campaigns.csv`, `keywords.csv`, `negatives_ad_group.csv`, `negatives_campaign.csv`, `negatives_lists.csv`, `list_attachments.csv`, `converting_terms_history.csv`.
