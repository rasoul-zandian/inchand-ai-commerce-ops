"""Offline tests for smoke shell script config preflight (no curl to real server)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEMANTIC_SCRIPT = _REPO_ROOT / "scripts" / "smoke_semantic_rag_vendor_ticket.sh"
_OPENAI_SCRIPT = _REPO_ROOT / "scripts" / "smoke_openai_vendor_ticket.sh"


def _run_smoke_script(
    script: Path,
    *,
    env: dict[str, str] | None = None,
    fake_curl_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    run_env.update(
        {
            "LLM_PROVIDER": "mock",
            "EMBEDDING_PROVIDER": "mock",
            "EMBEDDING_MODEL": "mock-embedding-small",
        }
    )
    if env:
        run_env.update(env)
    if fake_curl_dir is not None:
        run_env["PATH"] = f"{fake_curl_dir}{os.pathsep}{run_env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(script)],
        cwd=_REPO_ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_stub_curl(directory: Path) -> None:
    stub = directory / "curl"
    stub.write_text(
        '#!/usr/bin/env bash\necho "CURL_INVOKED" >&2\nexit 99\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)


@pytest.mark.parametrize("script", [_SEMANTIC_SCRIPT, _OPENAI_SCRIPT])
def test_smoke_script_exits_nonzero_when_config_invalid(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_PROFILE", raising=False)
    _write_stub_curl(tmp_path)
    result = _run_smoke_script(
        script,
        env={"RAG_PROFILE": "pinecone", "RAG_STRATEGY": "semantic", "OPENAI_API_KEY": "sk-test"},
        fake_curl_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "config preflight failed" in result.stderr or "config check: failed" in result.stderr
    assert "CURL_INVOKED" not in result.stderr + result.stdout


def test_semantic_smoke_reaches_curl_after_preflight(tmp_path: Path) -> None:
    _write_stub_curl(tmp_path)
    result = _run_smoke_script(
        _SEMANTIC_SCRIPT,
        env={"RAG_STRATEGY": "semantic", "RAG_PROFILE": "semantic_local"},
        fake_curl_dir=tmp_path,
    )
    assert "config preflight passed" in result.stdout
    assert "CURL_INVOKED" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="bash smoke scripts require Unix shell")
def test_openai_smoke_requires_api_key_after_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing OPENAI_API_KEY must fail after preflight and before curl (no env leakage)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _write_stub_curl(tmp_path)
    result = _run_smoke_script(
        _OPENAI_SCRIPT,
        env={"RAG_STRATEGY": "mock", "OPENAI_API_KEY": ""},
        fake_curl_dir=tmp_path,
    )
    assert result.returncode != 0
    assert "config preflight passed" in result.stdout
    assert "OPENAI_API_KEY is not set" in result.stderr
    assert "CURL_INVOKED" not in result.stderr
    assert "sk-" not in result.stdout + result.stderr
