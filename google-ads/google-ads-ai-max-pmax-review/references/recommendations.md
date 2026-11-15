# Turning findings into recommendations

This skill never changes the account. Each recommendation becomes either a change set entry for the google-ads-apply-changes skill or a numbered manual step for the Google Ads interface. Recommend a change only for an **Issue**, never for Watch, Too early, or Unknown.

## Which route

| Recommendation | Route | Why |
|---|---|---|
| Negative keyword on an AI Max (or other) Search campaign, campaign or ad group level | Change set: `add_negative` | Supported by apply-changes and Google Ads Editor |
| Pause a campaign | Change set: `set_status` to `paused` | Never `removed` |
| Daily budget change | Change set: `set_budget` | Check shared budgets first |
| Target CPA or ROAS change | Change set: `set_target` | Applied through a connector or by hand |
| Negative keyword or negative keyword list on Performance Max | Manual steps | Not covered by apply-changes; set it in the interface or in Google Ads Editor 2.11 or later |
| Brand exclusion (brand list) on Performance Max or AI Max | Manual steps | Not an apply-changes action |
| URL exclusions; turning final URL expansion or text customization off | Manual steps | Campaign settings only |
| Placement exclusions | Manual steps | Google said API placement exclusions don't apply to Performance Max |
| Search theme edits, asset changes, removing Google-created assets | Manual steps | Not apply-changes actions |
| Search partners off on a Search campaign | Manual steps | A network setting, not an apply-changes action |
| Conversion goal changes | Manual steps, for the person to decide | Tracking and goals stay with the person |

## Change set entries

Write them to `google-ads-changes/<YYYY-MM-DD>-ai-max-pmax-review.json` in the google-ads-apply-changes format. Use only these actions and fields. Copy `evidence` from the script output (the grouped exclusions table has it ready), never retype numbers.

```json
{
  "name": "2026-11-15 AI Max and Performance Max review",
  "account_id": "123-456-7890",
  "account_name": "Example Co",
  "created": "2026-11-15",
  "approved_by": "",
  "approved_at": "",
  "changes": [
    {
      "id": "c1",
      "action": "add_negative",
      "level": "campaign",
      "campaign": "Search - Water Heaters",
      "keyword": "jobs",
      "match_type": "phrase",
      "reason": "Job seekers matched by AI Max; 'jobs' is in Terms we don't want",
      "evidence": "1 search term, 9 clicks, 30.60 cost, 0 conversions, 2026-10-18 to 2026-11-14",
      "expected_effect": "Stops AI Max matching job searches in this campaign"
    },
    {
      "id": "c2",
      "action": "set_budget",
      "campaign": "PMax - Leads",
      "from": 250,
      "to": 290,
      "reason": "Limited by budget with non-brand CPA under target after brand exclusion",
      "evidence": "[numbers from review.py budget and terms]",
      "expected_effect": "More non-brand conversions near the target CPA"
    }
  ]
}
```

Rules:
- Exact campaign names as they are in the account. Keywords without brackets or quotes.
- Leave `approved_by` and `approved_at` empty. The person approves in google-ads-apply-changes.
- Respect the context file's limits (default 20% for budgets, 15% for targets, 50 changes per batch).
- Don't put a budget raise in the same batch as a brand exclusion for the same campaign. Make the brand change, wait for its review date, then judge the budget on the new numbers.
- Every entry gets a review date from the waiting periods: 14 days for negatives, 7 days for budgets (longer when conversions take more than a week to arrive), 14 days plus the conversion delay for targets. google-ads-apply-changes computes the same dates.

If google-ads-apply-changes is installed, tell the person to run it on the file. It validates names and limits against a fresh snapshot, previews, gets approval, and applies through a connector or Google Ads Editor files. If it isn't installed, give the change set entries as numbered manual steps too (below), and still save the file so it can be used later.

## Manual steps

Number them M1, M2, and so on, in the order they should be done. Each one says which campaign, what to change, the evidence, how to check it worked, and the review date. Google moves menus; if a step's path doesn't match, search for the setting name in the search bar at the top of Google Ads. Steps with a Google Ads Help link follow that page; the others describe common layouts and weren't checked against a Google page, so tell the person the path may differ.

