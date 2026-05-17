"""Filesystem checks for data governance planning docs (no network, no secrets)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_PLAN = _REPO_ROOT / "docs" / "data_governance" / "real_data_pilot_plan.md"
_EXPORT_FORMAT = _REPO_ROOT / "docs" / "data_governance" / "real_ticket_export_format.md"
_CALIBRATION_REPORT = _REPO_ROOT / "docs" / "operations" / "real_replay_calibration_report.md"
_README = _REPO_ROOT / "README.md"


def test_real_data_pilot_plan_exists_with_required_sections() -> None:
    text = _PILOT_PLAN.read_text(encoding="utf-8")
    assert "Real Data Pilot Plan" in text
    assert "## 1. Pilot goals" in text
    assert "## 2. Pilot scope" in text
    assert "## 3. Anonymization policy" in text
    assert "## 4. Corpus strategy" in text
    assert "## 5. Evaluation strategy" in text
    assert "Golden Snapshot" in text
    assert "corpus/vendor_ticket_real_pilot" in text
    assert "20–50" in text or "20-50" in text
    assert "not" in text.lower() and "production rollout" in text
    assert "OPENAI_API_KEY" not in text
    assert "postgresql://" not in text


def test_readme_links_real_data_pilot_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/data_governance/real_data_pilot_plan.md" in readme
    assert "docs/data_governance/real_ticket_export_format.md" in readme
    assert "Conversation ticket snapshot" in readme or "conversation_models" in readme


def test_real_ticket_export_format_doc_exists() -> None:
    text = _EXPORT_FORMAT.read_text(encoding="utf-8")
    assert "JSONL" in text
    assert "SELLER_ID_001" in text
    assert "ConversationTicketSnapshot" in text


def test_real_replay_calibration_report_exists() -> None:
    text = _CALIBRATION_REPORT.read_text(encoding="utf-8")
    assert "Real Replay Calibration Report" in text
    assert "## Initial Replay Results (Before Calibration)" in text
    assert "## Replay Results After Calibration" in text
    assert "billing_review=48" in text or "billing_review` | 48" in text
    assert "32" in text and "**0**" in text
    assert "label_vs_department_mismatch" in text
    assert "no real tickets" in text.lower() or "No real tickets" in text
    assert "pgvector" in text.lower()


def test_readme_links_real_replay_calibration() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/real_replay_calibration_report.md" in readme
    assert "Real Replay Calibration" in readme
    assert "normalize_ticket_export.py" in readme
    assert "replay_ticket_export.py" in readme
    assert "32" in readme and "0" in readme
