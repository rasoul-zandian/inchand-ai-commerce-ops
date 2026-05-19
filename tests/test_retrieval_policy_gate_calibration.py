"""Tests for synthetic retrieval policy gate calibration (no pgvector/OpenAI)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.corpus_planning.retrieval_policy_gate_calibration import (
    load_policy_gate_calibration_cases,
    run_policy_gate_calibration,
    score_policy_gate_calibration_case,
)
from scripts.eval_retrieval_policy_gate import main as eval_main

_CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "retrieval_policy_gate"
    / "policy_gate_calibration_cases.json"
)


def test_calibration_cases_file_loads() -> None:
    suite = load_policy_gate_calibration_cases(_CASES_PATH)
    assert suite.calibration_version == "1"
    assert len(suite.cases) >= 15


def test_full_suite_passes() -> None:
    suite = load_policy_gate_calibration_cases(_CASES_PATH)
    report = run_policy_gate_calibration(suite, source_path=str(_CASES_PATH))
    assert report.total_cases == len(suite.cases)
    assert report.pass_rate == 1.0
    assert report.failed_cases == 0
    assert "allow" in report.decision_confusion_matrix
    assert "deny" in report.decision_confusion_matrix
    assert "skip" in report.decision_confusion_matrix


def test_scoring_detects_wrong_expected_decision() -> None:
    suite = load_policy_gate_calibration_cases(_CASES_PATH)
    base = next(c for c in suite.cases if c.case_id == "allow-support-matching-filter")
    from app.corpus_planning.retrieval_policy_gate import RetrievalGateDecision

    case = base.model_copy(update={"expected_decision": RetrievalGateDecision.DENY})
    result = score_policy_gate_calibration_case(case)
    assert result.passed is False
    assert result.actual_decision == "allow"


def test_calibration_module_has_no_pgvector_or_openai() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "corpus_planning"
        / "retrieval_policy_gate_calibration.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    joined = " ".join(modules).lower()
    assert "pgvector" not in joined
    assert "openai" not in joined


def test_eval_script_main_writes_reports(tmp_path: Path) -> None:
    json_out = tmp_path / "calibration.json"
    md_out = tmp_path / "calibration.md"
    rc = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--json-output",
            str(json_out),
            "--markdown-output",
            str(md_out),
            "--overwrite",
        ],
    )
    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["pass_rate"] == 1.0
    md = md_out.read_text(encoding="utf-8")
    assert "Decision confusion matrix" in md
    assert "pgvector" not in md.lower() or "no pgvector" in md.lower()
