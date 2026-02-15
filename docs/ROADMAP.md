# FOSSMate Roadmap

## Direction

Build an installable, self-hostable AI maintainer assistant where the core workflow does not require proprietary APIs.

## Phase 1: Foundation (Completed)

- FastAPI scaffold
- Webhook verification + persistence
- Provider abstraction
- Async DB layer

## Phase 2: OSS-Core Automation (Current)

- `issues.opened`: summary + label suggestion
- `issue_comment.created`: onboarding intent replies
- `pull_request.opened`: PR summary
- Ollama/local model baseline prompts

## Phase 3: OSS RAG Pipeline

- Repo ingestion (`.py`, `.js`, `.ts`, `.md`, README, CONTRIBUTING)
- Smart chunking
- Embeddings + Qdrant indexing
- Source-cited answers

## Phase 4: Reliability and Scale

- Queue workers and retry semantics
- Idempotency and replay safety
- Observability and metrics
- Multi-installation configuration
- CI and integration tests

## Optional Adapter Track

- Keep proprietary providers (Gemini/OpenAI) as optional adapters.
- Ensure features land first on OSS-core provider path.
