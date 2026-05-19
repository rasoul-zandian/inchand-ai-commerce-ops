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
_OFFLINE_EMBEDDING_PLAN = (
    _REPO_ROOT / "docs" / "operations" / "offline_embedding_generation_plan.md"
)
_REAL_OPENAI_EMBEDDING_PLAN = (
    _REPO_ROOT / "docs" / "operations" / "real_openai_embedding_generation_plan.md"
)
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


def test_offline_embedding_plan_doc_exists() -> None:
    text = _OFFLINE_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "Offline Embedding Generation Plan" in text
    assert "not_started" in text
    assert "artifacts/embeddings/" in text
    assert "corpus_lockfile_hash" in text
    assert "no embeddings" in text.lower() or "not generated" in text.lower()


def test_readme_links_offline_embedding_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "docs/operations/offline_embedding_generation_plan.md" in readme
    assert "sensitive" in readme.lower() or "not_started" in readme


def test_repository_policy_links_offline_embedding_plan() -> None:
    text = _PILOT_CORPUS_REPO_POLICY.read_text(encoding="utf-8")
    assert "offline_embedding_generation_plan.md" in text


def test_build_report_links_offline_embedding_plan() -> None:
    text = _PILOT_CORPUS_25_REPORT.read_text(encoding="utf-8")
    assert "offline_embedding_generation_plan.md" in text
    assert "not_started" in text


def test_gitignore_excludes_embedding_artifact_paths() -> None:
    text = _GITIGNORE.read_text(encoding="utf-8")
    assert "artifacts/embeddings/" in text
    assert "artifacts/vector_indexes/" in text


def test_readme_documents_mock_embedding_dry_run() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "build_pilot_corpus_embeddings.py" in readme
    assert "--provider mock" in readme
    assert "artifacts/embeddings/" in readme


def test_offline_embedding_plan_documents_dry_run_script() -> None:
    text = _OFFLINE_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "build_pilot_corpus_embeddings.py" in text
    assert "mock_generated" in text
    assert "no OpenAI" in text or "No OpenAI" in text


def test_mock_embedding_integrity_report_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "mock_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "Mock Embedding Artifact Integrity Report" in text
    assert "check_embedding_artifact_integrity.py" in text
    assert "mock_generated" in text


def test_readme_links_embedding_artifact_integrity() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "check_embedding_artifact_integrity.py" in readme
    assert "mock_embedding_artifact_integrity_report.md" in readme


def test_real_openai_embedding_plan_doc_exists() -> None:
    text = _REAL_OPENAI_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "Real OpenAI Embedding Generation Plan" in text
    assert "text-embedding-3-small" in text
    assert "real_generated" in text
    assert "no OpenAI" in text or "no API" in text.lower() or "Planning only" in text
    assert "pgvector" in text.lower()
    assert "artifacts/embeddings/" in text


def test_readme_links_real_openai_embedding_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "real_openai_embedding_generation_plan.md" in readme


def test_offline_embedding_plan_links_real_openai_plan() -> None:
    text = _OFFLINE_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "real_openai_embedding_generation_plan.md" in text


def test_mock_integrity_report_links_real_openai_plan() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "mock_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "real_openai_embedding_generation_plan.md" in text


def test_repository_policy_notes_real_embedding_plan() -> None:
    text = _PILOT_CORPUS_REPO_POLICY.read_text(encoding="utf-8")
    assert "real_openai_embedding_generation_plan.md" in text


def test_real_embedding_integrity_report_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "real_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "Real Embedding Artifact Integrity Report" in text
    assert "openai" in text
    assert "text-embedding-3-small" in text
    assert "real_generated" in text
    assert "not_started" in text
    assert "pgvector_indexed" in text
    assert "retrieval_activated" in text
    assert "gitignored" in text.lower() or "local/private" in text.lower()
    assert "integrity_issue_count" in text
    assert "8cfc18e1c392" in text


def test_readme_links_real_embedding_integrity_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "real_embedding_artifact_integrity_report.md" in readme


def test_real_openai_plan_links_real_integrity_report() -> None:
    text = _REAL_OPENAI_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "real_embedding_artifact_integrity_report.md" in text


