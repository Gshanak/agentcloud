#!/usr/bin/env python3
"""Apply the agentcloud overlay onto a cloned AutoGPT repository.

Steps (idempotent - safe to re-run):
  1. Copy the custom blocks (AutoGen bridge, news dedup, briefing store and
     their pure helpers) into the platform's blocks directory (auto-discovered
     by the platform's block loader).
  2. Copy the /api/briefings feature into the platform's api/features tree.
  3. Patch rest_api.py to mount the briefings router (import + include_router).
  4. Add autogen-agentchat / autogen-ext to the backend's poetry
     dependencies so the Docker build installs them.
  5. Create autogpt_platform/.env from .env.default, filling the required
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
BLOCK_FILES = (
    "autogen_team.py",
    "autogen_bridge_block.py",
    "_block_shim.py",
    "_briefing_store.py",
    "news_dedup_block.py",
    "briefing_store_block.py",
)
FEATURES_SRC = REPO_ROOT / "platform_overlay" / "backend" / "api" / "features" / "briefings"
FEATURES_DST_REL = Path("autogpt_platform") / "backend" / "backend" / "api" / "features" / "briefings"

# Pinned AutoGen versions - keep in sync with requirements-dev.txt.
AUTOGEN_DEPS = (
    'autogen-agentchat = "0.4.7"',
    'autogen-ext = { extras = ["openai"], version = "^0.4.7" }',
)

# rest_api.py patch points (markers verified against the pinned AutoGPT commit).
ROUTER_IMPORT_MARKER = (
    "from .features.integrations.router import router as integrations_router\n"
)
ROUTER_IMPORT_LINE = (
    "from backend.api.features.briefings.routes import router as briefings_router\n"
)
ROUTER_MOUNT_MARKER = (
    'app.include_router(backend.api.features.v1.v1_router, tags=["v1"], prefix="/api")\n'
)
ROUTER_MOUNT_LINE = (
    'app.include_router(briefings_router, tags=["agentcloud"], prefix="/api/briefings")\n'
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


def copy_briefings_feature(repo: Path) -> list[str]:
    """Copy the /api/briefings feature package into the platform tree."""
    if not FEATURES_SRC.is_dir():
        raise SystemExit(f"Overlay feature missing: {FEATURES_SRC}")
    dest_dir = repo / FEATURES_DST_REL
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(FEATURES_SRC, dest_dir)
    return [
        str((dest_dir / name).relative_to(repo))
        for name in sorted(p.name for p in dest_dir.iterdir())
    ]


def patch_rest_api(repo: Path) -> bool:
    """Mount the briefings router in rest_api.py (idempotent).

    Returns True if the file changed.
    """
    rest_api = (
        repo / "autogpt_platform" / "backend" / "backend" / "api" / "rest_api.py"
    )
    text = rest_api.read_text(encoding="utf-8")

    if "briefings_router" in text:
        return False

    if ROUTER_IMPORT_MARKER not in text or ROUTER_MOUNT_MARKER not in text:
        raise SystemExit(
            "rest_api.py does not match the pinned AutoGPT commit "
            "(patch markers not found); update ROUTER_*_MARKER in customize.py"
        )

    text = text.replace(
        ROUTER_IMPORT_MARKER, ROUTER_IMPORT_MARKER + ROUTER_IMPORT_LINE, 1
    )
    text = text.replace(
        ROUTER_MOUNT_MARKER, ROUTER_MOUNT_MARKER + ROUTER_MOUNT_LINE, 1
    )
    rest_api.write_text(text, encoding="utf-8")
    return True


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

    feature_files = copy_briefings_feature(repo)
    print("Copied briefings feature:")
    for path in feature_files:
        print(f"  {path}")

    mounted = patch_rest_api(repo)
    print(f"rest_api.py briefings router: {'mounted' if mounted else 'already mounted'}")

    changed = add_autogen_deps(repo)
    print(f"pyproject.toml autogen deps: {'added' if changed else 'already present'}")

    created = write_env(repo, force=args.force_env)
    print(f".env: {'created' if created else 'exists (kept)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
