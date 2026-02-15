"""Generate a concrete GitHub App setup checklist from local environment values."""

from __future__ import annotations

import argparse
from pathlib import Path
import secrets

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env() -> dict[str, str]:
    """Load .env values if available."""
    if not ENV_PATH.exists():
        return {}
    values = dotenv_values(ENV_PATH)
    return {k: v for k, v in values.items() if isinstance(v, str)}


def build_webhook_url(values: dict[str, str]) -> str:
    """Resolve webhook URL from WEBHOOK_PUBLIC_URL or fallback example."""
    configured = values.get("WEBHOOK_PUBLIC_URL", "").strip()
    if configured:
        return configured
    return "https://<your-public-domain>/webhooks/github"


def build_permissions() -> list[str]:
    """Recommended GitHub App permission set for current + near-term scope."""
    return [
        "Repository permissions:",
        "  - Issues: Read & write",
        "  - Pull requests: Read & write",
        "  - Checks: Read & write",
        "  - Contents: Read-only",
        "  - Metadata: Read-only",
        "",
        "Subscribe to events:",
        "  - Issues",
        "  - Issue comment",
        "  - Pull request",
        "  - Pull request review comment",
        "  - Pull request review",
        "  - Installation",
        "  - Installation repositories",
    ]


def mask_secret(secret: str) -> str:
    """Mask secret for terminal safety."""
    if not secret or secret.startswith("<"):
        return secret
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def print_checklist(values: dict[str, str]) -> None:
    """Print setup checklist for GitHub App UI."""
    app_id = values.get("GITHUB_APP_ID", "<set-in-.env>")
    webhook_secret = values.get("GITHUB_WEBHOOK_SECRET", "<set-in-.env>")
    webhook_url = build_webhook_url(values)

    print("\nFOSSMate GitHub App Setup Checklist\n")
    print(f"Project root: {ROOT}")
    print(f"Env file: {ENV_PATH if ENV_PATH.exists() else '.env not found'}")
    print("")

    print("1) General")
    print("   - App name: FOSSMate (or your deployment name)")
    print("   - Homepage URL: your public landing page or repository URL")
    print(f"   - App ID (after creation): {app_id}")
    print("")

    print("2) Webhook")
    print(f"   - Webhook URL: {webhook_url}")
    print(f"   - Webhook secret: {mask_secret(webhook_secret)}")
    print("   - In backend env, GITHUB_WEBHOOK_SECRET must match exactly")
    print("")

    print("3) Permissions and events")
    for line in build_permissions():
        print(f"   {line}")
    print("")

    print("4) Install")
    print("   - Install app to target repositories")
    print("   - For testing, choose 'Only select repositories' first")
    print("")

    print("5) Verify end-to-end")
    print("   - Start backend: cd backend && uvicorn app.main:app --reload --port 8000")
    print("   - Open an issue in installed repo (expect summary + labels)")
    print("   - Comment: 'How can I work on this issue?' (expect onboarding reply)")
    print("   - Open a PR (expect review comment and check-run)")
    print("   - Confirm webhook accepted in API logs and DB")


def update_secret_file(new_secret: str) -> None:
    """Write GITHUB_WEBHOOK_SECRET in .env (create file if missing)."""
    lines: list[str]

    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith("GITHUB_WEBHOOK_SECRET="):
            lines[idx] = f"GITHUB_WEBHOOK_SECRET={new_secret}"
            replaced = True
            break

    if not replaced:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"GITHUB_WEBHOOK_SECRET={new_secret}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate GitHub App setup instructions for FOSSMate."
    )
    parser.add_argument(
        "--print-checklist",
        action="store_true",
        help="Print setup checklist using values from .env.",
    )
    parser.add_argument(
        "--generate-secret",
        action="store_true",
        help="Generate and print a secure webhook secret.",
    )
    parser.add_argument(
        "--write-secret",
        action="store_true",
        help="When used with --generate-secret, write secret to .env.",
    )

    args = parser.parse_args()

    if not args.print_checklist and not args.generate_secret:
        parser.print_help()
        print(
            "\nExample:\n  python scripts/setup_github_app.py --print-checklist",
        )
        return

    values = load_env()

    if args.generate_secret:
        secret = secrets.token_urlsafe(48)
        print(f"Generated webhook secret:\n{secret}\n")
        if args.write_secret:
            update_secret_file(secret)
            print(f"Updated {ENV_PATH} with new GITHUB_WEBHOOK_SECRET.\n")
        else:
            print("Use --write-secret to persist this in .env.\n")

    if args.print_checklist:
        print_checklist(load_env())


if __name__ == "__main__":
    main()