def test_mock_integrity_report_links_real_integrity_report() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "mock_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "real_embedding_artifact_integrity_report.md" in text


def test_pilot_corpus_build_report_links_real_integrity_report() -> None:
    text = _PILOT_CORPUS_25_REPORT.read_text(encoding="utf-8")
    assert "real_embedding_artifact_integrity_report.md" in text


def test_pgvector_sandbox_indexing_plan_doc_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pgvector_sandbox_indexing_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "PgVector Sandbox Indexing Plan" in text
    assert "sandbox" in text.lower()
    assert "semantic_pgvector" in text
    assert "schema proposal only" in text.lower()


def test_readme_links_pgvector_sandbox_indexing_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pgvector_sandbox_indexing_plan.md" in readme


def test_real_integrity_report_links_pgvector_plan() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "real_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "pgvector_sandbox_indexing_plan.md" in text


def test_real_openai_plan_links_pgvector_sandbox_plan() -> None:
    text = _REAL_OPENAI_EMBEDDING_PLAN.read_text(encoding="utf-8")
    assert "pgvector_sandbox_indexing_plan.md" in text


def test_readme_documents_pgvector_sandbox_indexing_cli() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "index_pilot_embeddings_pgvector.py" in readme
    assert "--confirm-sandbox" in readme
    assert "semantic_pgvector" in readme
    assert "reports/pgvector_sandbox_indexing_pilot_v1.json" in readme


def test_pgvector_sandbox_plan_documents_index_cli() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pgvector_sandbox_indexing_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "index_pilot_embeddings_pgvector.py" in text
    assert "--confirm-sandbox" in text
    assert "reports/pgvector_sandbox_indexing_pilot_v1.json" in text
    assert "retrieval_activated" in text


def test_real_integrity_report_documents_sandbox_index_cli() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "real_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "index_pilot_embeddings_pgvector.py" in text
    assert "pgvector_sandbox_indexing_plan.md" in text


def test_readme_documents_pilot_retrieval_eval_cli() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "eval_pilot_retrieval.py" in readme
    assert "evals/pilot_retrieval/vendor_ticket_real_pilot_cases.json" in readme
    assert "retrieval_activated" in readme.lower() or "does not activate" in readme.lower()


def test_pgvector_plan_documents_pilot_retrieval_eval() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pgvector_sandbox_indexing_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "eval_pilot_retrieval.py" in text
    assert "pilot_retrieval_eval_pilot_v1.json" in text


def test_pilot_retrieval_eval_cases_exist() -> None:
    path = _REPO_ROOT / "evals" / "pilot_retrieval" / "vendor_ticket_real_pilot_cases.json"
    text = path.read_text(encoding="utf-8")
    assert "pilot-support-general-001" in text
    assert "conversation_transcript" not in text.lower()
    assert text.count('"case_id"') >= 12
    assert "metadata_filter" in text
    assert "metadata_filtered" in text
    assert (
        '"department"' not in text
        or "metadata_filter.department" in text.lower()
        or ("do not" in text.lower() and "department" in text.lower())
    )


def test_pilot_retrieval_evaluation_report_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    assert "Pilot Retrieval Evaluation Report" in text
    assert "sandbox" in text.lower()
    assert "retrieval_activated" in text
    assert "label_match_rate" in text
    assert "department_match_rate" in text
    assert "wrong_label_return_count" in text
    assert "retrieval_ready_for_sandbox_tooling_review" in text


def test_readme_links_pilot_retrieval_evaluation_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pilot_retrieval_evaluation_report.md" in readme


def test_pgvector_plan_links_pilot_retrieval_evaluation_report() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pgvector_sandbox_indexing_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "pilot_retrieval_evaluation_report.md" in text


def test_real_integrity_report_links_pilot_retrieval_evaluation_report() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "real_embedding_artifact_integrity_report.md"
    text = path.read_text(encoding="utf-8")
    assert "pilot_retrieval_evaluation_report.md" in text


