Adapted in part from "Account Audits, Scoring & Recommendation Guardrails" and the Performance Max guidance in google-search-playbook.md in [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT, Copyright (c) 2025 Corey Haines), and the operation-capability check in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici). The placement checks follow the method of Nils Rooijmans' free [Performance Max placement exclusion suggestions script](https://nilsrooijmans.com/google-ads-script-pmax-placement-exclusion-suggestions/), which has no license; the method is described here in our own words and no code was copied.

# Judging the review

Read this before writing any finding. Every number in a finding comes from `scripts/review.py` or `scripts/metrics.py`. This file says how to read those numbers and when they are enough to call something an issue.

## Statuses

Every area ends with one status:

| Status | Use when |
|---|---|
| **OK** | You saw the data and nothing needs to change |
| **Issue** | You saw the data, and it shows a problem the data can prove (the script's verdict says "data rules out") or a setting that is plainly wrong for this business |
| **Watch** | Something looks off but the script says "not conclusive yet" or "not enough data". Give the date or click count that would settle it. |
| **Too early** | `review.py timing` says to wait. Report the numbers as context only, with the date judging becomes fair. |
| **Unknown** | The data needed wasn't available. Say exactly which query or export would answer it. |
| **Not applicable** | The account doesn't run that feature |

Rules that keep the review honest:

- An Unknown never counts as an Issue. "I couldn't see your brand lists" is not "you have no brand exclusions."
- Not using a feature is never an Issue. This skill reviews what's running. It doesn't push AI Max, Performance Max, video, or any new setting.
- Report coverage separately: how many of the nine areas you could check, and the disclosed share of search term clicks.
- Before recommending any change, confirm the change can be made for this campaign type in this account: the setting exists in the interface, or the connector or Google Ads Editor supports it. If you can't confirm it, say what to check instead of recommending it.
- Practitioner results in `references/platform-facts.md` explain why a check exists. Never quote them as what this account should expect.

## 0. Timing (always first)

`review.py timing` with the change log or change history, and the campaign settings.

- **Too early** for a campaign when it says "wait". Google's waiting periods: about two weeks after turning on AI Max, two to three weeks after Performance Max asset changes, two weeks plus the conversion delay after target or bid strategy changes.
- "Window split by" an event: split the window at that date and compare the parts. Don't average across it.
- "Last N days undercount conversions": move the window end back or label the last days incomplete.
- "Crosses 2026-08-17": budget-limited target CPA or ROAS campaigns spend toward the target after that date. Don't compare a CPA trend across it without saying so.
- "Bid strategy learning": performance isn't readable yet. A verified break (tracking broken, a page down) still gets fixed now.
- Campaigns moved into AI Max in September 2026 may have no recorded change. Ask the person when AI Max was turned on before judging it.

## 1. Where the spend went

`review.py channels` on the campaign by network pull, with the target CPA or ROAS from the account context.

- Compare each channel's cost share with its conversion share. A channel that takes much more of the cost than of the conversions, with the verdict "above target CPA (data rules out target)", is an **Issue**. "Not conclusive yet" is **Watch**.
- For AI Max Search campaigns, the same table splits Google Search from Search partners.
- Say how much cost is "cross-network (not split)". That part can't be assigned to a channel.
- Check which conversion actions sit behind cheap channels before praising them. Maps conversions are often direction clicks (see area 6).
- What you can do about a channel is limited. Most accounts can't switch Performance Max channels off (only a mid-2026 pilot could). The levers are placement exclusions, the assets that feed that channel (video drives YouTube), conversion goals, and budget. Say this in the finding, so a channel finding doesn't read as "turn off Display."
- Don't call video or Display worthless because they show few last-click conversions. Say that's what the data shows and that view-through and assist effects aren't in it.

## 2. Search terms

`review.py terms` on the Performance Max and AI Max search terms, with the keyword inventory, campaign totals, brand terms, and the account context.

1. **State the disclosed share first** (the coverage table). Every share below is a share of what Google discloses, not of all traffic.
2. **Irrelevant terms.** Terms matching "Terms we don't want" in the account context are counted automatically. Then read the top terms by cost yourself and propose labels for the rest in a labels file (`search_term,label,reason`, with label `irrelevant`, `relevant`, `brand`, or `competitor`). Show the labels to the person, then rerun with `--labels` so the totals come from code. Never label a term irrelevant only because it sounds off: the offer may cover it. Ask.
3. **Competitor terms.** Follow the "Competitor policy" section. Pass `--no-competitor-bidding` only when it says not to bid on competitors. Otherwise report them as information.
4. **Identical to an exact keyword elsewhere.** A Performance Max term that equals an exact keyword in a Search campaign means the Search campaign didn't take that search. Google says that happens when the Search campaign is limited by budget, the keyword has low volume, its ads are disapproved, or its targeting isn't met. Check those four (the budget check shows the first) before calling it an **Issue**. Compare the two campaigns' CPA on that term where both have data.
5. **AI Max against your own keywords.** The match source table splits each AI Max campaign into your keywords, AI Max broad match, and AI Max keywordless. AI Max matches with "above target CPA (data rules out target)" while your keywords sit within target is an **Issue**. If they're within target, say so plainly: the practitioner criticism doesn't apply to this account.
6. **Search themes that repeat a Search keyword.** An identical exact keyword wins the search; an identical phrase or broad keyword shares priority with the theme. Repeats are a structure question, rarely urgent.
7. **Exclusion candidates.** The grouped table checks each proposed negative against every disclosed term in that campaign. Anything in `would_block_converting` goes back to the person. Routes marked "blocked" touch a protected term and are dropped unless the person says otherwise.

## 3. Brand traffic

From the terms output plus the brand list query.

- Report the brand share of each Performance Max and AI Max campaign's disclosed cost and conversions, and the CPA with and without brand ("ALL except brand"). Brand searches usually convert cheaply, so they can make a campaign look better than its non-brand work is. Judge budget and targets on the non-brand numbers.
- **Brand exclusions set?** No `BRAND_LIST` exclusion on a Performance Max campaign that shows brand terms, while a brand Search campaign exists, is an **Issue** for most advertisers. If there is no brand Search campaign, excluding brand from Performance Max could drop those searches entirely: recommend building or checking the brand campaign first, and let the person decide.
- Performance Max brand exclusions cover Search and Shopping inventory only. Brand lists match variants and misspellings on their own.
- AI Max: brand exclusions need AI Max on. In a non-brand AI Max campaign, brand terms point to a brand exclusion or a brand negative so the brand campaign gets those searches.
- Don't say Performance Max "steals" brand conversions. Some brand clicks would have come through the brand campaign anyway and some might not. The clean test is a brand exclusion with a before and after comparison of total brand conversions across campaigns. Recommend that, with the review date.

## 4. Landing pages

`review.py landing` on the expanded landing pages, with your own final URLs from ads and asset groups.

- Report the share of clicks, cost, and conversions that went to pages Google chose, and their conversion rate against your own pages in the same campaign.
- Open the top expanded pages by cost (web fetch or browser) before judging them. Describe them from what's on the page, not from the URL. Note pages that are down, off-offer, or informational.
- **Issue:** paid clicks going to careers, login, legal, or other pages that can't convert; or expanded pages as a group converting below your pages with the verdict "data rules out their rate."
- **Fix size:** a few bad pages call for URL exclusions. Expanded pages that convert worse as a group, or a business that must control its landing pages (regulated industries, required disclaimers), call for turning final URL expansion off. In AI Max, text disclaimers are the way to keep required text when expansion stays on.
- Practitioners report URL exclusions that don't always hold. Any exclusion gets a review date two weeks out to check the landing pages again.
- The Performance Max final URL expansion asset view has one row per asset and URL. Use it to see which URLs and generated text ran, not to total clicks by page.

## 5. Placements

`review.py placements` on the Performance Max placement report.

- Placement data is impressions only, and Google calls it a brand safety tool. Findings here are about where the brand appears and obvious junk inventory, not CPA. Pair them with the channel table, which has Display and YouTube cost and CPA.
- The flags follow Nils Rooijmans' method: every mobile app placement, websites whose domain ending isn't on a short safe list (add the account's country ending with `--extra-tlds`, such as `co.uk`), domains that look generated (several hyphens, digit runs, repeated characters, punycode, spam words), and YouTube videos whose titles look like clickbait or children's content.
- Flags are prompts to look, not verdicts. Open each flagged placement before proposing it. A news site on an unusual country domain can be fine; a game app that shows ads between levels deserves a hard look.
- "Google Owned & Operated" and "anonymous.google" group many placements and can't be excluded.
- Placement exclusions are made in the Google Ads interface. An account-level list also affects Display, YouTube, and Demand Gen campaigns: say so.

## 6. Conversion quality

`review.py conversions` with the conversion action settings and the account context's "Conversions" table.

- List which actions make up each campaign's conversions. Pass the actions the context marks as not driving bidding, or describes as low value (page views, direction clicks, newsletter signups), as `--low-value`.
- **Issue:** a low-value action is a large share of a Performance Max or AI Max campaign's conversions, or those campaigns count actions the Search campaigns don't. Performance Max will buy more of whatever it's told to count.
- For lead generation, ask whether leads from Performance Max become customers as often as Search leads. If the CRM says they don't, Performance Max is cheaper only on paper. MISSING when there's no CRM data.
- Conversion goal changes are the person's call. Changing which actions count resets learning on every campaign that uses them, so recommend timing it outside a peak.

## 7. Budget and targets

`review.py budget` with the target and break-even from the account context's "Economics" section.

- "Limited by budget" plus a non-brand CPA within target is a candidate for a budget raise. A blended CPA within target only because of brand traffic is not. Use the non-brand numbers from area 3.
- A campaign target far from the business target or the break-even point is worth raising with the person, with both numbers.
- Since August 17, 2026, a budget-limited target CPA or ROAS campaign spends toward its target. A CPA that rose toward the target after that date may be that change, not a decline.
- Shared budgets: a change to one campaign changes every campaign on it.
- Budget and target changes go into the change set, inside the context file's limits, and only when timing allows.

## 8. Asset coverage

`review.py assets` with asset groups and campaign-level assets.

- Below Google's required minimums is an **Issue**. Below the recommended counts is **Watch**. Feed-only asset groups in Merchant Center campaigns are **Not applicable**.
- No video uploaded means Google may generate one from the images. Say so; don't call it an error.
- Read the Google-created ("Google AI") assets and text customization headlines against the account context's approved offers and claims. Generated text that promises something the business hasn't approved is an **Issue**.
- Ad Strength is Google's measure of asset completeness, not of results. Never present it as performance.
- New assets need two to three weeks before they can be judged.

## Writing a finding

One short block per finding:

> **Brand traffic in PMax - Leads: Issue.** Brand searches took 12.2% of the campaign's disclosed search term cost and 48.6% of its disclosed conversions, and no brand exclusion is attached. Without brand, the disclosed CPA is 66.55 against 38.94 with it. Evidence: Performance Max search terms, Oct 18 to Nov 14, 10.7% of clicks disclosed. Recommendation M1.

Then end the report with three lists:

- **Facts:** each with its dataset and window.
- **Hypotheses:** each with a confidence level.
- **Missing data:** each with how it could change the answer.

## Never

- Judge a campaign inside a waiting period, or across a change, without saying so.
- Recommend turning AI Max or Performance Max off because practitioners dislike them. Judge this account's numbers.
- Call terms, pages, or placements wasted below a readable sample. Use the verdicts.
- Describe a landing page or placement you haven't opened.
- Treat Ad Strength or optimization score as a performance metric.
- Fill a gap with a benchmark. Missing means MISSING.
