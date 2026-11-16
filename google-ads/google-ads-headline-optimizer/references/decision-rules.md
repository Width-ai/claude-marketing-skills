# Deciding what to change, and testing it

Read this after the analyzer runs and before writing any headline.

## How the analyzer judges a headline

Each unpinned headline is compared with the ad's other unpinned headlines, on two rates: CTR (clicks per impression) and conversions per impression. "Clearly above" or "clearly below" means the headline's 95% range doesn't include the others' rate. Everything else is "no clear difference".

| Verdict | When | What to do |
|---|---|---|
| **replace** | Google hasn't shown it, or shows it under a tenth as often as the most-shown headline with no conversions | Replace first. Google's own model has stopped choosing it. |
| **replace** | CTR or conversions per impression clearly below the others | Replace, unless it's the only line carrying something the ad needs (see below) |
| **keep** | Clearly above the others on CTR or conversions per impression | Keep, and never edit its text |
| **keep for now** | No clear difference | Keep this round. A near duplicate of another line can go if a slot is needed. |
| **too early** | The ad has under 2,000 impressions in the range, or Google lists the line as learning | Don't remove anything. Fill empty slots, or wait. |
| **pinned** | Pinned to a position | Not compared, because it shows every time its position shows. Change a pin only if the person asks. |

The thresholds sit at the top of `scripts/analyze_headlines.py`.

Headlines serve in combinations, and Google shows each line more often to the searches it expects it to win. So a headline's numbers partly reflect the lines and searches it showed with. A replace verdict is a reason to test a new line, not proof the old one is bad. Say this in the output.

## Choosing what to replace

1. **Take the analyzer's order.** It lists rarely shown lines first, then the ones furthest below the others, then near duplicates. Replace at most 3 per round (`--max-replace`). More changes at once make it impossible to tell which line made the difference.
2. **Keep what the ad needs.** Before removing a line, check what it carries. If it's the only headline with a converting keyword, the only proof line, the only call to action, or a required disclaimer, replace it with a better line of the same role, not a different angle.
3. **Fill empty slots too.** An RSA takes up to 15 headlines. Adding lines removes nothing, so new angles can go into empty slots in the same round, within the change limit.
4. **Never touch a "keep" line's text.** Not even its capitals. Google treats any edit as a new line with no history.
5. **Ask before changing pins.** Pins limit Google's combinations and often exist for a reason (a brand rule or a disclaimer).

## Where replacement lines come from

In this order:

1. **Converting searches no headline echoes.** The analyzer lists them with the missing words. A headline in the searcher's words is usually the safest win. Leave out competitor names, and services the business doesn't sell.
2. **Themes the kept lines don't cover.** The analyzer lists them (keyword, proof, call to action, offer). Fill them only with approved claims.
3. **Competitor gaps.** A claim type most competitors use and the ad doesn't. Ask the person whether the business can make an equal claim, in what words, and add it to the approved-claims file only if they approve.
4. **Differences only the business has.** Words only it uses, and approved proof points no competitor matches. These give a reason to pick the business over the ad next to it.
5. **The landing page.** Plain service and product words from it. A number, price, rating, guarantee, or result seen on the page is "seen on the page, needs approval" until the person approves it.

Write 2 or 3 candidates per open slot and pick with the person, or pick the strongest and show the rest as alternates.

## Writing replacement headlines

- **30 characters at most.** Chinese, Japanese, and Korean characters count as 2. The checker counts; never count by hand.
- **Each line must make sense alone and next to any other headline,** because Google mixes them. Don't start a sentence in one headline and finish it in another.
- **One idea per line, different from every other line.** A new line that says what a kept line already says won't get shown.
- **No invented claims.** Numbers, prices, discounts, "free", guarantees, superlatives ("best", "#1"), ratings, awards, credentials (licensed, certified), customer counts, and deadlines come only from the context file's "Business and offer" section or an approved-claims file. "Same-day service", "family-owned", and similar phrases are claims too, even when the checker can't spot them.
- **Follow the context file's brand voice:** its words to use and avoid, and its trademark notes.
- **Google's editorial rules:** no repeated punctuation, emoji, gimmicky capitals ("FREE"), phone numbers, or exclamation marks in headlines.
- **Match the ad's style.** Copy the capitalization and tone of the kept lines, so new lines don't stand out as different.

## Picking the route

Ask the person which route they want, and recommend one:

| Route | When | What happens |
|---|---|---|
| **Ad variation** (recommended) | The campaign has steady traffic, and the person can set it up in Google Ads | Experiments > Ad variations > Update text on the live ad, with a 50% split by user. The cleanest comparison, because the same ad runs both ways at once. Set up by hand; no connector or Editor file can create it. |
| **New ad** | The person wants both versions running as separate ads, or the account can't run experiments | A new paused RSA in the same ad group, with the old one left running. Google allows 3 enabled RSAs per ad group. Google gives more traffic to the ad it expects to win, so the comparison is rougher. |
| **Edit the live ad** | Only when the person asks | The edit creates a new version. Google keeps the old version's stats separately and the new version starts learning again, so before-and-after comparisons mix in seasons and bid changes. |

## Reviewing the result

Set the review for about 4 weeks after the change starts (`--review-days`), and later for low-volume ads. When the review comes:

- **For an ad variation,** compare the original and the variation on the Ad variations tab: clicks, CTR, conversions, and cost per conversion. Apply the variation if it wins on conversions per impression (or on CTR with conversions no worse); otherwise end it.
- **For a new ad,** compare the two ads over the same dates.
- **Then re-run the analyzer** on the winning ad, with dates starting when it went live, for the next round. Each new headline needs its own impressions before it can be judged; until then it shows as "too early" or "keep for now".

Log the change when it's live, with google-ads-change-log if it's installed, so the next review knows what changed and when.