def test_pilot_retrieval_evaluation_report_governance_conclusions() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "no production retrieval" in lowered or "production retrieval activation" in lowered
    assert "langgraph" in lowered
    assert "retrieval_ready_for_sandbox_tooling_review" in text
    assert "retrieval_activated" in lowered
    assert "retrieval_activated=false" in lowered.replace(" ", "") or "**false**" in text


def test_pilot_retrieval_failure_analysis_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_failure_analysis.md"
    text = path.read_text(encoding="utf-8")
    assert "Pilot Retrieval Failure Analysis" in text
    assert "0.6667" in text
    assert "pilot-fund-settlement-005" in text
    assert "fund" in text.lower()
    assert "retrieval_ready_for_sandbox_tooling_review" in text


def test_readme_links_pilot_retrieval_failure_analysis() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pilot_retrieval_failure_analysis.md" in readme


def test_evaluation_report_links_failure_analysis() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    assert "pilot_retrieval_failure_analysis.md" in text
    assert "0.6667" in text


def test_failure_analysis_documents_hypotheses_and_calibration() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_failure_analysis.md"
    lowered = path.read_text(encoding="utf-8").lower()
    assert "persian" in lowered or "fa-ir" in lowered
    assert "label-filtered" in lowered or "label filtered" in lowered
    assert "metadata" in lowered
    assert "langgraph" in lowered
    assert "sandbox only" in lowered or "sandbox-only" in lowered
    assert "compare-modes" in lowered or "metadata_filtered" in lowered


def test_readme_documents_compare_modes() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "--compare-modes" in readme
    assert "metadata_filtered" in readme
    assert "delta_pass_rate" in readme


def test_readme_documents_pilot_metadata_inventory() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "inspect_pilot_pgvector_metadata.py" in readme
    assert "pilot_pgvector_metadata_inventory_pilot_v1.json" in readme


def test_failure_analysis_documents_metadata_inventory() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_failure_analysis.md"
    text = path.read_text(encoding="utf-8")
    assert "inspect_pilot_pgvector_metadata.py" in text
    assert "missing_field_counts" in text or "metadata.department" in text


def test_balanced_pilot_corpus_rebuild_doc_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "balanced_pilot_corpus_rebuild.md"
    text = path.read_text(encoding="utf-8")
    assert "Balanced Pilot Corpus Rebuild" in text
    assert "--balance-pilot" in text
    assert "fund=0" in text
    assert "build_pilot_corpus.py" in text
    assert "eval_pilot_retrieval.py" in text
    assert "reviewer" in text.lower()


def test_readme_links_balanced_pilot_corpus_rebuild() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "balanced_pilot_corpus_rebuild.md" in readme
    assert "--balance-pilot" in readme


def test_failure_analysis_links_balanced_rebuild() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_retrieval_failure_analysis.md"
    text = path.read_text(encoding="utf-8")
    assert "balanced_pilot_corpus_rebuild.md" in text
    assert "Step 121" in text


def test_pilot_balanced_rebuild_execution_report_exists() -> None:
    path = _REPO_ROOT / "docs" / "operations" / "pilot_balanced_rebuild_execution_report.md"
    text = path.read_text(encoding="utf-8")
    assert "Step 122" in text
    assert "fund=8" in text or "fund **8**" in text
    assert "retrieval_activated" in text.lower() or "retrieval not activated" in text.lower()
    assert "pilot_balanced_v1" in text


def test_readme_links_pilot_balanced_rebuild_execution_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "pilot_balanced_rebuild_execution_report.md" in readme


def test_failure_analysis_documents_step_123_eval_calibration() -> None:
    path = _REPO_ROOT / "docs/operations/pilot_retrieval_failure_analysis.md"
    text = path.read_text(encoding="utf-8")
    assert "Step 123" in text
    assert "eval_version" in text.lower() or "v4" in text
    assert "namespace" in text.lower()


def test_sandbox_retrieval_tool_contract_doc_exists() -> None:
    path = _REPO_ROOT / "docs/operations/sandbox_retrieval_tool_contract.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "Sandbox Retrieval Tool Contract" in text
    assert "retrieval_activated" in lowered
    assert "sandbox_only" in lowered
    assert "langgraph" in lowered
    assert "not approved" in lowered or "not implemented" in lowered
    assert "ticket_label" in lowered


