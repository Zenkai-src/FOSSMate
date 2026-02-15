# For Developers (Self-Hosted)

Use this if you are running FOSSMate backend yourself.

## 1. Clone and Environment

```bash
git clone https://github.com/Zenkai-src/FOSSMate.git
cd FOSSMate
conda create -n fossmate python=3.11 -y
conda activate fossmate
pip install -r backend/requirements.txt
cp .env.example .env
```

## 2. Configure GitHub App Auth

Use GitHub App private key auth (recommended):

```env
GITHUB_APP_ID=<real_app_id>
GITHUB_PRIVATE_KEY_PATH="/absolute/path/to/private-key.pem"
GITHUB_WEBHOOK_SECRET=<same_as_github_app_webhook_secret>
```

Notes:
- Quote key path if it has spaces.
- Keep `.pem` and `.env` out of git.

## 3. Configure Inference

Default local OSS path:

```env
LLM_PROVIDER=ollama
LLM_MODEL_NAME=llama3:8b
LLM_ENDPOINT=http://127.0.0.1:11434
```

## 4. Run Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 5. Expose Webhook URL in Development

```bash
ngrok http 8000
```

Set GitHub App webhook URL to:
- `https://<ngrok-domain>/webhooks/github`

## 6. Required GitHub App Permissions

- Issues: Read and write
- Pull requests: Read and write
- Checks: Read and write
- Contents: Read-only
- Metadata: Read-only

Required events:
- Issues
- Issue comment
- Pull request
- Pull request review comment
- Pull request review
- Installation
- Installation repositories

## 7. Continuous Operation Model

FOSSMate is event-driven.
- It does not poll GitHub continuously.
- GitHub pushes events to your webhook endpoint.
- If backend is down, events fail delivery/retry from GitHub side.

For always-on behavior:
- run backend as a managed service/process
- keep stable public webhook URL
- monitor delivery failures and queue backlog

## 8. Verify End-to-End

1. Open issue -> expect summary + labels.
2. Comment `@fossmate` -> expect automated reply.
3. Open PR -> expect PR summary + inline review comments.
4. Push commit to PR -> expect updated review path on synchronize event.

## 9. Common Failures

401 invalid signature:
- webhook secret mismatch

403 on comments/labels/reviews:
- app not installed on repo
- missing permission for target operation

No automation triggered:
- event not subscribed in GitHub App
- backend not reachable at configured webhook URL
