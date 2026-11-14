# Google Ads Editor import

Use Editor files when no connected tool can make a change type, or when the person wants to review everything in Editor before it goes live. Editor shows every change as a pending edit and nothing reaches Google until the person clicks Post, which makes it a good final review step.

## Build the files

```bash
python3 scripts/build_editor_csv.py google-ads-changes/2026-11-14-negatives.json \
  --out google-ads-changes/2026-11-14-negatives-editor/
```

The builder refuses a change set without `approved_by` unless you pass `--include-unapproved` to make a draft for review. It writes:

| File | Columns |
|---|---|
| `negatives.csv` | Campaign, Ad Group, Keyword, Criterion Type (`Negative Exact`, or `Campaign Negative Phrase` with Ad Group blank) |
| `keywords.csv` | Campaign, Ad Group, Keyword, Criterion Type, Max CPC, Final URL, Status |
| `keyword_bids.csv` | Campaign, Ad Group, Keyword, Criterion Type, Max CPC |
| `campaign_status.csv` | Campaign, Campaign Status |
| `ad_group_status.csv` | Campaign, Ad Group, Ad Group Status |
| `keyword_status.csv` | Campaign, Ad Group, Keyword, Criterion Type, Status |
| `budgets.csv` | Campaign, Budget |
| `ads.csv` | Campaign, Ad Group, Ad type, Headline 1 to 15, Description 1 to 4, Path 1, Path 2, Final URL, Status |
| `rollback/` | Files that undo budget, bid, and status changes, and pause added keywords |
| `manifest.md` | Import order, what each file holds, what must be undone by hand, and what isn't in the files |

Each file has only the columns its change type needs, so blank cells can't be read as "clear this value". In Editor, each row is one item, and which columns are filled tells Editor what kind of item it is: a row with Campaign, Ad Group, and Keyword is a keyword.

Files are UTF-16 and tab-separated, the format Editor writes when it exports and the encoding Google recommends for text with non-English characters. If Editor won't read them, rebuild with `--utf8` for comma-separated UTF-8.

## Header spellings

The builder uses Google's standard Editor column headers. Editor versions and languages can label columns a little differently. If the import preview shows a column it doesn't recognize:

1. Ask the person to export a small sample from their Editor (Account > Export, CSV).
2. Rebuild with `--template that-export.csv`. The builder copies the export's exact header spellings.

The person can also fix a header in the import preview by picking the right column from the drop-down.

## Steps for the person

Give these steps along with the files:

1. Open Google Ads Editor and select the account. Click **Get recent changes** so Editor has the latest version of the account.
2. Go to **Account > Import > From file...** and pick the first file in the manifest's order.
3. In the preview, check the column headers match. If one is wrong, choose the right one from the drop-down.
4. Finish the import. Editor marks imported items as pending changes. Nothing is live yet.
5. Repeat for each file in the manifest's order.
6. Review the pending changes in Editor. Check that campaign and ad group names match existing ones. A new campaign or ad group you didn't expect means a name was misspelled: revert it before posting.
7. Click **Check changes** to run Editor's own validation, and fix anything it flags.
8. Click **Post** to send the changes to Google Ads.
9. Reply here when it's posted, so the changes can be verified and logged.

Before posting, any pending change can be reverted in Editor. After posting, import the files in `rollback/` to undo budget, bid, and status changes. Undo the items listed under "Undo by hand" in the manifest directly in Editor or the Google Ads interface.

## After posting

Re-pull the changed items (through the connector or a fresh export) and compare them with the change set. Changes posted from Editor don't appear in the change history available through the Google Ads API. Log them with `applied_via` set to `editor`, so the change log doesn't flag them as missing.
