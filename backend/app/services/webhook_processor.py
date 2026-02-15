"""Webhook processing worker logic."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.database import (
    DeliveryLog,
    DeveloperMetric,
    InstallationSetting,
    ReviewFinding,
    ReviewRun,
    ScoreCardModel,
)
from app.models.schemas import NormalizedEvent, NotificationPayload
from app.services.github_service import GitHubService
from app.services.notification_service import NotificationService
from app.services.review_service import ReviewService

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """Process normalized events from queue and persist review artifacts."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        github_service: GitHubService,
        review_service: ReviewService,
        notification_service: NotificationService,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.github_service = github_service
        self.review_service = review_service
        self.notification_service = notification_service

    async def process_delivery_log(self, payload: dict) -> None:
        """Queue handler entrypoint."""
        delivery_log_id = int(payload["delivery_log_id"])
        async with self.session_factory() as session:
            delivery_log = await session.get(DeliveryLog, delivery_log_id)
            if delivery_log is None:
                logger.warning("Delivery log %s missing", delivery_log_id)
                return

            if delivery_log.status == "done":
                return

            delivery_log.status = "processing"
            delivery_log.error_message = None
            await session.commit()

        try:
            async with self.session_factory() as session:
                await self._process(session, delivery_log_id)
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.exception("Delivery processing failed id=%s", delivery_log_id)
            async with self.session_factory() as session:
                failed = await session.get(DeliveryLog, delivery_log_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error_message = str(exc)
                    await session.commit()

    async def _process(self, session: AsyncSession, delivery_log_id: int) -> None:
        delivery_log = await session.get(DeliveryLog, delivery_log_id)
        if delivery_log is None:
            return

        normalized = NormalizedEvent.model_validate(delivery_log.normalized_event)
        installation_flags = await self._get_feature_flags(session, normalized.installation_id)

        if normalized.platform == "github":
            await self._process_github_event(session, delivery_log, normalized, installation_flags)
        elif normalized.platform == "gitlab":
            await self._process_gitlab_event(session, delivery_log, normalized)
        else:
            logger.info("Unknown platform '%s' for delivery_log=%s", normalized.platform, delivery_log.id)

        delivery_log.status = "done"
        await session.commit()

    async def _process_github_event(
        self,
        session: AsyncSession,
        delivery_log: DeliveryLog,
        event: NormalizedEvent,
        feature_flags: dict[str, bool],
    ) -> None:
        if event.event_type == "pull_request" and event.action in {"opened", "synchronize"}:
            if event.action == "synchronize" and not feature_flags.get("commit_trigger", True):
                return
            if not event.repository_full_name or event.pr_number is None:
                await self._record_non_pr_run(
                    session=session,
                    delivery_log_id=delivery_log.id,
                    event=event,
                    run_type="pull_request_skipped",
                    status="done",
                    result_json={"reason": "missing repository/pr metadata"},
                )
                return
            await self._run_pull_request_review(session, delivery_log, event, feature_flags)
            return

        if event.event_type == "issues" and event.action == "opened":
            summary = await self.review_service.summarize_issue(event)
            suggested_labels = await self.review_service.suggest_issue_labels(event)
            applied_labels: list[str] = []
            label_error: str | None = None

            if event.installation_id and event.repository_full_name and event.issue_number:
                try:
                    applied_labels = await self.github_service.add_issue_labels(
                        repository_full_name=event.repository_full_name,
                        issue_number=event.issue_number,
                        installation_id=event.installation_id,
                        labels=suggested_labels,
                    )
                except Exception as exc:
                    label_error = str(exc)
                    logger.exception(
                        "Failed applying issue labels for %s#%s",
                        event.repository_full_name,
                        event.issue_number,
                    )

            summary_with_labels = summary
            if suggested_labels:
                labels_preview = ", ".join(f"`{label}`" for label in suggested_labels)
                summary_with_labels = f"{summary}\n\nSuggested labels: {labels_preview}"

            await self._record_non_pr_run(
                session=session,
                delivery_log_id=delivery_log.id,
                event=event,
                run_type="issue_summary",
                status="done",
                result_json={
                    "summary": summary,
                    "suggested_labels": suggested_labels,
                    "applied_labels": applied_labels,
                    "label_error": label_error,
                },
            )
            if event.installation_id and event.repository_full_name and event.issue_number:
                marker = "<!-- fossmate:issue-summary -->"
                try:
                    await self.github_service.upsert_issue_comment(
                        repository_full_name=event.repository_full_name,
                        issue_number=event.issue_number,
                        installation_id=event.installation_id,
                        body=summary_with_labels,
                        marker=marker,
                    )
                except Exception:
                    logger.exception(
                        "Failed posting issue summary for %s#%s",
                        event.repository_full_name,
                        event.issue_number,
                    )
            return

        if event.event_type in {"issue_comment", "pull_request_review_comment"} and event.action in {
            "created",
            "edited",
        }:
            if not feature_flags.get("comment_auto_reply", True):
                return
            await self._process_comment_reply(session, delivery_log, event, feature_flags)
            return

        if event.event_type == "pull_request_review" and event.action in {"submitted", "edited"}:
            if not feature_flags.get("comment_auto_reply", True):
                return
            await self._process_pull_request_review_reply(session, delivery_log, event, feature_flags)
            return

    async def _process_gitlab_event(
        self,
        session: AsyncSession,
        delivery_log: DeliveryLog,
        event: NormalizedEvent,
    ) -> None:
        await self._record_non_pr_run(
            session=session,
            delivery_log_id=delivery_log.id,
            event=event,
            run_type="gitlab_event_received",
            status="done",
            result_json={"message": "GitLab processing pipeline placeholder accepted event."},
        )

    async def _process_comment_reply(
        self,
        session: AsyncSession,
        delivery_log: DeliveryLog,
        event: NormalizedEvent,
        feature_flags: dict[str, bool],
    ) -> None:
        comment = event.payload.get("comment", {})
        sender = event.payload.get("sender", {})
        comment_text = str(comment.get("body", "")).strip()
        comment_id = comment.get("id")
        sender_login = str(sender.get("login", "")).strip()
        sender_type = str(sender.get("type", "")).strip().lower()

        if not comment_text:
            return
        if sender_type == "bot" or sender_login.endswith("[bot]"):
            return
        if "<!-- fossmate:" in comment_text.lower():
            return

        assistant_handle = self.settings.assistant_handle
        reply_all_comments = feature_flags.get("comment_reply_all", True)
        should_reply = reply_all_comments or self.review_service.is_assistant_mention(
            comment_text=comment_text,
            assistant_handle=assistant_handle,
        )
        if not should_reply:
            return

        target_issue_number = event.issue_number or event.pr_number
        if not event.installation_id or not event.repository_full_name or not target_issue_number:
            return

        if self.review_service.is_onboarding_request(comment_text):
            reply = await self.review_service.onboarding_reply(event)
            run_type = "issue_onboarding"
            marker_prefix = "onboarding"
        else:
            reply = await self.review_service.answer_issue_comment(
                event=event,
                comment_text=comment_text,
                assistant_handle=assistant_handle,
            )
            run_type = "comment_assistant"
            marker_prefix = "comment-assistant"

        marker = (
            f"<!-- fossmate:{marker_prefix}:{comment_id} -->"
            if comment_id
            else f"<!-- fossmate:{marker_prefix} -->"
        )

        await self._record_non_pr_run(
            session=session,
            delivery_log_id=delivery_log.id,
            event=event,
            run_type=run_type,
            status="done",
            result_json={
                "reply": reply,
                "source_comment_id": comment_id,
                "sender_login": sender_login,
                "reply_all_comments": reply_all_comments,
                "assistant_handle": assistant_handle,
            },
        )

        try:
            await self.github_service.upsert_issue_comment(
                repository_full_name=event.repository_full_name,
                issue_number=target_issue_number,
                installation_id=event.installation_id,
                body=reply,
                marker=marker,
            )
        except Exception:
            logger.exception(
                "Failed posting automated comment reply for %s#%s (event=%s)",
                event.repository_full_name,
                target_issue_number,
                event.event_type,
            )

    async def _run_pull_request_review(
        self,
        session: AsyncSession,
        delivery_log: DeliveryLog,
        event: NormalizedEvent,
        feature_flags: dict[str, bool],
    ) -> None:
        started = time.perf_counter()
        run = ReviewRun(
            delivery_log_id=delivery_log.id,
            installation_id=event.installation_id,
            platform=event.platform,
            run_type="pull_request_review",
            status="processing",
            provider=self.review_service.llm_provider.provider_name,
            model_name=self.review_service.llm_provider.model_name,
            repository_full_name=event.repository_full_name,
            pr_number=event.pr_number,
            actor_login=event.sender_login,
            result_json={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        result = await self.review_service.build_pr_review(event)
        if not feature_flags.get("pr_summary", True):
            result.pr_summary = "PR summary feature is disabled for this installation."
        if not feature_flags.get("file_summary", True):
            result.file_summaries = []
        if not feature_flags.get("review_suggestions", True):
            result.suggestions = []
        if not feature_flags.get("scoring", True):
            result.score_card.correctness = 0.0
            result.score_card.readability = 0.0
            result.score_card.maintainability = 0.0
            result.score_card.overall = 0.0
        run.status = "done"
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.result_json = result.model_dump(mode="json")

        for suggestion in result.suggestions:
            session.add(
                ReviewFinding(
                    review_run_id=run.id,
                    file_path=suggestion.file_path,
                    title=suggestion.title,
                    details=suggestion.details,
                    severity=suggestion.severity,
                )
            )

        session.add(
            ScoreCardModel(
                review_run_id=run.id,
                correctness=result.score_card.correctness,
                readability=result.score_card.readability,
                maintainability=result.score_card.maintainability,
                overall=result.score_card.overall,
                advisory_only=result.score_card.advisory_only,
            )
        )

        if event.sender_login:
            session.add(
                DeveloperMetric(
                    installation_id=event.installation_id,
                    platform=event.platform,
                    repository_full_name=event.repository_full_name,
                    developer_login=event.sender_login,
                    review_run_id=run.id,
                    correctness=result.score_card.correctness,
                    readability=result.score_card.readability,
                    maintainability=result.score_card.maintainability,
                    overall=result.score_card.overall,
                    measured_at=datetime.now(tz=timezone.utc),
                )
            )

        await session.commit()

        comment_body = self._format_pr_comment(result)
        check_summary = self._format_check_run_summary(result)

        if event.installation_id and event.repository_full_name and event.pr_number:
            try:
                await self.github_service.upsert_pull_request_comment(
                    repository_full_name=event.repository_full_name,
                    pr_number=event.pr_number,
                    installation_id=event.installation_id,
                    body=comment_body,
                    marker="<!-- fossmate:pr-review -->",
                )
            except Exception:
                logger.exception(
                    "Failed posting PR review comment for %s#%s",
                    event.repository_full_name,
                    event.pr_number,
                )

            if event.head_sha:
                review_event = self._review_event_for_result(result)
                review_body = self._format_inline_review_body(result, review_event)
                inline_comments: list[dict[str, str | int]] = []
                try:
                    pr_files = await self.github_service.list_pull_request_files(
                        repository_full_name=event.repository_full_name,
                        pr_number=event.pr_number,
                        installation_id=event.installation_id,
                    )
                    inline_comments = self._build_inline_review_comments(pr_files, result)
                except Exception:
                    logger.exception(
                        "Failed preparing inline PR review comments for %s#%s",
                        event.repository_full_name,
                        event.pr_number,
                    )
                try:
                    await self.github_service.submit_pull_request_review(
                        repository_full_name=event.repository_full_name,
                        pr_number=event.pr_number,
                        installation_id=event.installation_id,
                        commit_id=event.head_sha,
                        body=review_body,
                        event=review_event,
                        comments=inline_comments,
                    )
                except Exception:
                    logger.exception(
                        "Failed submitting PR review for %s#%s",
                        event.repository_full_name,
                        event.pr_number,
                    )

            if event.head_sha:
                try:
                    await self.github_service.create_or_update_check_run(
                        repository_full_name=event.repository_full_name,
                        installation_id=event.installation_id,
                        head_sha=event.head_sha,
                        name="FOSSMate Review",
                        summary=check_summary,
                        external_id=str(run.id),
                    )
                except Exception:
                    logger.exception(
                        "Failed creating check run for %s#%s",
                        event.repository_full_name,
                        event.pr_number,
                    )

        if feature_flags.get("email_reports"):
            payload = NotificationPayload(
                subject=f"FOSSMate Review: {event.repository_full_name}#{event.pr_number}",
                body_text=check_summary,
                recipients=[],
            )
            await self.notification_service.send_review_notification(payload)

    async def _record_non_pr_run(
        self,
        session: AsyncSession,
        delivery_log_id: int,
        event: NormalizedEvent,
        run_type: str,
        status: str,
        result_json: dict,
    ) -> None:
        session.add(
            ReviewRun(
                delivery_log_id=delivery_log_id,
                installation_id=event.installation_id,
                platform=event.platform,
                run_type=run_type,
                status=status,
                provider=self.review_service.llm_provider.provider_name,
                model_name=self.review_service.llm_provider.model_name,
                repository_full_name=event.repository_full_name,
                issue_number=event.issue_number,
                actor_login=event.sender_login,
                result_json=result_json,
            )
        )
        await session.commit()

    async def _get_feature_flags(
        self,
        session: AsyncSession,
        installation_id: int | None,
    ) -> dict[str, bool]:
        defaults = self.settings.default_feature_flags
        if installation_id is None:
            return defaults

        query = select(InstallationSetting).where(InstallationSetting.installation_id == installation_id)
        setting = (await session.execute(query)).scalars().first()
        if setting is None:
            setting = InstallationSetting(
                installation_id=installation_id,
                locale="en",
                feature_flags_json=defaults,
                provider_config_json={
                    "provider": self.settings.llm_provider,
                    "model": self.settings.llm_model_name,
                },
            )
            session.add(setting)
            await session.commit()
            return defaults

        merged = defaults.copy()
        for key, value in (setting.feature_flags_json or {}).items():
            merged[key] = bool(value)
        return merged

    @staticmethod
    def _format_pr_comment(result) -> str:
        summary_lines = [
            "### FOSSMate Automated Review",
            "",
            f"**Category**: `{result.category}`",
            f"**Score (advisory)**: `{result.score_card.overall}/10`",
            "",
            "#### Summary",
            result.pr_summary,
            "",
            "#### Major Files",
        ]
        if result.major_files:
            summary_lines.extend([f"- `{path}`" for path in result.major_files])
        else:
            summary_lines.append("- No file details available.")

        summary_lines.extend(["", "#### Suggestions (Experimental)"])
        if result.suggestions:
            for suggestion in result.suggestions:
                target = f" ({suggestion.file_path})" if suggestion.file_path else ""
                summary_lines.append(
                    f"- **{suggestion.title}**{target}: {suggestion.details} "
                    f"`[{suggestion.severity}]`"
                )
        else:
            summary_lines.append("- No suggestions generated.")

        return "\n".join(summary_lines)

    @staticmethod
    def _format_check_run_summary(result) -> str:
        file_count = len(result.file_summaries)
        return (
            f"Category: {result.category}\n"
            f"Overall score: {result.score_card.overall}/10 (advisory)\n"
            f"Files summarized: {file_count}\n"
            f"Suggestions: {len(result.suggestions)}"
        )

    @staticmethod
    def _review_event_for_result(result) -> str:
        has_high_suggestion = any(s.severity == "high" for s in result.suggestions)
        has_high_risk_file = any(f.risk == "high" for f in result.file_summaries)
        if result.score_card.overall <= 6.4 or has_high_suggestion or has_high_risk_file:
            return "REQUEST_CHANGES"
        return "COMMENT"

    @staticmethod
    def _format_inline_review_body(result, review_event: str) -> str:
        marker = "<!-- fossmate:pr-inline-review -->"
        title = "Requesting changes" if review_event == "REQUEST_CHANGES" else "Review notes"
        return (
            f"{marker}\n\n"
            f"### FOSSMate {title}\n"
            f"Category: `{result.category}`\n"
            f"Advisory score: `{result.score_card.overall}/10`\n"
            "Inline comments below highlight concrete review points."
        )

    def _build_inline_review_comments(
        self,
        pr_files: list[dict[str, object]],
        result,
    ) -> list[dict[str, str | int]]:
        comments: list[dict[str, str | int]] = []
        file_index = {
            str(item.get("filename")): item
            for item in pr_files
            if isinstance(item, dict) and item.get("filename")
        }

        used_paths: set[str] = set()

        for suggestion in result.suggestions:
            path = (suggestion.file_path or "").strip()
            if not path or path in used_paths:
                continue
            file_obj = file_index.get(path)
            if not file_obj:
                continue
            line = self._first_addition_line(str(file_obj.get("patch", "")))
            if line is None:
                continue
            comments.append(
                {
                    "path": path,
                    "line": line,
                    "side": "RIGHT",
                    "body": f"{suggestion.title}: {suggestion.details}",
                }
            )
            used_paths.add(path)
            if len(comments) >= 6:
                return comments

        for file_summary in result.file_summaries:
            if file_summary.risk == "low":
                continue
            path = file_summary.path
            if not path or path in used_paths:
                continue
            file_obj = file_index.get(path)
            if not file_obj:
                continue
            line = self._first_addition_line(str(file_obj.get("patch", "")))
            if line is None:
                continue
            comments.append(
                {
                    "path": path,
                    "line": line,
                    "side": "RIGHT",
                    "body": (
                        f"Risk flagged as {file_summary.risk}. "
                        "Please validate edge cases, tests, and error handling for this change."
                    ),
                }
            )
            used_paths.add(path)
            if len(comments) >= 6:
                return comments

        return comments

    @staticmethod
    def _first_addition_line(patch: str) -> int | None:
        if not patch:
            return None

        new_line = 0
        for raw_line in patch.splitlines():
            if raw_line.startswith("@@"):
                match = re.search(r"\+(\d+)(?:,\d+)?", raw_line)
                if not match:
                    continue
                new_line = int(match.group(1))
                continue
            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                return new_line
            if raw_line.startswith(" "):
                new_line += 1
                continue
            if raw_line.startswith("-") and not raw_line.startswith("---"):
                continue
        return None

    async def _process_pull_request_review_reply(
        self,
        session: AsyncSession,
        delivery_log: DeliveryLog,
        event: NormalizedEvent,
        feature_flags: dict[str, bool],
    ) -> None:
        review = event.payload.get("review", {})
        sender = event.payload.get("sender", {})
        review_body = str(review.get("body", "")).strip()
        review_id = review.get("id")
        sender_login = str(sender.get("login", "")).strip()
        sender_type = str(sender.get("type", "")).strip().lower()

        if not review_body:
            return
        if sender_type == "bot" or sender_login.endswith("[bot]"):
            return
        if "<!-- fossmate:" in review_body.lower():
            return

        assistant_handle = self.settings.assistant_handle
        reply_all_comments = feature_flags.get("comment_reply_all", True)
        should_reply = reply_all_comments or self.review_service.is_assistant_mention(
            comment_text=review_body,
            assistant_handle=assistant_handle,
        )
        if not should_reply:
            return

        target_issue_number = event.pr_number or event.issue_number
        if not event.installation_id or not event.repository_full_name or not target_issue_number:
            return

        reply = await self.review_service.answer_issue_comment(
            event=event,
            comment_text=review_body,
            assistant_handle=assistant_handle,
        )
        marker = (
            f"<!-- fossmate:review-reply:{review_id} -->"
            if review_id
            else "<!-- fossmate:review-reply -->"
        )

        await self._record_non_pr_run(
            session=session,
            delivery_log_id=delivery_log.id,
            event=event,
            run_type="pr_review_assistant",
            status="done",
            result_json={
                "reply": reply,
                "source_review_id": review_id,
                "sender_login": sender_login,
                "reply_all_comments": reply_all_comments,
                "assistant_handle": assistant_handle,
            },
        )

        try:
            await self.github_service.upsert_issue_comment(
                repository_full_name=event.repository_full_name,
                issue_number=target_issue_number,
                installation_id=event.installation_id,
                body=reply,
                marker=marker,
            )
        except Exception:
            logger.exception(
                "Failed posting automated review-body reply for %s#%s",
                event.repository_full_name,
                target_issue_number,
            )