def test_readme_links_sandbox_retrieval_tool_contract() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "sandbox_retrieval_tool_contract.md" in readme
    assert "retrieval_tool_models" in readme
    assert "run_sandbox_retrieval_tool.py" in readme
    assert "--confirm-sandbox" in readme


def test_sandbox_retrieval_tool_contract_documents_executor() -> None:
    path = _REPO_ROOT / "docs/operations/sandbox_retrieval_tool_contract.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "execute_sandbox_retrieval_tool" in text
    assert "run_sandbox_retrieval_tool.py" in text
    assert "langgraph" in lowered
    assert "not approved" in lowered or "not" in lowered
    assert "retrieval_activated" in lowered


def test_evaluation_report_documents_sandbox_executor() -> None:
    path = _REPO_ROOT / "docs/operations/pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    assert "sandbox_retrieval_tool.py" in text
    assert "run_sandbox_retrieval_tool.py" in text
    assert "not" in text.lower() and "langgraph" in text.lower()


def test_evaluation_report_links_sandbox_retrieval_tool_contract() -> None:
    path = _REPO_ROOT / "docs/operations/pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    assert "sandbox_retrieval_tool_contract.md" in text
    assert "sandbox_retrieval_tool_smoke_test_report.md" in text
    assert "not" in text.lower() and "runtime activation" in text.lower()


def test_sandbox_retrieval_tool_smoke_test_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/sandbox_retrieval_tool_smoke_test_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "retrieval_activated" in lowered
    assert "sandbox_only" in lowered
    assert "false" in lowered
    assert "c24189e23ea1c12c" in text
    assert "vendor_ticket_real_pilot_balanced" in text
    assert "pilot_balanced_v1" in text


def test_sandbox_retrieval_tool_smoke_test_report_blocks_activation() -> None:
    path = _REPO_ROOT / "docs/operations/sandbox_retrieval_tool_smoke_test_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "langgraph" in lowered
    assert "not" in lowered
    assert "production" in lowered and "rag_profile" in lowered
    assert "customer-facing" in lowered or "customer-facing retrieval" in lowered


def test_readme_links_sandbox_retrieval_tool_smoke_test_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "sandbox_retrieval_tool_smoke_test_report.md" in readme


def test_langgraph_retrieval_integration_plan_exists() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_retrieval_integration_plan.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "LangGraph Retrieval Integration Plan" in text
    assert "retrieval policy gate" in lowered
    assert "retrieval_activated" in lowered
    assert "plan only" in lowered or "planning only" in lowered


def test_langgraph_retrieval_integration_plan_blocks_activation() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_retrieval_integration_plan.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "no runtime activation" in lowered or "retrieval_activated" in lowered
    assert "false" in lowered
    assert "rag_profile" in lowered
    assert "not" in lowered and "production" in lowered
    assert "customer-facing" in lowered or "customer-facing retrieval" in lowered
    assert "no langgraph wiring" in lowered or "no implementation" in lowered


def test_langgraph_retrieval_integration_plan_governance_boundaries() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_retrieval_integration_plan.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "hitl" in lowered
    assert "audit" in lowered
    assert "feature flag" in lowered
    assert "metadata_filtered" in lowered or "metadata-filtered" in lowered


def test_readme_links_langgraph_retrieval_integration_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "langgraph_retrieval_integration_plan.md" in readme


def test_evaluation_report_links_langgraph_retrieval_integration_plan() -> None:
    path = _REPO_ROOT / "docs/operations/pilot_retrieval_evaluation_report.md"
    text = path.read_text(encoding="utf-8")
    assert "langgraph_retrieval_integration_plan.md" in text


def test_retrieval_policy_gate_contract_exists() -> None:
    path = _REPO_ROOT / "docs/operations/retrieval_policy_gate_contract.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "Retrieval Policy Gate Contract" in text
    assert "retrieval_activated" in lowered
    assert "sandbox_only" in lowered
    assert "retrieval policy gate" in lowered or "evaluate_retrieval_policy_gate" in lowered


