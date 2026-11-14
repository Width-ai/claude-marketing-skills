# Prefill queries

Run these through a connector tool that accepts GAQL (`search` on Google's official Google Ads MCP server, with `customer_id` and `query`). If the connector only has fixed reports, use its account, campaign, and conversion reports instead. If the google-ads-data-pull skill is installed, you can use it for these pulls and its normalizer for the results.

Use explicit dates for the last 90 days, ending yesterday, in place of `<START>` and `<END>`. Customer IDs go without hyphens. If a field errors, check it with the connector's metadata tool rather than skipping the section.

## Account basics

```sql
SELECT customer.id, customer.descriptive_name, customer.currency_code,
       customer.time_zone, customer.auto_tagging_enabled
FROM customer
```

Fills: Customer ID, account name, Currency, Time zone, Auto-tagging.

## Campaigns

```sql
SELECT campaign.id, campaign.name, campaign.status,
       campaign.advertising_channel_type, campaign.bidding_strategy_type,
       campaign_budget.amount_micros, campaign_budget.explicitly_shared
FROM campaign
WHERE campaign.status != 'REMOVED'
```

Fills: the Campaign map table (name and type). Budgets are in micros; divide by 1,000,000. The person supplies "what it's for". Note shared budgets: a change to one changes every campaign that uses it.

## Conversion actions

```sql
SELECT conversion_action.id, conversion_action.name, conversion_action.status,
       conversion_action.category, conversion_action.type,
       conversion_action.primary_for_goal, conversion_action.counting_type,
       conversion_action.click_through_lookback_window_days
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
```

Fills: one row per action in the Conversions table, with "Drives bidding (primary)?" from `primary_for_goal`. The person supplies what each action really measures, its real value, and known problems.

## Which actions actually fire

```sql
SELECT segments.conversion_action_name, metrics.conversions, metrics.all_conversions
FROM campaign
WHERE segments.date BETWEEN '<START>' AND '<END>'
  AND metrics.all_conversions > 0
```

Sum the rows by action in code. An enabled action with zero conversions in 90 days is worth asking about: it may be broken, or it may be rare. An action counted in "All conv." but not "Conversions" is secondary.

## Brand terms for the Protected terms list

The account's own brand keywords and top brand search terms are a good starting list. Look for campaign names containing "brand" and pull their keywords, or ask the person. Confirm the list with them; never add a term only because it looked like a brand.
