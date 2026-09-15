"""Smoke tests for deploy/customize.py against a fake AutoGPT tree."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))

import customize  # noqa: E402

# rest_api.py skeleton with the exact patch-point markers customize.py looks for.
REST_API_SKELETON = """\
import fastapi

from .features.analytics import router as analytics_router
from .features.integrations.router import router as integrations_router

app = fastapi.FastAPI()

app.include_router(backend.api.features.v1.v1_router, tags=["v1"], prefix="/api")
app.include_router(
    integrations_router,
)
"""


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Minimal AutoGPT checkout skeleton with the paths customize.py touches."""
    backend = tmp_path / "autogpt_platform" / "backend" / "backend"
    blocks = backend / "blocks"
    api_features = backend / "api" / "features"
    blocks.mkdir(parents=True)
    api_features.mkdir(parents=True)
    (blocks / "_base.py").write_text("# platform base\n")
    (api_features / "__init__.py").write_text("")

    (backend / "api" / "rest_api.py").write_text(REST_API_SKELETON)

    pyproject = tmp_path / "autogpt_platform" / "backend" / "pyproject.toml"
    pyproject.write_text(
        "[tool.poetry.dependencies]\n"
        'python = ">=3.10,<3.14"\n'
        'anthropic = "^0.79.0"\n'
        'apscheduler = "^3.11.1"\n'
        'autogpt-libs = { path = "../autogpt_libs", develop = true }\n'
        'feedparser = "^6.0.11"\n'
    )

    platform_dir = tmp_path / "autogpt_platform"
    (platform_dir / ".env.default").write_text(
        "APP_ENVIRONMENT=local\nGRAPHITI_FALKORDB_PASSWORD=\n"
    )
    return tmp_path


def test_customize_applies_overlay(fake_repo, capsys):
    rc = customize.main(["--repo", str(fake_repo)])
    assert rc == 0

    blocks = fake_repo / "autogpt_platform" / "backend" / "backend" / "blocks"
    assert (blocks / "autogen_team.py").is_file()
    assert (blocks / "autogen_bridge_block.py").is_file()
    assert (blocks / "news_dedup_block.py").is_file()
    assert (blocks / "briefing_store_block.py").is_file()
    assert (blocks / "_briefing_store.py").is_file()
    assert (blocks / "_block_shim.py").is_file()
    assert (blocks / "_story_store.py").is_file()
    assert (blocks / "story_store_block.py").is_file()

    features = fake_repo / "autogpt_platform" / "backend" / "backend" / "api" / "features"
    assert (features / "briefings" / "routes.py").is_file()
    assert (features / "stories" / "routes.py").is_file()

    rest_api = (
        fake_repo / "autogpt_platform" / "backend" / "backend" / "api" / "rest_api.py"
    ).read_text()
    assert "briefings_router" in rest_api
    assert "stories_router" in rest_api
    assert '/api/briefings' in rest_api
    assert '/api/stories' in rest_api

    pyproject = (
        fake_repo / "autogpt_platform" / "backend" / "pyproject.toml"
    ).read_text()
    assert 'autogen-agentchat = "0.4.7"' in pyproject
    assert 'autogen-ext = { extras = ["openai"], version = "^0.4.7" }' in pyproject
    assert pyproject.index("autogen-agentchat") < pyproject.index("feedparser")

    env = (fake_repo / "autogpt_platform" / ".env").read_text()
    assert "GRAPHITI_FALKORDB_PASSWORD=" in env
    password_line = [l for l in env.splitlines() if l.startswith("GRAPHITI_")][0]
    assert len(password_line.split("=", 1)[1]) > 20
    # GEMINI_API_KEY appended (empty, user fills in)
    assert "GEMINI_API_KEY=" in env


def test_customize_is_idempotent(fake_repo):
    customize.main(["--repo", str(fake_repo)])
    pyproject_path = fake_repo / "autogpt_platform" / "backend" / "pyproject.toml"
    before = pyproject_path.read_text()
    rest_api_path = (
        fake_repo / "autogpt_platform" / "backend" / "backend" / "api" / "rest_api.py"
    )
    rest_before = rest_api_path.read_text()
    env_path = fake_repo / "autogpt_platform" / ".env"
    env_before = env_path.read_text()

    changed = customize.add_autogen_deps(fake_repo)
    assert changed is False
    assert pyproject_path.read_text() == before

    mounted = customize.patch_rest_api(fake_repo)
    assert mounted is False
    assert rest_api_path.read_text() == rest_before

    created = customize.write_env(fake_repo)
    assert created is False
    assert env_path.read_text() == env_before


def test_customize_rejects_wrong_repo(tmp_path):
    empty = tmp_path / "not-autogpt"
    empty.mkdir()
    with pytest.raises(SystemExit, match="does not exist"):
        customize.copy_blocks(empty)
