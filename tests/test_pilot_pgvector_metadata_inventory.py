"""Tests for pilot pgvector metadata inventory (fake rows only; no Postgres)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_pgvector_metadata_inventory import (
    PilotMetadataRow,
    assert_safe_inventory_report,
    build_pilot_metadata_inventory,
    inventory_to_dict,
    run_pilot_metadata_inventory,
    write_pilot_metadata_inventory_report,
)
from scripts.inspect_pilot_pgvector_metadata import main as inspect_main


def _fund_row(
    *,
    record_id: str = "pilot::vendor_ticket_real_pilot::pilot_v1::doc-fund-1",
) -> PilotMetadataRow:
    return PilotMetadataRow(
        record_id=record_id,
        metadata={
            "ticket_label": "fund",
            "route_label": "billing_review",
            "review_priority": "high",
            "source_corpus_id": "vendor_ticket_real_pilot",
            "namespace": "vendor_ticket_real_pilot",
            "index_version": "pilot_v1",
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-small",
        },
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
    )


def _support_row() -> PilotMetadataRow:
    return PilotMetadataRow(
        record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-support-1",
        metadata={
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "review_priority": "normal",
            "source_corpus_id": "vendor_ticket_real_pilot",
            "namespace": "vendor_ticket_real_pilot",
            "index_version": "pilot_v1",
        },
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
    )


def test_build_inventory_counts_labels_and_missing_department() -> None:
    inventory = build_pilot_metadata_inventory(
        [_fund_row(), _support_row()],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )
    assert inventory.row_count == 2
    assert inventory.ticket_label_counts["fund"] == 1
    assert inventory.ticket_label_counts["support"] == 1
    assert inventory.department_counts["finance"] == 1
    assert inventory.department_counts["support"] == 1
    assert inventory.explicit_department_present_count == 0
    assert inventory.missing_field_counts.get("department", 0) == 2
    assert "ticket_label" in inventory.metadata_keys_present
    assert "route_label" in inventory.metadata_keys_present


def test_inventory_output_excludes_forbidden_fields(tmp_path: Path) -> None:
    inventory = build_pilot_metadata_inventory(
        [_fund_row()],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )
    payload = inventory_to_dict(inventory)
    serialized = json.dumps(payload)
    assert "conversation_transcript" not in serialized.lower()
    assert '"vector"' not in serialized
    assert '"content"' not in serialized
    assert_safe_inventory_report(payload)
    write_pilot_metadata_inventory_report(
        inventory,
        output_path=tmp_path / "reports" / "pilot_pgvector_metadata_inventory_pilot_v1.json",
    )


def test_run_with_fake_row_fetcher() -> None:
    rows = [_fund_row() for _ in range(25)]

    def fake_fetch(
        _database_url: str,
        *,
        table_name: str,
        namespace: str,
        index_version: str,
    ) -> list[PilotMetadataRow]:
        _ = table_name
        assert namespace == "vendor_ticket_real_pilot"
        assert index_version == "pilot_v1"
        return rows

    inventory = run_pilot_metadata_inventory(
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        row_fetcher=fake_fetch,
    )
    assert inventory.row_count == 25
    assert inventory.ticket_label_counts.get("fund") == 25


def test_cli_success_with_fake_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.corpus_planning.pilot_pgvector_metadata_inventory import PilotMetadataInventory

    fake_inventory = PilotMetadataInventory(
        row_count=25,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        ticket_label_counts={"fund": 8, "support": 10, "complaint": 7},
        department_counts={"finance": 8, "support": 10, "complaint": 7},
        route_label_counts={"billing_review": 8},
        review_priority_counts={"high": 8, "normal": 17},
        source_corpus_id_counts={"vendor_ticket_real_pilot": 25},
        embedding_provider_counts={"openai": 25},
        embedding_model_counts={"text-embedding-3-small": 25},
        missing_field_counts={"department": 25},
        metadata_keys_present=("ticket_label", "route_label"),
        explicit_department_present_count=0,
        derived_department_empty_count=0,
    )

    monkeypatch.setattr(
        "scripts.inspect_pilot_pgvector_metadata.run_pilot_metadata_inventory",
        lambda *a, **k: fake_inventory,
    )
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    code = inspect_main(
        [
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--output",
            str(tmp_path / "reports" / "pilot_pgvector_metadata_inventory_pilot_v1.json"),
            "--overwrite",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "row_count=25" in out
    assert "explicit_department_present_count=0" in out


def test_cli_rejects_production_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://user:pass@mydb.prod.amazonaws.com:5432/inchand_ai",
    )
    code = inspect_main(
        [
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--overwrite",
        ]
    )
    assert code == 1