def test_retrieval_policy_gate_contract_blocks_runtime_activation() -> None:
    path = _REPO_ROOT / "docs/operations/retrieval_policy_gate_contract.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "false" in lowered
    assert "langgraph" in lowered
    assert "not" in lowered
    assert "pgvector" in lowered or "openai" in lowered


def test_readme_links_retrieval_policy_gate_contract() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "retrieval_policy_gate_contract.md" in readme
    assert "evaluate_retrieval_policy_gate" in readme or "retrieval_policy_gate" in readme


def test_langgraph_plan_links_retrieval_policy_gate_contract() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_retrieval_integration_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "retrieval_policy_gate_contract.md" in text


def test_langgraph_plan_documents_retrieval_state_fields() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_retrieval_integration_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "retrieval_gate_decision" in text
    assert "retrieval_state.py" in text
    assert "retrieval_activated" in text.lower()


def test_readme_mentions_retrieval_state_helpers() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "retrieval_state.py" in readme
    assert "retrieval_" in readme


def test_readme_documents_sandbox_retrieval_chain_dry_run() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "dry_run_sandbox_retrieval_chain.py" in readme
    assert "--confirm-sandbox" in readme
    assert "not" in readme.lower() and "langgraph" in readme.lower()


def test_dry_run_retrieval_chain_smoke_test_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/dry_run_retrieval_chain_smoke_test_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "Dry-run Retrieval Chain Smoke Test Report" in text
    assert "retrieval_activated" in lowered
    assert "sandbox_only" in lowered
    assert "false" in lowered
    assert "c24189e23ea1c12c" in text
    assert "executor_called" in lowered


def test_dry_run_retrieval_chain_smoke_test_report_blocks_activation() -> None:
    path = _REPO_ROOT / "docs/operations/dry_run_retrieval_chain_smoke_test_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "langgraph" in lowered
    assert "not" in lowered
    assert "production" in lowered and "rag_profile" in lowered
    assert "customer-facing" in lowered or "customer-facing retrieval" in lowered
    assert "retrieval_activated" in lowered and "false" in lowered


def test_readme_links_dry_run_retrieval_chain_smoke_test_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "dry_run_retrieval_chain_smoke_test_report.md" in readme


def test_langgraph_sandbox_retrieval_node_plan_exists() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_sandbox_retrieval_node_plan.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "LangGraph Sandbox Retrieval Node Plan" in text
    assert "shadow" in lowered
    assert "langgraph_sandbox_retrieval_enabled" in lowered


def test_langgraph_sandbox_retrieval_node_plan_shadow_and_flags() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_sandbox_retrieval_node_plan.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "default" in lowered and "false" in lowered
    assert "draft" in lowered and "final" in lowered
    assert "not" in lowered and "rag_profile" in lowered
    assert "production" in lowered


def test_readme_links_langgraph_sandbox_retrieval_node_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "langgraph_sandbox_retrieval_node_plan.md" in readme


def test_langgraph_shadow_retrieval_smoke_test_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_shadow_retrieval_smoke_test_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "LangGraph Shadow Retrieval Smoke Test Report" in text
    assert "retrieval_activated" in lowered
    assert "false" in lowered
    assert "shadow_node_executed" in lowered


def test_langgraph_shadow_retrieval_smoke_test_report_governance() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_shadow_retrieval_smoke_test_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "default" in lowered and "false" in lowered
    assert "downstream_consumed_retrieval" in lowered
    assert "false" in lowered
    assert "not influenced" in lowered or "did not" in lowered


def test_readme_links_langgraph_shadow_retrieval_smoke_test_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "langgraph_shadow_retrieval_smoke_test_report.md" in readme


def test_readme_documents_shadow_replay_export_and_dashboard() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "export_shadow_replay_jsonl.py" in readme
    assert "build_shadow_retrieval_metrics_dashboard.py" in readme
    assert "--confirm-sandbox" in readme
    assert "LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED" in readme


