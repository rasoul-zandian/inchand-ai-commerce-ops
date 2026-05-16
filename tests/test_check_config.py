"""Tests for offline local configuration validation (scripts/check_config.py)."""

from __future__ import annotations

import pytest
from app.config import AppSettings
from pydantic import ValidationError
from scripts.check_config import (
    _SECRET_FIELD_NAMES,
    build_safe_config_lines,
    format_rag_profile,
    run_config_check,
)


def test_format_rag_profile_none() -> None:
    assert format_rag_profile(None) == "<none>"


def test_format_rag_profile_value() -> None:
    assert format_rag_profile("semantic_local") == "semantic_local"


def test_build_safe_config_lines_never_includes_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_secret")
    monkeypatch.setenv("RAG_PROFILE", "mock")
    settings = AppSettings()
    lines = build_safe_config_lines(settings)
    joined = "\n".join(lines)
    assert "sk-test" not in joined
    assert "lsv2_test" not in joined
    for name in _SECRET_FIELD_NAMES:
        assert name not in joined
    assert "rag_profile=mock" in joined


def test_run_config_check_passes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("RAG_STRATEGY", "mock")
    monkeypatch.delenv("RAG_PROFILE", raising=False)
    assert run_config_check() == 0
    out = capsys.readouterr().out
    assert "config check: passed" in out
    assert "rag_profile=<none>" in out
    assert "llm_provider=mock" in out


def test_run_config_check_invalid_profile_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RAG_PROFILE", "pinecone")
    assert run_config_check() == 1
    captured = capsys.readouterr()
    assert "config check: failed" in captured.err
    assert "Invalid RAG_PROFILE" in captured.err
    assert "sk-" not in captured.out + captured.err


def test_run_config_check_does_not_print_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("RAG_PROFILE", "semantic_local")
    assert run_config_check() == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "sk-super-secret" not in combined
    assert "openai_api_key" not in combined


def test_app_settings_validation_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PROFILE", "not-a-profile")
    with pytest.raises(ValidationError, match="Invalid RAG_PROFILE"):
        AppSettings()
