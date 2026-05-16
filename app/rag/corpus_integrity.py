"""Local corpus file inventory, SHA-256 verification, and lockfile comparison (no network)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_ROOT_MANIFEST_FILES = frozenset({"manifest.json", "eval_cases.json"})
_EXCLUDED_CORPUS_FILES = frozenset({"corpus.lock.json"})
_DEFAULT_VENDOR_TICKET_CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "vendor_ticket"
_DEFAULT_VENDOR_TICKET_LOCKFILE = _DEFAULT_VENDOR_TICKET_CORPUS / "corpus.lock.json"


class CorpusFileHash(BaseModel):
    """SHA-256 digest and size for one corpus asset."""

    path: str
    sha256: str
    size_bytes: int


class CorpusHashLockfile(BaseModel):
    """Committed expected hashes and sizes for a corpus tree."""

    lock_version: str
    corpus_name: str
    manifest_version: str | None = None
    eval_version: str | None = None
    files: list[CorpusFileHash]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CorpusIntegrityReport(BaseModel):
    """Result of scanning a corpus directory and optional lockfile comparison."""

    passed: bool
    checked_file_count: int
    issue_count: int
    file_hashes: list[CorpusFileHash]
    issues: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file read in binary mode."""
    p = Path(path)
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_under_base(resolved: Path, base: Path) -> bool:
    try:
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


def _should_include_file(rel: Path) -> bool:
    if rel.name.startswith("."):
        return False
    if rel.name == ".DS_Store":
        return False
    if rel.name in _EXCLUDED_CORPUS_FILES:
        return False
    if "__pycache__" in rel.parts:
        return False
    if rel.name in _ROOT_MANIFEST_FILES:
        return True
    return rel.suffix == ".txt"


def collect_corpus_files(base_dir: str | Path) -> list[Path]:
    """Collect manifest, eval_cases, and ``.txt`` corpus bodies under ``base_dir``."""
    root = Path(base_dir).resolve()
    if not root.is_dir():
        return []

    candidates: list[tuple[str, Path]] = []
    for entry in sorted(root.rglob("*")):
        if not entry.is_file() and not entry.is_symlink():
            continue
        if entry.is_symlink():
            resolved = entry.resolve()
            if not _is_under_base(resolved, root):
                continue
            target = resolved
        else:
            target = entry.resolve()
            if not _is_under_base(target, root):
                continue
        rel = target.relative_to(root)
        if not _should_include_file(rel):
            continue
        candidates.append((str(rel).replace("\\", "/"), target))

    candidates.sort(key=lambda item: item[0])
    return [path for _, path in candidates]


def _read_version_key(base_dir: Path, filename: str, key: str) -> str | None:
    path = base_dir / filename
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = data.get(key)
    return str(value) if value is not None else None


def verify_corpus_integrity(base_dir: str | Path) -> CorpusIntegrityReport:
    """Build a SHA-256 inventory for corpus files under ``base_dir``."""
    root = Path(base_dir)
    resolved_root = root.resolve()
    issues: list[str] = []

    if not resolved_root.is_dir():
        issues.append(f"Corpus base directory does not exist: {resolved_root}")
        return CorpusIntegrityReport(
            passed=False,
            checked_file_count=0,
            issue_count=len(issues),
            file_hashes=[],
            issues=issues,
            metadata={"base_dir": str(resolved_root), "verifier": "local_sha256"},
        )

    files = collect_corpus_files(resolved_root)
    if not files:
        issues.append(f"No corpus files found under: {resolved_root}")

    file_hashes: list[CorpusFileHash] = []
    for file_path in files:
        rel = file_path.relative_to(resolved_root)
        rel_str = str(rel).replace("\\", "/")
        size = file_path.stat().st_size
        file_hashes.append(
            CorpusFileHash(
                path=rel_str,
                sha256=sha256_file(file_path),
                size_bytes=size,
            )
        )

    return CorpusIntegrityReport(
        passed=len(issues) == 0,
        checked_file_count=len(file_hashes),
        issue_count=len(issues),
        file_hashes=file_hashes,
        issues=issues,
        metadata={"base_dir": str(resolved_root), "verifier": "local_sha256"},
    )


