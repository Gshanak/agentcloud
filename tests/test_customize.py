"""Smoke tests for deploy/customize.py against a fake AutoGPT tree."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy"))

import customize  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Minimal AutoGPT checkout skeleton with the paths customize.py touches."""
    blocks = tmp_path / "autogpt_platform" / "backend" / "backend" / "blocks"
    blocks.mkdir(parents=True)
    (blocks / "_base.py").write_text("# platform base\n")

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

    pyproject = (
        fake_repo / "autogpt_platform" / "backend" / "pyproject.toml"
    ).read_text()
    assert 'autogen-agentchat = "0.4.7"' in pyproject
    assert 'autogen-ext = { extras = ["openai"], version = "^0.4.7" }' in pyproject
    # inserted inside the dependencies section, before other deps
    assert pyproject.index("autogen-agentchat") < pyproject.index("feedparser")

    env = (fake_repo / "autogpt_platform" / ".env").read_text()
    assert "GRAPHITI_FALKORDB_PASSWORD=" in env
    # the empty default was replaced with a generated secret
    password_line = [l for l in env.splitlines() if l.startswith("GRAPHITI_")][0]
    assert len(password_line.split("=", 1)[1]) > 20


def test_customize_is_idempotent(fake_repo):
    customize.main(["--repo", str(fake_repo)])
    pyproject_path = fake_repo / "autogpt_platform" / "backend" / "pyproject.toml"
    before = pyproject_path.read_text()
    env_path = fake_repo / "autogpt_platform" / ".env"
    env_before = env_path.read_text()

    changed = customize.add_autogen_deps(fake_repo)
    assert changed is False
    assert pyproject_path.read_text() == before

    # .env is kept unless --force-env
    created = customize.write_env(fake_repo)
    assert created is False
    assert env_path.read_text() == env_before


def test_customize_rejects_wrong_repo(tmp_path):
    empty = tmp_path / "not-autogpt"
    empty.mkdir()
    with pytest.raises(SystemExit, match="does not exist"):
        customize.copy_blocks(empty)
