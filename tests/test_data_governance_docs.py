"""Filesystem checks for data governance planning docs (no network, no secrets)."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_PLAN = _REPO_ROOT / "docs" / "data_governance" / "real_data_pilot_plan.md"
_EXPORT_FORMAT = _REPO_ROOT / "docs" / "data_governance" / "real_ticket_export_format.md"
_CALIBRATION_REPORT = _REPO_ROOT / "docs" / "operations" / "real_replay_calibration_report.md"
_BASELINE_50 = _REPO_ROOT / "docs" / "operations" / "real_replay_50_ticket_baseline.md"
_LARGER_REPLAY_PLAN = _REPO_ROOT / "docs" / "operations" / "larger_replay_batch_plan.md"
_LARGER_REPLAY_166_REPORT = (
    _REPO_ROOT / "docs" / "operations" / "larger_replay_166_ticket_execution_report.md"
)
_PILOT_CORPUS_PLANNING = _REPO_ROOT / "docs" / "operations" / "pilot_corpus_planning.md"
_PRIVACY_REVIEW_166_REPORT = (
    _REPO_ROOT / "docs" / "operations" / "privacy_review_166_ticket_execution_report.md"
)
_REDACTED_REPLAY_166_REPORT = (
    _REPO_ROOT / "docs" / "operations" / "redacted_replay_166_ticket_execution_report.md"
)
_REVIEWER_SIGNOFF_DOC = _REPO_ROOT / "docs" / "operations" / "reviewer_signoff_workflow.md"
_PILOT_CORPUS_REPO_POLICY = _REPO_ROOT / "docs" / "operations" / "pilot_corpus_repository_policy.md"
_PILOT_CORPUS_25_REPORT = _REPO_ROOT / "docs" / "operations" / "pilot_corpus_25_build_report.md"
_GITIGNORE = _REPO_ROOT / ".gitignore"
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
    assert "build_replay_metrics_dashboard.py" in readme
    assert "32" in readme and "0" in readme


def test_calibration_report_mentions_dashboard_builder() -> None:
    text = _CALIBRATION_REPORT.read_text(encoding="utf-8")
    assert "build_replay_metrics_dashboard.py" in text
    assert "metrics dashboard" in text.lower()
    assert "real_replay_50_ticket_baseline.md" in text


def test_50_ticket_baseline_doc_exists() -> None:
    text = _BASELINE_50.read_text(encoding="utf-8")
    assert "50-Ticket Real Replay Baseline" in text
    assert "mismatch_count" in text.lower() or "mismatch_count` | **0**" in text
    assert "qa_attention_count" in text
    assert "13" in text
    assert "no raw ticket text" in text.lower() or "No raw ticket text" in text
    assert "pgvector" in text.lower()
    assert "not" in text.lower() and "corpus" in text.lower()
    assert "Conversation transcript" not in text
    assert "sk-" not in text


def test_readme_links_50_ticket_baseline() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/real_replay_50_ticket_baseline.md" in readme
    assert "mismatch 0" in readme.lower()
    assert "13/50" in readme or "13" in readme


def test_larger_replay_batch_plan_exists() -> None:
    text = _LARGER_REPLAY_PLAN.read_text(encoding="utf-8")
    assert "Larger Replay Batch Plan" in text
    assert "100" in text and "500" in text
    assert "normalize_ticket_export.py" in text
    assert "validate_ticket_export.py" in text
    assert "replay_ticket_export.py" in text
    assert "build_replay_metrics_dashboard.py" in text
    assert "50-ticket" in text.lower() or "50 ticket" in text.lower()
    assert "pgvector" in text.lower()
    assert "not" in text.lower() and "corpus" in text.lower()
    assert "embeddings" in text.lower() or "embedding" in text.lower()


def test_readme_links_larger_replay_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/larger_replay_batch_plan.md" in readme
    assert "100" in readme and "500" in readme


def test_baseline_links_larger_replay_plan() -> None:
    text = _BASELINE_50.read_text(encoding="utf-8")
    assert "larger_replay_batch_plan.md" in text


def test_larger_replay_166_execution_report_exists() -> None:
    text = _LARGER_REPLAY_166_REPORT.read_text(encoding="utf-8")
    assert "166-Ticket Larger Replay Execution Report" in text
    assert "166" in text
    assert "qa_attention_count" in text or "QA attention" in text
    assert "51" in text
    assert "mismatch" in text.lower() and "0" in text
    assert "suspicious" in text.lower() and "card_like" in text or "iban_like" in text
    assert "pgvector" in text.lower()
    assert "not" in text.lower() and "corpus" in text.lower()
    assert "no raw ticket text" in text.lower() or "No raw ticket text" in text
    assert "Conversation transcript" not in text


def test_readme_links_larger_replay_166_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/larger_replay_166_ticket_execution_report.md" in readme
    assert "166" in readme
    assert "51/166" in readme or "51" in readme


def test_larger_replay_plan_links_166_report() -> None:
    text = _LARGER_REPLAY_PLAN.read_text(encoding="utf-8")
    assert "larger_replay_166_ticket_execution_report.md" in text


def test_baseline_links_166_execution_report() -> None:
    text = _BASELINE_50.read_text(encoding="utf-8")
    assert "larger_replay_166_ticket_execution_report.md" in text
    assert "30.7" in text or "30.7%" in text


def test_readme_documents_privacy_review_workflow() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "build_privacy_review_report.py" in readme
    assert "app/privacy_review" in readme
    assert "residual" in readme.lower() or "privacy review" in readme.lower()


def test_readme_documents_pii_redaction() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "redact_ticket_export.py" in readme
    assert "does not replace" in readme.lower() or "not replace" in readme.lower()
    assert "embeddings" in readme.lower()


def test_readme_redact_first_before_validate_and_privacy_review() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "normalize → redact → validate" in readme or "normalize → redact" in readme
    assert "residual" in readme.lower()
    redact_pos = readme.find("redact_ticket_export.py")
    validate_pos = readme.find("validate_ticket_export.py", redact_pos)
    privacy_pos = readme.find("build_privacy_review_report.py", redact_pos)
    assert redact_pos != -1 and validate_pos != -1 and privacy_pos != -1
    assert redact_pos < validate_pos < privacy_pos


def test_pilot_corpus_planning_uses_redacted_jsonl_for_builder() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert ".redacted.jsonl" in text
    assert "build_pilot_corpus.py" in text
    assert "residual" in text.lower()
    assert "Do not" in text or "do not" in text.lower()
    assert "normalized.jsonl" not in text.split("build_pilot_corpus.py")[1].split("```")[1]


def test_privacy_review_166_documents_residual_warnings() -> None:
    text = _PRIVACY_REVIEW_166_REPORT.read_text(encoding="utf-8")
    assert "residual" in text.lower()
    assert "redact" in text.lower()
    assert "redacted.jsonl" in text
    assert "Pre-redaction" in text or "pre-redaction" in text.lower()


def test_redacted_replay_166_execution_report_exists() -> None:
    text = _REDACTED_REPLAY_166_REPORT.read_text(encoding="utf-8")
    assert "Redacted Replay Execution Report" in text
    assert "redact" in text.lower() and "first" in text.lower()
    assert "residual" in text.lower()
    assert "0" in text
    assert "reviewer sign-off" in text.lower() or "sign-off" in text.lower()
    assert "pgvector" in text.lower()
    assert "embeddings" in text.lower()
    assert "no raw" in text.lower() or "No raw" in text.lower()
    assert "Conversation transcript" not in text


def test_readme_links_redacted_replay_166_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/redacted_replay_166_ticket_execution_report.md" in readme
    assert "residual" in readme.lower()


def test_pilot_corpus_planning_links_redacted_replay_166_report() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "redacted_replay_166_ticket_execution_report.md" in text


def test_docs_do_not_recommend_corpus_from_unredacted_normalized() -> None:
    readme = _README.read_text(encoding="utf-8")
    pilot = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "build_pilot_corpus.py" in readme
    assert "vendor_tickets_400.redacted.jsonl" in readme
    assert "Do not" in pilot or "do not" in pilot.lower()
    assert "unredacted" in pilot.lower() or "not" in pilot.lower() and "normalized.jsonl" in pilot


def test_166_report_documents_privacy_review_workflow() -> None:
    text = _LARGER_REPLAY_166_REPORT.read_text(encoding="utf-8")
    assert "build_privacy_review_report.py" in text
    assert "app/privacy_review" in text
    assert "pgvector" in text.lower()
    assert "not" in text.lower() and "moderation" in text.lower() or "governance" in text.lower()


def test_pilot_corpus_planning_doc_exists() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "Pilot Corpus Planning" in text
    assert "## Preconditions" in text
    assert "vendor_ticket_real_pilot" in text
    assert "not_started" in text
    assert "pgvector" in text.lower()
    assert "embeddings" in text.lower()
    assert "privacy review" in text.lower()


def test_readme_links_pilot_corpus_planning() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/pilot_corpus_planning.md" in readme
    assert "app/corpus_planning" in readme


def test_166_report_links_pilot_corpus_planning() -> None:
    text = _LARGER_REPLAY_166_REPORT.read_text(encoding="utf-8")
    assert "pilot_corpus_planning.md" in text


def test_privacy_review_166_execution_report_exists() -> None:
    text = _PRIVACY_REVIEW_166_REPORT.read_text(encoding="utf-8")
    assert "Privacy Review Execution Report" in text
    assert "166" in text
    assert "review_required" in text
    assert "not" in text.lower() and "approved" in text.lower()
    assert "mismatch" in text.lower() and "0" in text
    assert "card_like_long_digits" in text
    assert "iban_like" in text
    assert "phone_like" in text
    assert "pgvector" in text.lower()
    assert "no raw" in text.lower() or "No raw" in text


def test_readme_links_privacy_review_166_execution_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/privacy_review_166_ticket_execution_report.md" in readme
    assert "redacted_replay_166_ticket_execution_report.md" in readme


def test_pilot_corpus_planning_links_privacy_review_166_report() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "privacy_review_166_ticket_execution_report.md" in text
    assert "review_required" in text


def test_reviewer_signoff_workflow_doc_exists() -> None:
    text = _REVIEWER_SIGNOFF_DOC.read_text(encoding="utf-8")
    assert "Reviewer Sign-off Workflow" in text
    assert "corpus_ready_after_signoff" in text
    assert "no_raw_pii_visible" in text
    assert "approved" in text
    assert "escalate" in text
    assert "pgvector" in text.lower()


def test_readme_documents_reviewer_signoff_workflow() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/reviewer_signoff_workflow.md" in readme
    assert "Reviewer Sign-off Workflow" in readme
    assert "corpus_ready_after_signoff" in readme
    assert "create_reviewer_signoff.py" in readme
    assert "select_approved_room_ids.py" in readme


def test_reviewer_signoff_workflow_documents_execution_scripts() -> None:
    text = _REVIEWER_SIGNOFF_DOC.read_text(encoding="utf-8")
    assert "create_reviewer_signoff.py" in text
    assert "select_approved_room_ids.py" in text
    assert "validate_approved_room_ids.py" in text


def test_redacted_replay_report_documents_signoff_execution() -> None:
    text = _REDACTED_REPLAY_166_REPORT.read_text(encoding="utf-8")
    assert "create_reviewer_signoff.py" in text
    assert "approved_room_ids" in text


def test_pilot_corpus_planning_links_reviewer_signoff_workflow() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "reviewer_signoff_workflow.md" in text


def test_pilot_corpus_planning_documents_builder() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "build_pilot_corpus.py" in text
    assert "not_started" in text
    assert "approved-room-ids" in text or "approved room" in text.lower()


def test_readme_documents_pilot_corpus_builder() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "build_pilot_corpus.py" in readme
    assert "approved-room-ids" in readme
    assert "not_started" in readme


def test_pilot_corpus_repository_policy_doc_exists() -> None:
    text = _PILOT_CORPUS_REPO_POLICY.read_text(encoding="utf-8")
    assert "Pilot Corpus Repository Policy" in text
    assert "local" in text.lower() and "private" in text.lower()
    assert "corpus/vendor_ticket_real_pilot/" in text
    assert "not" in text.lower() and "committed" in text.lower()
    assert "embedding" in text.lower()
    assert "lockfile" in text.lower()


def test_readme_links_pilot_corpus_repository_policy() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/pilot_corpus_repository_policy.md" in readme
    assert "local-only" in readme.lower() or "local/private" in readme.lower()


def test_gitignore_excludes_pilot_corpus_and_private_paths() -> None:
    text = _GITIGNORE.read_text(encoding="utf-8")
    assert "data/private/" in text
    assert "reports/" in text
    assert "corpus/vendor_ticket_real_pilot/" in text


def test_pilot_corpus_25_build_report_links_repository_policy() -> None:
    text = _PILOT_CORPUS_25_REPORT.read_text(encoding="utf-8")
    assert "pilot_corpus_repository_policy.md" in text
    assert "local-only" in text.lower() or "local/private" in text.lower()


def test_pilot_corpus_planning_links_repository_policy() -> None:
    text = _PILOT_CORPUS_PLANNING.read_text(encoding="utf-8")
    assert "pilot_corpus_repository_policy.md" in text
