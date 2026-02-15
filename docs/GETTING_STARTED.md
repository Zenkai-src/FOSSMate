# FOSSMate Beginner Setup Guide

This guide is for first-time users who want FOSSMate to run automatically on real repositories.

## 1. What You Are Setting Up

You are connecting four pieces:
1. GitHub App configuration (permissions, webhook URL, secret)
2. FOSSMate backend server (FastAPI)
3. LLM provider (Ollama local by default, Gemini optional)
4. Repository installation (install app on repo/org)

Once configured, FOSSMate processes GitHub events automatically.

## 2. Prerequisites

- macOS/Linux with `conda`
- Python 3.11 environment
- A GitHub account with permission to create/configure GitHub Apps
- One LLM path:
  - OSS path: local Ollama model (recommended default)
  - Optional API path: Gemini/OpenAI/OpenRouter

## 3. Clone and Install

```bash
git clone https://github.com/Zenkai-src/FOSSMate.git
cd FOSSMate
conda create -n fossmate python=3.11 -y
conda activate fossmate
pip install -r backend/requirements.txt
cp .env.example .env
```

## 4. Configure `.env`

Minimum required values:

```env
GITHUB_APP_ID=<your_real_app_id>
GITHUB_PRIVATE_KEY_PATH="/absolute/path/to/your-app-private-key.pem"
GITHUB_WEBHOOK_SECRET=<same_secret_as_github_app_webhook>
LLM_PROVIDER=ollama
LLM_MODEL_NAME=llama3:8b
LLM_ENDPOINT=http://localhost:11434
```

Notes:
- Keep `GITHUB_PRIVATE_KEY_PATH` quoted if the path contains spaces.
- Do not commit `.env` or `.pem` files.
- `GITHUB_TOKEN` is fallback-only for local experiments; app auth is the correct path.

## 5. Configure GitHub App (Critical)

In GitHub App settings, set:

App link for installation flow:
- https://github.com/apps/fossmate

Webhook:
- URL: `https://<your-public-domain>/webhooks/github`
- Secret: exactly `GITHUB_WEBHOOK_SECRET`

Repository permissions:
- Issues: Read and write
- Pull requests: Read and write
- Checks: Read and write
- Contents: Read-only
- Metadata: Read-only

Subscribe to events:
- Issues
- Issue comment
- Pull request
- Pull request review comment
- Pull request review
- Installation
- Installation repositories

Then install the app to your org/repositories.

## 6. Run Locally

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 7. Expose Webhooks During Local Dev

Use your tunnel (for example ngrok) so GitHub can reach your local backend:

```bash
ngrok http 8000
```

Set the GitHub App webhook URL to:

```text
https://<ngrok-domain>/webhooks/github
```

## 8. End-to-End Functional Test

Run these in an installed repository:

1. Open an issue.
Expected:
- FOSSMate posts issue summary comment
- FOSSMate suggests/applies triage labels

2. Add a comment like:
- "How can I work on this issue?"
Expected:
- FOSSMate posts onboarding guidance reply

3. Open a PR.
Expected:
- FOSSMate posts PR review comment with summary/suggestions/score
- FOSSMate creates a Check Run (requires `Checks: Read and write`)

## 9. Gemini Quick Test (Optional)

If you want to verify Gemini quickly:

```bash
LLM_PROVIDER=gemini LLM_MODEL_NAME=gemini-2.0-flash python backend/test_llm.py
```

A successful run prints a generated issue summary.

## 10. Troubleshooting

### Webhook returns 401 Invalid signature
- `GITHUB_WEBHOOK_SECRET` mismatch between GitHub and `.env`
- webhook body modified by proxy middleware

### Comments/labels fail with 403
- App not installed on target repo
- Missing `Issues: Read and write` / `Pull requests: Read and write`
- Running with PAT fallback that lacks scopes

### Check Run fails with 403
- Missing `Checks: Read and write` permission in GitHub App
- Permission changes require save + approval/reinstall in some org setups

### App appears "not connected"
- Verify app auth by checking installation repositories include your repo
- Verify webhook URL is reachable from GitHub
- Verify backend logs show accepted deliveries (`202`) and completed processing

## 11. Operator Checklist

Before production:
- Set stable HTTPS webhook URL (not temporary dev tunnel)
- Rotate webhook secret and private key regularly
- Keep `APP_ENV=production`
- Use persistent DB and queue backend as you scale
- Configure monitoring for webhook failures and queue backlog