def test_langgraph_sandbox_retrieval_node_plan_links_shadow_export() -> None:
    path = _REPO_ROOT / "docs/operations/langgraph_sandbox_retrieval_node_plan.md"
    text = path.read_text(encoding="utf-8")
    assert "export_shadow_replay_jsonl.py" in text
    assert "build_shadow_retrieval_metrics_dashboard.py" in text


def test_shadow_replay_metrics_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/shadow_replay_metrics_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Shadow Replay Metrics Report" in text
    assert "total_rows" in text
    assert "166" in text


def test_shadow_replay_metrics_report_governance() -> None:
    path = _REPO_ROOT / "docs/operations/shadow_replay_metrics_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "retrieval_activated_true_count" in lowered or "retrieval_activated" in lowered
    assert "false" in lowered
    assert "downstream_consumed_retrieval" in lowered
    assert "allow" in lowered
    assert "166" in text
    assert "query" not in lowered or "raw queries" in lowered or "no raw" in lowered


def test_readme_links_shadow_replay_metrics_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "shadow_replay_metrics_report.md" in readme


def test_shadow_replay_metrics_refresh_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/shadow_replay_metrics_refresh_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Shadow Replay Metrics Refresh Report" in text
    assert "Step 142" in text
    assert "Step 141" in text


