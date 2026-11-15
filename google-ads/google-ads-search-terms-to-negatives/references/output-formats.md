# Output formats

## Files from `review_terms.py`

All go in the `--out` folder, such as `google-ads-data/2026-11-07/search-term-review/`.

| File | What's in it |
|---|---|
| `review.md` | The readable review: window and economics, coverage by campaign (total clicks, disclosed clicks, disclosed share, AI Max share), summary counts, proposed negatives, keywords to promote, review by hand, watch list, candidates that failed a check, already blocked, data notes, and MISSING inputs |
| `proposals.csv` | One row per proposed change. The person edits only the `include` column (yes or no) |
| `rejected.csv` | Every candidate negative that failed a check, with the level tried and why |
| `terms.csv` | Every campaign and search term pair: totals, break-even rate, upper and lower bounds, verdict, status, proposal id, and a note |
| `ngrams.csv` | Every 1 to 3 word n-gram found in 2 or more searches, by scope, with totals, verdict, clicks needed, and what happened to it |

`proposals.csv` columns: `id, include, action, level, campaign, ad_group, shared_set, list_campaigns, keyword, match_type, basis, source, test, reason, evidence, expected_effect, blocks_example, must_not_block, terms_blocked, clicks, cost, conversions, warnings, campaign_type, target_ad_group`.

- `basis` is `intent`, `performance`, or `promote`.
- `source` is `terms we don't want`, `intent file`, `n-gram`, or `search term`.
- `test` names the rule that justified it: `break-even (95%)`, a labeled fixed default, `intent`, or the promotion rule.
- `level` is `campaign`, `ad_group`, or `shared_list`.

Never edit numbers, evidence, or keywords in `proposals.csv`. To change a negative, drop it (`include` = no) and add the better one to the intent file, then run the review again so the new one gets checked.

## The answer in the chat

Keep it in this order:

1. **Answer.** Two or three sentences: how many negatives and keywords are proposed, the historical cost of the searches the negatives match (with the window, and "not a forecast"), and the disclosed share of clicks.
2. **Proposed negatives.** The table from `review.md`: ID, negative, match type, level, where, basis, evidence, blocks, must not block, warnings. Say which warnings need a decision.
3. **Keywords to add (created paused).** ID, keyword, campaign and ad group, evidence, confidence.
4. **Review by hand.** The searches and patterns that need a person, with why.
5. **Watch list.** The top 10 by cost, with what each still needs.
6. **Not proposed.** One line per rejected candidate that a person might have expected, with why.
7. **Data notes.** Source and tool, account, window and time zone, disclosed share, row counts, conversion delay.
8. **Facts, hypotheses, missing data.** Three short labeled lists. Facts cite the dataset and window. Hypotheses say how confident. Missing data says how it could change the answer.
9. **Next step.** Which lines to approve or drop, and how the batch will be applied.

Every number comes from the script's files. Don't add totals, percentages, or savings by hand.

## The change set (for google-ads-apply-changes)

`build_batch.py` writes `google-ads-changes/<date>-search-term-negatives.json` in the apply-changes format: `name`, `account_id`, `account_name`, `created`, `source`, empty `approved_by` and `approved_at`, and `changes`.

| Proposal | Change set entry |
|---|---|
| Negative, campaign level | `add_negative`, `level: campaign`, `campaign`, `keyword`, `match_type` |
| Negative, ad group level | `add_negative`, `level: ad_group`, `campaign`, `ad_group`, `keyword`, `match_type` |
| Negative, shared list | `other`, with `description` (the steps), `keyword`, `match_type`, `shared_set`, `campaigns`, and `entity_type`, `entity`, `field` for the change log. The change set has no shared-list action, so these are applied by hand or through a connector that can edit lists |
| Keyword to promote | `add_keyword`, `campaign`, `ad_group`, `keyword`, `match_type: exact`, `status: paused` |

Every entry also carries `reason`, `evidence` (with the date range), `expected_effect` (historical spend, never a savings forecast), and `review_notes` when the proposal had warnings.

When the batch has more changes than "Max changes per batch" in the context (50 if not set), it's split into `-part1`, `-part2`, and so on, keeping the order: intent negatives, performance negatives, then keywords, strongest first.

## When google-ads-apply-changes isn't installed

Show the review, get the person's approval of the lines (or their edits to `include`), then build with a fallback folder:

```bash
python3 scripts/build_batch.py search-term-review/proposals.csv \
  --out google-ads-changes/2026-11-14-search-term-negatives.json \
  --context .agents/google-ads-context.md \
  --fallback-dir google-ads-changes/2026-11-14-search-term-negatives-manual/ \
  --approved-by "Name"
```

It writes:

| File | What it holds |
|---|---|
| `negatives.csv` | Campaign and ad group negatives for Google Ads Editor: Campaign, Ad Group, Keyword, Criterion Type (such as `Campaign Negative Phrase` or `Negative Exact`) |
| `keywords.csv` | New keywords for Editor: Campaign, Ad Group, Keyword, Criterion Type, Status (Paused) |
| `manual-steps.md` | Editor import steps, then numbered steps for the Google Ads interface with each keyword written in its match-type form (`[exact]`, `"phrase"`), including negative keyword lists, plus how to undo |

Files are UTF-16 and tab-separated, the format Editor exports. Add `--utf8` for comma-separated UTF-8 if Editor won't read them. Use `--draft` instead of `--approved-by` to make files for a look before approval; the steps then say not to post.

Nothing is applied by this skill. Editor holds imported changes as pending until the person clicks **Post**, which is the final check.

## Logging without the change log skill

After the person confirms the changes went live, add a row per change to `.agents/google-ads-change-log.csv` if the google-ads-change-log skill isn't installed. Columns:

`id, logged_at, status, account_id, campaign, ad_group, entity_type, entity, action, field, before, after, reason, evidence, expected_effect, approved_by, applied_via, applied_at, review_on, outcome, notes, change_set`

Set `review_on` two weeks after the change went live, the waiting period the Google Ads skills use for negatives and new keywords.
