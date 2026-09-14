#!/usr/bin/env python3
"""Apply the android-ai-agents overlay onto a cloned AutoGPT repository.

Steps (idempotent - safe to re-run):
  1. Copy the AutoGen bridge block and team factory into the platform's
     blocks directory (auto-discovered by the platform's block loader).
  2. Add autogen-agentchat / autogen-ext to the backend's poetry
     dependencies so the Docker build installs them.
  3. Create autogpt_platform/.env from .env.default, filling the required
     GRAPHITI_FALKORDB_PASSWORD with a generated secret if unset.

Usage:
    python3 deploy/customize.py --repo /path/to/AutoGPT [--force-env]
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_BLOCKS = REPO_ROOT / "platform_overlay" / "backend" / "blocks"
BLOCK_FILES = ("autogen_team.py", "autogen_bridge_block.py")

# Pinned AutoGen versions - keep in sync with requirements-dev.txt.
AUTOGEN_DEPS = (
    'autogen-agentchat = "0.4.7"',
    'autogen-ext = { extras = ["openai"], version = "^0.4.7" }',
)


def copy_blocks(repo: Path) -> list[str]:
    """Copy the overlay block files into the platform tree."""
    dest_dir = repo / "autogpt_platform" / "backend" / "backend" / "blocks"
    if not dest_dir.is_dir():
        raise SystemExit(f"Not an AutoGPT checkout: {dest_dir} does not exist")

    copied = []
    for name in BLOCK_FILES:
        src = OVERLAY_BLOCKS / name
        if not src.is_file():
            raise SystemExit(f"Overlay file missing: {src}")
        dest = dest_dir / name
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(repo)))
    return copied


def add_autogen_deps(repo: Path) -> bool:
    """Insert the AutoGen dependencies into backend/pyproject.toml.

    Returns True if the file changed, False if they were already present.
    """
    pyproject = repo / "autogpt_platform" / "backend" / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    if "autogen-agentchat" in text:
        return False

    marker = "[tool.poetry.dependencies]\n"
    idx = text.find(marker)
    if idx == -1:
        raise SystemExit("Could not find [tool.poetry.dependencies] section")
    insertion = "\n".join(AUTOGEN_DEPS) + "\n"
    text = text[: idx + len(marker)] + insertion + text[idx + len(marker) :]
    pyproject.write_text(text, encoding="utf-8")
    return True


def write_env(repo: Path, force: bool = False) -> bool:
    """Create autogpt_platform/.env from .env.default with secrets filled in.

    Returns True if .env was (re)created.
    """
    platform_dir = repo / "autogpt_platform"
    env_default = platform_dir / ".env.default"
    env_path = platform_dir / ".env"

    if env_path.exists() and not force:
        return False
    if not env_default.is_file():
        raise SystemExit(f"Missing {env_default}")

    lines = []
    for line in env_default.read_text(encoding="utf-8").splitlines():
        if line.startswith("GRAPHITI_FALKORDB_PASSWORD="):
            value = line.split("=", 1)[1].strip()
            if not value:
                value = secrets.token_urlsafe(24)
            line = f"GRAPHITI_FALKORDB_PASSWORD={value}"
        lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the AutoGPT checkout")
    parser.add_argument(
        "--force-env",
        action="store_true",
        help="Recreate .env even if it exists (regenerates the FalkorDB password)",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise SystemExit(f"No such directory: {repo}")

    copied = copy_blocks(repo)
    print("Copied blocks:")
    for path in copied:
        print(f"  {path}")

    changed = add_autogen_deps(repo)
    print(f"pyproject.toml autogen deps: {'added' if changed else 'already present'}")

    created = write_env(repo, force=args.force_env)
    print(f".env: {'created' if created else 'exists (kept)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
