---
name: google-ads-data-pull
description: >
  Pulls Google Ads data through whatever is available (a connected Google Ads
  tool that runs GAQL queries or reports, or CSV exports from the Google Ads
  web interface or Google Ads Editor), cleans it into standard tables, and
  computes every metric and period comparison in code so numbers and
  directions are never guessed. Use when someone asks to pull, export, check,
  or compare Google Ads numbers, search terms, keywords, ads, conversions,
  impression share, or change history, or when another Google Ads task needs
  account data first.
metadata:
  version: "1.0.0"
---

# Google Ads Data Pull

Get the right Google Ads data for the question, from the best source available, into clean tables you can trust. Then report what the data shows, with its limits stated up front.

Two rules hold for everything below:

1. **Every number comes from code.** Sums, ratios, differences, and percentage changes come from `scripts/metrics.py`, never from mental math. Say "up" or "down" only as the script reports it.
2. **Missing means MISSING.** If a dataset or field isn't available, say so and leave it out of calculations. Don't estimate it, work it out backward from other numbers, or fill it from a benchmark.

Script paths are relative to this skill's folder. The scripts use only the Python standard library.

## Step 1: Pin down the request

Read `.agents/google-ads-context.md` if it exists. It has the account ID, currency, time zone, what each conversion action measures, and the target CPA or ROAS.

Settle these before pulling anything:

- **Account:** the customer ID, plus the manager account ID if access goes through one.
- **Question:** the decision this data is for. It decides which datasets you need.
- **Window:** explicit start and end dates in the account's time zone. If the question is about change, add a comparison window of the same length. Flag the last few days as incomplete when conversions arrive late.
- **Datasets:** pick from `references/gaql-queries.md`. Each query says which question it answers. Pull only what the question needs.

## Step 2: Choose the source

Check which tools this session has.

| What's available | Use it like this |
|---|---|
| A tool that runs GAQL, such as `search` on Google's official Google Ads MCP server or a third-party tool that accepts a query | Run the queries in `references/gaql-queries.md`. This is the preferred source. |
| A Google Ads connector with fixed reports and no GAQL | Use its reports for the same datasets. Mark any metric it doesn't return as MISSING. |
| No connector | Ask for exports, using the steps in `references/exports.md`, for only the datasets needed. |
| A connector plus a file the person attached | Use the connector for the main pull and the file only for what the connector lacks. Say which number came from where. |

Tool names differ between connectors (`search`, `run_gaql`, `execute_gaql_query`, and others), so work out which tool does the job from its description. This skill only reads. Never call a tool that changes the account.

## Step 3: Pull

- Use explicit dates (`segments.date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`), not `DURING` literals, so the pull can be repeated exactly.
- Before an unfamiliar query, check field names with the connector's metadata tool if it has one (`get_resource_metadata` on the official server). Google releases a new API version every few months and fields get renamed.
- An error such as `UNRECOGNIZED_FIELD` or `INVALID_ARGUMENT` means the query needs fixing, not that the data is empty. Fix it, or report the dataset as MISSING with the error. Never show a failed query as zero.
- Save each raw result to a file in `google-ads-data/<end-date>/`, such as `search_terms_raw.json`, before analyzing it. Large results don't belong in the conversation.
- For search terms, raise the `LIMIT` until disclosed clicks stop growing. A low limit hides the long tail.

## Step 4: Normalize

Run every raw file or export through the normalizer:

```bash
python3 scripts/normalize.py google-ads-data/2026-11-14/search_terms_raw.json \
  --out google-ads-data/2026-11-14/search_terms.csv
```

It reads connector JSON, CSVs with GAQL field names, Google Ads web interface downloads, and Google Ads Editor exports (UTF-16 and tab-separated included). It:

- maps columns to standard names: `campaign`, `ad_group`, `keyword`, `match_type`, `search_term`, `impressions`, `clicks`, `cost`, `conversions`, `conversion_value`, and so on
- converts micros to currency and percentages to fractions
- keeps values like "< 10%" as numbers, with a `_bound` flag column
- drops Total rows
- marks negative keywords in `is_negative`
- drops reported ratios (CTR, CPC, CPA, ROAS) so `metrics.py` recomputes them from sums

Use `--group-by` to collapse daily rows, for example `--group-by campaign,ad_group,keyword,match_type` for keywords. Read the summary it prints, and put unmapped columns, bound flags, and its notes in your data notes.

## Step 5: Compute

Use `scripts/metrics.py` for every number you report:

| Need | Command |
|---|---|
| Totals and ratios by any grouping | `metrics.py summary campaigns.csv --by campaign --target-cpa 80` |
| This period vs. the last one | `metrics.py compare current.csv prior.csv --by campaign`, or one file with a `date` column and `--current START:END --prior START:END` |
| How much traffic the search terms report shows | `metrics.py coverage --search-terms search_terms.csv --campaigns campaigns.csv` |
| Whether zero conversions means anything | `metrics.py zero-conv --clicks 40 --cpc 2.10 --target-cpa 80` |

Add `--markdown` for a table to paste into the answer.

With `--target-cpa`, `summary` adds the break-even conversion rate (CPC divided by target CPA). For rows with zero conversions, it also adds the highest conversion rate the data rules out at 95% confidence. A row is "underperforming" only when the data rules out converting at break-even. Otherwise it's "not enough data", and that's what you report.

## Step 6: Report

Read `references/reading-the-data.md` before writing any conclusion. Then answer in this shape:

1. **Answer:** two or three sentences that answer the question, using only script output.
2. **Numbers:** a compact table from `metrics.py`.
3. **Data notes:**
   - the source and tool, account ID, window and time zone, and currency
   - row counts and the share of search term clicks Google disclosed
   - recent days affected by conversion delay
   - campaigns in learning, and changes made inside the window that split it
4. **Facts, hypotheses, missing data:** three short labeled lists.
   - **Facts:** cite the dataset and window.
   - **Hypotheses:** say how confident you are.
   - **Missing data:** say how it could change the answer.

Label any figure that didn't come from this session's pull as stale, with its date.

## Quality checks

Before answering, confirm:

- Every percentage change and its direction came from `metrics.py`.
- No ratio was averaged across rows; ratios were recomputed from summed numerators and denominators.
- Positive and negative keywords were kept apart.
- Search term findings state the disclosed share of clicks.
- Failed queries appear as MISSING with their error, not as zero.

## Reference files

| File | Read it when |
|---|---|
| `references/gaql-queries.md` | Choosing datasets and running queries through a connector (Steps 1 to 3) |
| `references/exports.md` | No connector is available and you need to ask for exports (Step 2) |
| `references/reading-the-data.md` | Before interpreting any result or writing conclusions (Step 6) |
| `scripts/normalize.py` | Cleaning every raw result or export (Step 4) |
| `scripts/metrics.py` | Computing every number you report (Step 5) |