def test_shadow_replay_metrics_refresh_report_governance() -> None:
    path = _REPO_ROOT / "docs/operations/shadow_replay_metrics_refresh_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert '"5": 166' in text or "5` | 166" in text or "5 | 166" in text
    assert "result_count_distribution" in lowered
    assert "retrieval_activated_true_count" in lowered
    assert "downstream_consumed_retrieval_true_count" in lowered
    assert "0" in text
    assert "ticket_label" in lowered and "route_label" in lowered
    assert "review_priority" in lowered


def test_readme_links_shadow_replay_metrics_refresh_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "shadow_replay_metrics_refresh_report.md" in readme


def test_non_shadow_retrieval_consumption_governance_plan_exists() -> None:
    path = _REPO_ROOT / "docs/operations/non_shadow_retrieval_consumption_governance_plan.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Non-Shadow Retrieval Consumption Governance Plan" in text
    assert "Step 144" in text


def test_non_shadow_retrieval_consumption_governance_plan_governance() -> None:
    path = _REPO_ROOT / "docs/operations/non_shadow_retrieval_consumption_governance_plan.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "hitl-only" in lowered or "hitl only" in lowered
    assert "draft-assist" in lowered or "draft assist" in lowered
    assert "blocked" in lowered
    assert "customer-facing" in lowered or "customer facing" in lowered
    assert "retrieval_activated" in lowered
    assert "downstream_consumed" in lowered
    assert "not_ready" in lowered
    assert "ready_for_hitl_visibility_review" in lowered
    assert "approved_for_hitl_visibility" in lowered
    assert "166" in text
    assert "retrieval_error_count" in lowered


def test_readme_links_non_shadow_retrieval_consumption_governance_plan() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "non_shadow_retrieval_consumption_governance_plan.md" in readme
    lowered = readme.lower()
    assert "hitl-only" in lowered or "hitl only" in lowered
    assert "blocked" in lowered


def test_vendor_ticket_ai_assist_shadow_workflow_doc_exists() -> None:
    path = _REPO_ROOT / "docs/operations/vendor_ticket_ai_assist_shadow_workflow.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Vendor Ticket AI Assist Shadow Workflow" in text
    assert "Step 145" in text


def test_vendor_ticket_ai_assist_shadow_workflow_doc_governance() -> None:
    path = _REPO_ROOT / "docs/operations/vendor_ticket_ai_assist_shadow_workflow.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "shadow-only" in lowered or "shadow only" in lowered
    assert "hitl" in lowered
    assert "retrieval_activated" in lowered
    assert "downstream_consumed_retrieval" in lowered
    assert "no" in lowered and ("auto-send" in lowered or "customer" in lowered)
    assert "final_response" in lowered or "draft" in lowered
    assert "vendor_ticket_ai_assist_shadow" in lowered
    assert "vendor_ticket_ai_assist_shadow_enabled" in lowered


def test_readme_links_vendor_ticket_ai_assist_shadow_workflow() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "vendor_ticket_ai_assist_shadow_workflow.md" in readme
    lowered = readme.lower()
    assert "shadow-only" in lowered or "shadow only" in lowered
    assert "hitl" in lowered
    assert "vendor_ticket_ai_assist_shadow_enabled" in lowered
    assert "export_ai_assist_shadow_replay_jsonl.py" in readme
    assert "build_ai_assist_shadow_metrics_dashboard.py" in readme


def test_vendor_ticket_ai_assist_shadow_workflow_links_metrics_export() -> None:
    path = _REPO_ROOT / "docs/operations/vendor_ticket_ai_assist_shadow_workflow.md"
    text = path.read_text(encoding="utf-8")
    assert "export_ai_assist_shadow_replay_jsonl.py" in text
    assert "build_ai_assist_shadow_metrics_dashboard.py" in text
    assert "ai_assist_shadow_replay_v1.jsonl" in text


def test_ai_assist_shadow_metrics_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/ai_assist_shadow_metrics_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "AI Assist Shadow Metrics Report" in text
    assert "Step 149" in text
    assert "Step 148" in text


def test_ai_assist_shadow_metrics_report_governance() -> None:
    path = _REPO_ROOT / "docs/operations/ai_assist_shadow_metrics_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "166" in text
    assert "error_count" in lowered
    assert '"0"' in text or "| 0 |" in text or "=0" in text
    assert "monitor" in lowered and "109" in text
    assert "escalate" in lowered and "37" in text
    assert "billing_review" in lowered and "20" in text
    assert "retrieval_activated_true_count" in lowered
    assert "downstream_consumed_retrieval_true_count" in lowered
    assert "retrieval_activated" in lowered and "false" in lowered
    assert "downstream_consumed" in lowered
    assert "ai_assist_shadow_only" in lowered
    assert "human_review_required" in lowered
    assert "vendor_ticket_node" in lowered
    assert "hitl" in lowered


def test_readme_links_ai_assist_shadow_metrics_report() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "ai_assist_shadow_metrics_report.md" in readme
    lowered = readme.lower()
    assert "166" in readme
    assert "error_count" in lowered or "error count" in lowered


def test_retrieval_policy_gate_calibration_report_exists() -> None:
    path = _REPO_ROOT / "docs/operations/retrieval_policy_gate_calibration_report.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Retrieval Policy Gate Calibration Report" in text
    assert "166" in text or "Step 138" in text


def test_retrieval_policy_gate_calibration_report_governance() -> None:
    path = _REPO_ROOT / "docs/operations/retrieval_policy_gate_calibration_report.md"
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "retrieval_activated" in lowered
    assert "false" in lowered
    assert "pass_rate" in lowered
    assert "no pgvector" in lowered or "not called" in lowered


def test_readme_links_retrieval_policy_gate_calibration() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert "retrieval_policy_gate_calibration_report.md" in readme
    assert "eval_retrieval_policy_gate.py" in readme


def test_calibration_cases_file_exists() -> None:
    path = _REPO_ROOT / "evals/retrieval_policy_gate/policy_gate_calibration_cases.json"
    assert path.is_file()


def test_step_124_retrieval_decision_governance_across_docs() -> None:
    """Step 124: sandbox tooling review allowed; production/LangGraph still blocked."""
    doc_paths = [
        _REPO_ROOT / "docs/operations/pilot_retrieval_evaluation_report.md",
        _REPO_ROOT / "docs/operations/pilot_retrieval_failure_analysis.md",
        _REPO_ROOT / "docs/operations/balanced_pilot_corpus_rebuild.md",
        _README,
    ]
    for path in doc_paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "retrieval_ready_for_sandbox_tooling_review" in text, path.name
        assert "retrieval_activated" in lowered, path.name
        assert "langgraph" in lowered, path.name
        assert "rag_profile" in lowered or "production" in lowered, path.name
        assert "not approved" in lowered or "blocked" in lowered or "not implied" in lowered, (
            path.name
        )
