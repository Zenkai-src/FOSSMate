"""GitHub API interaction service."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import logging
from typing import Any

import httpx

from app.config import Settings
from app.utils.github_auth import GitHubAppAuth

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitHubService:
    """Thin async client wrapper for GitHub REST operations."""

    settings: Settings
    auth: GitHubAppAuth

    async def ping(self) -> str:
        """Simple async smoke test method."""
        return "github-service-ready"

    async def list_pull_request_files(
        self,
        repository_full_name: str,
        pr_number: int,
        installation_id: int,
    ) -> list[dict[str, Any]]:
        """Return pull request file change list from GitHub REST API."""
        token = await self.auth.get_installation_token(installation_id)
        url = f"https://api.github.com/repos/{repository_full_name}/pulls/{pr_number}/files"
        headers = self._build_headers(token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, list) else []

    async def get_repository_default_branch(
        self,
        repository_full_name: str,
        installation_id: int,
    ) -> str:
        """Fetch repository metadata and return default branch name."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        url = f"https://api.github.com/repos/{repository_full_name}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        return str(data.get("default_branch", "main"))

    async def get_repository_tree(
        self,
        repository_full_name: str,
        installation_id: int,
        branch: str,
    ) -> list[dict[str, Any]]:
        """Get recursive git tree entries for the branch head."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        url = f"https://api.github.com/repos/{repository_full_name}/git/trees/{branch}?recursive=1"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        tree = data.get("tree", [])
        return tree if isinstance(tree, list) else []

    async def get_file_content(
        self,
        repository_full_name: str,
        installation_id: int,
        path: str,
    ) -> str:
        """Get decoded file content from repository path."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        url = f"https://api.github.com/repos/{repository_full_name}/contents/{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        encoding = str(data.get("encoding", ""))
        content = str(data.get("content", ""))
        if encoding == "base64":
            return base64.b64decode(content).decode("utf-8", errors="ignore")
        return content

    async def upsert_pull_request_comment(
        self,
        repository_full_name: str,
        pr_number: int,
        installation_id: int,
        body: str,
        marker: str,
    ) -> None:
        """Create or update a bot comment identified by a marker tag."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        issue_comments_url = (
            f"https://api.github.com/repos/{repository_full_name}/issues/{pr_number}/comments"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            list_resp = await client.get(issue_comments_url, headers=headers)
            list_resp.raise_for_status()
            comments = list_resp.json()

            existing = None
            if isinstance(comments, list):
                for comment in comments:
                    comment_body = str(comment.get("body", ""))
                    if marker in comment_body:
                        existing = comment
                        break

            formatted_body = f"{marker}\n\n{body}"
            if existing:
                comment_id = existing.get("id")
                update_url = f"https://api.github.com/repos/{repository_full_name}/issues/comments/{comment_id}"
                update_resp = await client.patch(update_url, headers=headers, json={"body": formatted_body})
                update_resp.raise_for_status()
                return

            create_resp = await client.post(issue_comments_url, headers=headers, json={"body": formatted_body})
            create_resp.raise_for_status()

    async def upsert_issue_comment(
        self,
        repository_full_name: str,
        issue_number: int,
        installation_id: int,
        body: str,
        marker: str,
    ) -> None:
        """Create or update a bot comment for an issue thread."""
        await self.upsert_pull_request_comment(
            repository_full_name=repository_full_name,
            pr_number=issue_number,
            installation_id=installation_id,
            body=body,
            marker=marker,
        )

    async def create_or_update_check_run(
        self,
        repository_full_name: str,
        installation_id: int,
        head_sha: str,
        name: str,
        summary: str,
        details_url: str | None = None,
        external_id: str | None = None,
    ) -> None:
        """Create a completed check run for machine-readable review output."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        url = f"https://api.github.com/repos/{repository_full_name}/check-runs"

        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": "success",
            "output": {
                "title": name,
                "summary": summary[:65500],
            },
        }
        if details_url:
            payload["details_url"] = details_url
        if external_id:
            payload["external_id"] = external_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "Unable to create check run repository=%s status=%s body=%s",
                    repository_full_name,
                    response.status_code,
                    response.text[:500],
                )
                return

    async def submit_pull_request_review(
        self,
        repository_full_name: str,
        pr_number: int,
        installation_id: int,
        commit_id: str,
        body: str,
        event: str,
        comments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Submit a PR review with optional inline line comments."""
        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        url = f"https://api.github.com/repos/{repository_full_name}/pulls/{pr_number}/reviews"

        payload: dict[str, Any] = {
            "commit_id": commit_id,
            "body": body,
            "event": event,
        }
        if comments:
            payload["comments"] = comments

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "Unable to submit PR review repository=%s pr=%s event=%s status=%s body=%s",
                    repository_full_name,
                    pr_number,
                    event,
                    response.status_code,
                    response.text[:500],
                )
                return

    async def add_issue_labels(
        self,
        repository_full_name: str,
        issue_number: int,
        installation_id: int,
        labels: list[str],
    ) -> list[str]:
        """Add labels to an issue; creates missing labels when possible."""
        cleaned = [label.strip() for label in labels if label and label.strip()]
        deduped = list(dict.fromkeys(cleaned))
        if not deduped:
            return []

        token = await self.auth.get_installation_token(installation_id)
        headers = self._build_headers(token)
        repo_labels = await self._list_repository_labels(
            repository_full_name=repository_full_name,
            headers=headers,
        )

        missing = [label for label in deduped if label.lower() not in repo_labels]
        if missing:
            await self._create_missing_labels(
                repository_full_name=repository_full_name,
                headers=headers,
                labels=missing,
            )
            repo_labels = await self._list_repository_labels(
                repository_full_name=repository_full_name,
                headers=headers,
            )

        applicable = [label for label in deduped if label.lower() in repo_labels]
        if not applicable:
            return []

        url = f"https://api.github.com/repos/{repository_full_name}/issues/{issue_number}/labels"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json={"labels": applicable})
            response.raise_for_status()
        return applicable

    async def _list_repository_labels(
        self,
        repository_full_name: str,
        headers: dict[str, str],
    ) -> set[str]:
        """List repository labels as a normalized set."""
        url = f"https://api.github.com/repos/{repository_full_name}/labels?per_page=100"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
        labels: set[str] = set()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip().lower()
                    if name:
                        labels.add(name)
        return labels

    async def _create_missing_labels(
        self,
        repository_full_name: str,
        headers: dict[str, str],
        labels: list[str],
    ) -> None:
        """Attempt to create labels that are missing in the repository."""
        url = f"https://api.github.com/repos/{repository_full_name}/labels"
        async with httpx.AsyncClient(timeout=30.0) as client:
            for label in labels:
                payload = {
                    "name": label,
                    "color": self._label_color(label),
                    "description": f"Managed by FOSSMate: {label}",
                }
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code in {201, 422}:
                    continue
                logger.warning(
                    "Unable to create label '%s' for %s status=%s body=%s",
                    label,
                    repository_full_name,
                    response.status_code,
                    response.text[:400],
                )

    @staticmethod
    def _label_color(label: str) -> str:
        palette = {
            "bug": "d73a4a",
            "enhancement": "a2eeef",
            "documentation": "0075ca",
            "good first issue": "7057ff",
            "help wanted": "008672",
            "question": "d876e3",
            "needs triage": "fbca04",
            "dependencies": "0366d6",
            "testing": "5319e7",
            "refactor": "cfd3d7",
        }
        return palette.get(label.lower(), "ededed")

    def _build_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FOSSMate/0.1",
        }
