# Google Ads Skills

Skills for managing and optimizing Google Ads accounts. They work through a connected Google Ads tool (Google's official Google Ads MCP server or a third-party connector) and fall back to CSV exports from the Google Ads web interface or Google Ads Editor when there's no connection.

**Belongs here:** skills for work inside Google Ads accounts, covering Search, Performance Max, Shopping, Demand Gen, and YouTube campaigns run through Google Ads. Other ad platforms get their own areas.

## Skills

| Skill | What it does | Guide |
|---|---|---|
| [google-ads-account-context](google-ads-account-context/) | Builds the context file the other skills read first: approved offers and proof, target and break-even CPA or ROAS, what each conversion really measures, protected terms, and change limits. | [Guide](../guides/google-ads/google-ads-account-context.md) |
| [google-ads-data-pull](google-ads-data-pull/) | Pulls data through a connector or exports, cleans it into standard tables, and computes every metric and comparison in code. | [Guide](../guides/google-ads/google-ads-data-pull.md) |
| [google-ads-apply-changes](google-ads-apply-changes/) | Checks proposed changes against the live account, previews them, gets approval, and applies them through a connector or Google Ads Editor files. | [Guide](../guides/google-ads/google-ads-apply-changes.md) |
| [google-ads-change-log](google-ads-change-log/) | Logs every change with its reason and review date, and reconciles against the account's change history. | [Guide](../guides/google-ads/google-ads-change-log.md) |

Start with google-ads-account-context. The other three read the file it creates.

## How the skills work together

Each skill works on its own, and they share files when installed side by side:

| File | Written by | Read by |
|---|---|---|
| `.agents/google-ads-context.md` | google-ads-account-context | All of them |
| `google-ads-data/<end-date>/*.csv` | google-ads-data-pull | google-ads-apply-changes, google-ads-change-log |
| `google-ads-changes/<date>-<name>.json` | google-ads-apply-changes | google-ads-change-log |
| `.agents/google-ads-change-log.csv` | google-ads-change-log (or google-ads-apply-changes when the log skill isn't installed) | All of them |

In a chat without a project folder, the skills hand these files to you to download. Attach them in your next Google Ads chat, or add them to your project files.

## Safety defaults

Every skill in this area follows the same rules:

- Read only, unless a person approves a specific batch of changes after seeing it.
- Never delete anything; pause instead.
- New keywords, ads, ad groups, and campaigns start paused.
- Every number comes from code, not from the model's arithmetic.
- Missing data is marked MISSING, never estimated.
