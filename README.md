# FOSSMate

FOSSMate is a GitHub App for open-source maintenance workflows.

Install app:
- https://github.com/apps/fossmate

## Who This Is For

### Open Source Maintainers (No Infra)
- Install the app and use it in your repositories.
- Guide: [For Open Source Maintainers](docs/MAINTAINER_INSTALL.md)

### Developers / Operators (Self-Hosted)
- Run backend, webhook endpoint, and model stack yourself.
- Guide: [For Developers (Self-Hosted)](docs/DEVELOPER_SETUP.md)

## Current Core Automation

- `issues.opened`
  - issue summary
  - label suggestion and apply flow
- `issue_comment.created`
  - auto-replies for `@fossmate`
  - onboarding replies for contributor-intent comments
- `pull_request.opened` + `pull_request.synchronize`
  - PR summary
  - per-file notes
  - review suggestions
  - advisory scorecard
  - PR thread summary comment
  - PR inline review submission with line comments (and `REQUEST_CHANGES` when risk is high)

## Architecture and Internals

- [Working Logic and Architecture](docs/WORKING_LOGIC.md)
- [Operating Model](docs/OPERATING_MODEL.md)
- [Roadmap](docs/ROADMAP.md)
- [Screenshots Guide](docs/SCREENSHOTS.md)

## Setup Helper

```bash
python scripts/setup_github_app.py --print-checklist
```

## API Endpoints

- `GET /health`
- `POST /webhooks/github`
- `POST /webhooks/github/test`
- `GET /chat/ping`
- `POST /chat/ask`
- `GET /admin/ping`
- `GET /admin/installations/{id}/status`
- `POST /admin/installations/{id}/replay/{event_id}`
- `GET /reports/developer-evaluation`

Optional:
- `POST /webhooks/gitlab` (if enabled)

## License

MIT (`LICENSE`).