def write_corpus_lockfile(
    *,
    base_dir: str | Path,
    lockfile_path: str | Path,
    corpus_name: str,
    lock_version: str = "1",
) -> CorpusHashLockfile:
    """Write a lockfile from the current on-disk corpus inventory."""
    resolved_base = Path(base_dir).resolve()
    report = verify_corpus_integrity(resolved_base)
    if not report.passed:
        raise ValueError(
            f"Cannot write lockfile: corpus integrity failed ({report.issue_count} issue(s)): "
            + "; ".join(report.issues)
        )

    manifest_version = _read_version_key(resolved_base, "manifest.json", "manifest_version")
    eval_version = _read_version_key(resolved_base, "eval_cases.json", "eval_version")

    lockfile = CorpusHashLockfile(
        lock_version=lock_version,
        corpus_name=corpus_name,
        manifest_version=manifest_version,
        eval_version=eval_version,
        files=sorted(report.file_hashes, key=lambda f: f.path),
        metadata={
            "generated_by": "write_corpus_lockfile",
            "checked_file_count": report.checked_file_count,
        },
    )

    out = Path(lockfile_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = lockfile.model_dump()
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return lockfile


def load_corpus_lockfile(path: str | Path) -> CorpusHashLockfile:
    """Load and validate a corpus lockfile (UTF-8 JSON)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corpus lockfile is not valid JSON: {p}") from exc
    return CorpusHashLockfile.model_validate(data)


def verify_corpus_against_lockfile(
    *,
    base_dir: str | Path,
    lockfile_path: str | Path,
) -> CorpusIntegrityReport:
    """Compare on-disk corpus files to a committed lockfile."""
    resolved_lock = Path(lockfile_path).resolve()
    lockfile = load_corpus_lockfile(resolved_lock)
    report = verify_corpus_integrity(base_dir)

    issues = list(report.issues)
    current_by_path = {entry.path: entry for entry in report.file_hashes}
    locked_by_path = {entry.path: entry for entry in lockfile.files}

    for path in sorted(locked_by_path):
        if path not in current_by_path:
            issues.append(f"Missing locked corpus file: {path}")
            continue
        current = current_by_path[path]
        locked = locked_by_path[path]
        if current.sha256 != locked.sha256:
            issues.append(f"Hash mismatch for corpus file: {path}")
        if current.size_bytes != locked.size_bytes:
            issues.append(f"Size mismatch for corpus file: {path}")

    for path in sorted(current_by_path):
        if path not in locked_by_path:
            issues.append(f"Unexpected corpus file not present in lockfile: {path}")

    meta = dict(report.metadata)
    meta.update(
        {
            "verifier": "local_sha256_lockfile",
            "lockfile_path": str(resolved_lock),
            "corpus_name": lockfile.corpus_name,
            "lock_version": lockfile.lock_version,
            "manifest_version": lockfile.manifest_version,
            "eval_version": lockfile.eval_version,
        }
    )

    return CorpusIntegrityReport(
        passed=report.passed and len(issues) == len(report.issues),
        checked_file_count=report.checked_file_count,
        issue_count=len(issues),
        file_hashes=report.file_hashes,
        issues=issues,
        metadata=meta,
    )


def default_vendor_ticket_corpus_integrity() -> CorpusIntegrityReport:
    """Verify the default ``corpus/vendor_ticket`` tree."""
    return verify_corpus_integrity(_DEFAULT_VENDOR_TICKET_CORPUS)


def default_vendor_ticket_corpus_lockfile_path() -> Path:
    """Return the default committed lockfile path for the vendor-ticket corpus."""
    return _DEFAULT_VENDOR_TICKET_LOCKFILE


def verify_default_vendor_ticket_corpus_lockfile() -> CorpusIntegrityReport:
    """Verify default vendor-ticket corpus files against ``corpus.lock.json``."""
    return verify_corpus_against_lockfile(
        base_dir=_DEFAULT_VENDOR_TICKET_CORPUS,
        lockfile_path=_DEFAULT_VENDOR_TICKET_LOCKFILE,
    )