**Brand exclusion on a Performance Max campaign**
1. Tools > Shared library > Brand lists. Create a list (for example "Our brand") or open the existing one.
2. Add the brand from Google's brand library. If it's missing, request it, and add the main brand name meanwhile.
3. Open the Performance Max campaign > Settings > Brand exclusions, select the list, and save.
4. Check: the brand list query (or the campaign's settings) shows the list attached as an exclusion.
5. Review in two weeks: brand terms in the campaign's search terms, and total brand conversions across all campaigns, before and after.

**Brand exclusion on an AI Max Search campaign** (AI Max must be on)
1. Make or open the brand list as above.
2. Open the Search campaign > Settings > AI Max section > brand exclusions, select the list, and save.
3. Brand searches should now go to the brand campaign. Check its impression share and conversions at the review date.

**URL exclusions on Performance Max** ([Google Ads Help](https://support.google.com/google-ads/answer/14337539?hl=en))
1. Campaigns > open the Performance Max campaign > Settings > Asset optimization.
2. Expand Text customization, then under Final URL select "Exclude some URLs".
3. List the URLs, or use the Rules tab for patterns (such as URLs containing /careers/), then Add.
4. Apply, then Save. Changes take 24 to 48 hours.

**Final URL expansion off on Performance Max**
1. Campaign settings > Asset optimization.
2. Clear the Final URL expansion checkbox and save. Traffic then goes only to the asset groups' final URLs and any page feed.

**URL exclusions on an AI Max Search campaign** ([Google Ads Help](https://support.google.com/google-ads/answer/16230205?hl=en))
1. Open the Search campaign's settings > AI Max section. AI Max, text customization, and final URL expansion must all be on.
2. Under Final URL expansion, select "Add URL exclusions".
3. List the URLs, or use the Rules tab, then Add. Apply, then Save.

**Final URL expansion off on an AI Max Search campaign**
1. Campaign settings > AI Max section > Asset optimization.
2. Clear Final URL expansion and save. Text customization stays on unless cleared too (turning text customization off also turns final URL expansion off). Pinned headlines are used again once expansion is off.

**Negative keywords on Performance Max**
1. Open the Performance Max campaign and find its negative keywords (in campaign settings in most layouts, or under negative search keywords with the campaign selected).
2. Add the negatives from the grouped exclusions table, with their match types. Up to 10,000 per campaign.
3. For a theme that applies to several campaigns, use a negative keyword list instead: Tools > Shared library > Negative keyword lists, add the terms, and apply the list to the campaigns.
4. Google Ads Editor 2.11 and later can also add Performance Max negative keyword lists.

**Placement exclusions**
1. Open the account's placement exclusions (under Content suitability or Brand safety, depending on the layout).
2. Add each approved placement exactly as the report shows it: the domain, the app ID (such as `mobileapp::2-com.example.app`), or the YouTube video or channel.
3. Choose account level so Performance Max respects it. Account-level exclusions also apply to Display, YouTube, and Demand Gen campaigns.
4. Recheck the placement report after a week.

**Search partners off on a Search campaign**
1. Campaign settings > Networks.
2. Clear "Include Google search partners" and save.

**Search themes**
1. Open the asset group > Signals > Search themes.
2. Remove or change themes that repeat a Search keyword, if the person wants Search to keep those searches. An identical exact keyword already wins without any change.

**Google-created assets**
1. AI Max: the campaign's asset report shows text customization assets with "Google AI" in the Added by column. Remove those that make claims the business hasn't approved. Bulk removal works in Google Ads Editor or the API, not the interface.
2. Performance Max: Assets > "Expanded Final URL assets" tab. Removing an asset there stops it across the whole campaign.

**Conversion goals** (the person decides)
1. Campaign settings > Goals. Check whether the campaign uses the account default goals or campaign-specific goals.
2. To stop a low-value action from driving bidding, make it secondary in Goals > Summary, or use campaign-specific goals that leave it out.
3. This resets learning for every campaign using that goal. Schedule it outside a peak period.

## Logging

When the person reports a manual step done, log it with the google-ads-change-log skill if it's installed. Otherwise append a row to `.agents/google-ads-change-log.csv` with `applied_via` set to `ui`. Use these actions for manual changes: `other` for brand exclusions, URL exclusions, placement exclusions, and expansion settings (describe the change in the entry), `add_negative` for Performance Max negatives, and `add_assets` for asset changes (reviewed after 21 days).
