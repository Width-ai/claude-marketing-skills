# Applying changes through a connector

Discovery steps, write gates, and failure handling adapted from "Advertising MCP and Agent Integration" and the mutation gate in [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) (MIT, Copyright (c) 2026 Daniel Agrici).

A connector is a way to reach the account, not permission to change it. Permission comes from the person's approval of a specific batch.

## Before the first write in a session

Work out what the connected tool can actually do. Read each tool's description and input schema and sort them:

| Kind | Examples | Use in this skill |
|---|---|---|
| Read | GAQL search, reports, list accounts, field metadata | Snapshots and verification |
| Write with a dry run | Tools that accept `validate_only`, a preview flag, or a confirm step | Preferred for writes |
| Write without a dry run | Tools that change the account on the first call | Only for small, approved batches, one change type at a time |
| Unclear | Descriptions that don't say whether they write | Don't call against a live account |

Record which tool you'll use for each change type in the batch. If no tool clearly supports a change type, that change goes to an Editor file or to written manual steps.

## What common connectors can do

**Google's official Google Ads MCP server** (googleads/google-ads-mcp):

- **Reads:** any GAQL query (`search`), field metadata, and accessible accounts.
- **Writes:**
  - creating assets (text, image, YouTube video, sitelink, callout, structured snippet)
  - uploading video
  - managing labels and attaching labels to items
- **Can't:** create or change campaigns, ad groups, ads, keywords, negatives, budgets, or bids. It also can't link assets to campaigns or asset groups.
- **Confirm step:** every write runs as a dry run first and returns a checksum. The change only happens when the same call is repeated with that checksum. Google notes this prevents drift between preview and apply but isn't access control.
- **Tool names:** these have changed between releases. Confirm the current names from the tool list rather than assuming them.

**Third-party connectors** (hosted Google Ads connectors from reporting and automation vendors) vary. Some only read. Some create drafts that need approval in their own interface. Some apply changes immediately. Read the write tool descriptions every time, and don't assume a connector that writes budgets also writes negatives.

## Applying an approved batch

1. Confirm the account. The customer ID in the tool call matches the change set's `account_id`. For manager access, the login customer ID is the manager.
2. Re-check current values. If anything differs from the snapshot the person approved, stop and re-run the validator.
3. Dry run first, whenever the tool supports it. Show any errors before applying.
4. Apply in small groups: one change type at a time, starting with the lowest-risk type (negatives and pauses before budgets and targets).
5. After each group, read the changed items back and compare them to the change set.
6. Record what was applied, with times.

## When something goes wrong

- **Failed read:** retry once after a short pause. If it fails again, report the error.
- **Authentication, permission, validation, or policy errors:** don't retry. Report the error and the change it blocked.
- **Write that timed out or returned an unclear result:** read the item back before doing anything else. Only retry if the read shows the change didn't happen. Never apply the same change twice on a guess.
- **Stop using the connector for this batch** if a tool's behavior doesn't match its description, the account ID in a response doesn't match, or results can't be verified. Finish through Editor files or manual steps, and tell the person why.

## Never

- Delete campaigns, ad groups, ads, keywords, conversion actions, or audiences, even when asked to. Offer to pause, label, or export a backup instead.
- Treat "optimize everything" or "go ahead" as approval for changes the person hasn't seen.
- Store credentials, tokens, or customer lists in change sets, logs, or reports.
