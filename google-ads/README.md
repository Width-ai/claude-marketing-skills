# Google Ads Skills

Skills for building, managing, and optimizing Google Ads accounts. They work through a connected Google Ads tool (Google's official Google Ads MCP server or a third-party connector) and fall back to CSV exports from the Google Ads web interface or Google Ads Editor when there's no connection.

**Belongs here:** skills for work inside Google Ads accounts, covering Search, Performance Max, Shopping, Demand Gen, and YouTube campaigns run through Google Ads. Other ad platforms get their own areas.

## Skills

| Skill | What it does | Guide |
|---|---|---|
| [google-ads-account-context](google-ads-account-context/) | Builds the context file the other skills read first: approved offers and proof, target and break-even CPA or ROAS, what each conversion really measures, protected terms, and change limits. | [Guide](../guides/google-ads/google-ads-account-context.md) |
| [google-ads-data-pull](google-ads-data-pull/) | Pulls data through a connector or exports, cleans it into standard tables, and computes every metric and comparison in code. | [Guide](../guides/google-ads/google-ads-data-pull.md) |
| [google-ads-campaign-builder](google-ads-campaign-builder/) | Turns a brief into a complete new Search campaign (ad groups, keywords, starting negatives, ads, sitelinks, callouts, and settings), all paused, with a plan to approve and Google Ads Editor import files. | [Guide](../guides/google-ads/google-ads-campaign-builder.md) |
| [google-ads-rsa-asset-writer](google-ads-rsa-asset-writer/) | Writes responsive search ads, sitelinks, callouts, and snippets from approved claims only, and checks limits, ad policies, and every claim with a script. | [Guide](../guides/google-ads/google-ads-rsa-asset-writer.md) |
| [google-ads-headline-optimizer](google-ads-headline-optimizer/) | Improves a live RSA's headlines from its performance data and competitor ads: keeps what works, replaces at most three lines that clearly lag, and plans a test of the change. | [Guide](../guides/google-ads/google-ads-headline-optimizer.md) |
| [google-ads-search-terms-to-negatives](google-ads-search-terms-to-negatives/) | Reviews the search terms report and proposes negatives and new paused keywords, calling a search wasted only when its clicks prove it and checking no negative blocks a converting search, a keyword, or a protected term. | [Guide](../guides/google-ads/google-ads-search-terms-to-negatives.md) |
| [google-ads-ai-max-pmax-review](google-ads-ai-max-pmax-review/) | Reviews AI Max and Performance Max from the advertiser's side: spend by channel, brand and irrelevant search terms, brand exclusions, the landing pages Google picked, placements, and conversion actions. | [Guide](../guides/google-ads/google-ads-ai-max-pmax-review.md) |
| [google-ads-recommendations-triage](google-ads-recommendations-triage/) | Sorts Google's recommendations into accept, reject, or test against your target and break-even, with a reason that names the numbers, experiment plans for tests, and an auto-apply check. | [Guide](../guides/google-ads/google-ads-recommendations-triage.md) |
| [google-ads-apply-changes](google-ads-apply-changes/) | Checks proposed changes against the live account, previews them, gets approval, and applies them through a connector or Google Ads Editor files. | [Guide](../guides/google-ads/google-ads-apply-changes.md) |
| [google-ads-change-log](google-ads-change-log/) | Logs every change with its reason and review date, and reconciles against the account's change history. | [Guide](../guides/google-ads/google-ads-change-log.md) |

Start with google-ads-account-context. The other skills read the file it creates.

## How the skills work together

Each skill works on its own, and they share files when installed side by side:

| File | Written by | Read by |
|---|---|---|
| `.agents/google-ads-context.md` | google-ads-account-context | All of them |
| `google-ads-data/<end-date>/*.csv` | google-ads-data-pull, and any skill that pulls its own data | Any skill that analyzes data |
| `google-ads-changes/<date>-<name>.json` | Any skill that proposes changes | google-ads-apply-changes, google-ads-change-log |
| `.agents/google-ads-change-log.csv` | google-ads-change-log (or google-ads-apply-changes when the log skill isn't installed) | All of them |

Skills that propose changes (the campaign builder, ad writer, headline optimizer, search terms review, AI Max and Performance Max review, and recommendations triage) never apply them. They write a change set for google-ads-apply-changes and include Editor files or step-by-step instructions for when it isn't installed.

In a chat without a project folder, the skills hand these files to you to download. Attach them in your next Google Ads chat, or add them to your project files.

## Safety defaults

Every skill in this area follows the same rules:

- Read only, unless a person approves a specific batch of changes after seeing it.
- Never delete anything; pause instead.
- New keywords, ads, ad groups, and campaigns start paused.
- Every number comes from code, not from the model's arithmetic.
- Missing data is marked MISSING, never estimated.
- Ad copy uses only offers and proof the business has approved.
