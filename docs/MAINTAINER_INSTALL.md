# For Open Source Maintainers

If you only want to use FOSSMate, you do not need to run any backend locally.

Install the GitHub App:
- https://github.com/apps/fossmate

## Install Steps

1. Open the app page and click **Install**.
2. Select your organization or account.
3. Choose repositories (start with selected repos if testing).
4. Complete installation.

That is the user-facing path.

## What Happens After Install

FOSSMate listens to GitHub webhooks and responds automatically to supported events.

Current automations:
- New issue opened:
  - issue summary
  - suggested labels + auto-apply path
- New issue/PR comments:
  - auto-replies for `@fossmate` and (by default) new comments
  - onboarding guidance for contributor-intent questions
- PR opened/synchronized:
  - PR summary
  - per-file notes
  - review suggestions
  - advisory score
  - PR review comments (including inline line comments where possible)

## How to Trigger It

- Mention `@fossmate` in an issue/PR comment.
- Ask onboarding-style questions like:
  - "How can I work on this?"
  - "Can you assign this to me?"

## Troubleshooting (Maintainer View)

If nothing happens:
1. Confirm app is installed on that exact repository.
2. Confirm webhook deliveries are green in GitHub App settings.
3. Confirm the service operator has configured required permissions/events.
4. Check whether your comment is in supported event types (`issue_comment`, PR thread comments/review comments).

If PR check-runs are missing:
- App needs `Checks: Read and write` permission.
