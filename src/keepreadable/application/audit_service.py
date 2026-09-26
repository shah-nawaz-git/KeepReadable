import logging
import os
import platform
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any

import pikepdf
import pypdf
from PIL import __version__ as pillow_version

from keepreadable.analysis.archive_identity import (
    ArchiveAvailability,
    is_root_available,
    resolve_archive_root,
)
from keepreadable.analysis.classification import (
    FileWorkResult,
    IdentificationOutcome,
    classify_file,
)
from keepreadable.analysis.discovery import DiscoveryOptions, SkippedItem, discover_files
from keepreadable.analysis.eta import EtaEstimator
from keepreadable.analysis.finding_texts import finding_text
from keepreadable.analysis.findings import reconcile
from keepreadable.analysis.hashing import hash_file
from keepreadable.analysis.normalization import extension_of
from keepreadable.analysis.planner import (
    CurrentStat,
    PlanContext,
    PreviousState,
    WorkPlan,
    WorkStep,
    plan_file,
)
from keepreadable.config.settings import Settings
from keepreadable.domain.archive import Archive
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    ChangeKind,
    FindingCategory,
    FindingCode,
    FindingSeverity,
    HealthState,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.finding import Finding
from keepreadable.domain.observation import Observation
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.integrations.siegfried import SiegfriedAdapter, SiegfriedError
from keepreadable.integrations.subprocess_runner import ToolNotFoundError
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    KEEP,
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    FindingRepository,
    ObservationRepository,
)
from keepreadable.policies.registry import PolicyRegistry
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled
from keepreadable.utilities.clock import utcnow
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import EvidenceCode, ValidationDepth
from keepreadable.validators.media import FFmpegMediaValidator
from keepreadable.validators.registry import ValidatorRegistry

logger = logging.getLogger(__name__)


class AuditStage(StrEnum):
    PREPARING = auto()
    DISCOVERING = auto()
    PROCESSING = auto()
    FINALIZING = auto()
    COMPLETED = auto()
    STOPPED = auto()


@dataclass(frozen=True, slots=True)
class AuditProgress:
    run_id: int
    stage: AuditStage
    files_discovered: int
    files_total_estimate: int
    files_processed: int
    files_failed: int
    files_skipped: int
    findings_count: int
    current_path: str | None
    elapsed_seconds: float
    bytes_hashed: int
    estimated_remaining_seconds: float | None


class ArchiveUnavailableError(Exception):
    pass


class AuditStateError(Exception):
    pass


class AuditEngine:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        siegfried: SiegfriedAdapter | None,
        ffmpeg: FFmpegAdapter | None,
        validators: ValidatorRegistry,
        policy: PolicyRegistry,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = db
        self.settings = settings
        self.siegfried = siegfried
        self.ffmpeg = ffmpeg
        self.validators = validators
        self.policy = policy
        self.clock = clock
        self._media_semaphore = BoundedSemaphore(max(1, settings.media_decode_workers))
        self._hash_lock = Lock()
        self._bytes_hashed = 0

    def start(
        self,
        archive_id: int,
        mode: AuditMode,
        *,
        force_deep_all: bool = False,
        cancel: CancellationToken | None = None,
        on_progress: Callable[[AuditProgress], None] | None = None,
    ) -> AuditRun:
        _archive, root = self._resolve_archive(archive_id, resume_run_id=None)
        now = self.clock()
        signature_version = None
        if self.siegfried is not None:
            try:
                signature_version = self.siegfried.info().identifiers or None
            except (SiegfriedError, ToolNotFoundError, OSError):
                logger.warning("Siegfried version information unavailable")
        run = AuditRun(
            archive_id=archive_id,
            mode=mode,
            status=AuditStatus.RUNNING,
            started_at=now,
            completed_at=None,
            policy_version=self.policy.policy_version,
            signature_version=signature_version,
            tool_versions=self._tool_versions(),
            force_deep_all=force_deep_all,
        )
        with self.db.session() as session:
            run = AuditRunRepository(session).add(run)
        return self._execute(run, root, cancel, on_progress)

    def resume(
        self,
        run_id: int,
        *,
        cancel: CancellationToken | None = None,
        on_progress: Callable[[AuditProgress], None] | None = None,
    ) -> AuditRun:
        with self.db.session() as session:
            repository = AuditRunRepository(session)
            run = repository.get(run_id)
            if run is None:
                raise AuditStateError(f"Audit run {run_id} does not exist")
            if run.status not in {
                AuditStatus.RUNNING,
                AuditStatus.INTERRUPTED,
                AuditStatus.PAUSED,
            }:
                raise AuditStateError(f"Audit run {run_id} is not resumable")
        try:
            _archive, root = self._resolve_archive(run.archive_id, resume_run_id=run_id)
        except ArchiveUnavailableError:
            raise
        with self.db.session() as session:
            updated = AuditRunRepository(session).update(run_id, status=AuditStatus.RUNNING)
            assert updated is not None
            run = updated
        return self._execute(run, root, cancel, on_progress)

    def discard(self, run_id: int) -> AuditRun:
        with self.db.session() as session:
            repository = AuditRunRepository(session)
            run = repository.get(run_id)
            if run is None:
                raise AuditStateError(f"Audit run {run_id} does not exist")
            updated = repository.update(
                run_id,
                status=AuditStatus.CANCELLED,
                interruption_reason="discarded",
                completed_at=self.clock(),
            )
            assert updated is not None
            return updated

    def recover_interrupted(self) -> list[AuditRun]:
        recovered: list[AuditRun] = []
        with self.db.session() as session:
            repository = AuditRunRepository(session)
            for run in repository.find_interrupted():
                if run.status is not AuditStatus.RUNNING or run.id is None:
                    continue
                updated = repository.update(
                    run.id,
                    status=AuditStatus.INTERRUPTED,
                    interruption_reason="application_closed",
                )
                if updated is not None:
                    recovered.append(updated)
        return recovered

    def _resolve_archive(self, archive_id: int, resume_run_id: int | None) -> tuple[Archive, Path]:
        unavailable = False
        result: tuple[Archive, Path] | None = None
        with self.db.session() as session:
            archives = ArchiveRepository(session)
            archive = archives.get(archive_id)
            if archive is None:
                raise ArchiveUnavailableError(f"Archive {archive_id} is not registered")
            resolved = resolve_archive_root(archive.root_path, archive.root_fingerprint)
            if resolved.availability is ArchiveAvailability.UNAVAILABLE or resolved.path is None:
                unavailable = True
                if resume_run_id is not None:
                    AuditRunRepository(session).update(
                        resume_run_id,
                        status=AuditStatus.INTERRUPTED,
                        interruption_reason="archive_unavailable",
                    )
            else:
                if resolved.availability is ArchiveAvailability.RELOCATED:
                    archive = archives.update_root(archive_id, str(resolved.path)) or archive
                result = archive, resolved.path
        if unavailable or result is None:
            raise ArchiveUnavailableError("The archive root is unavailable")
        return result

    def _execute(
        self,
        run: AuditRun,
        root: Path,
        cancel: CancellationToken | None,
        on_progress: Callable[[AuditProgress], None] | None,
    ) -> AuditRun:
        token = cancel or CancellationToken()
        started = time.monotonic()
        estimator = EtaEstimator()
        self._bytes_hashed = int(run.resume_state.get("bytes_hashed", 0))
        try:
            self._emit(run, AuditStage.PREPARING, started, estimator, None, on_progress)
            if not run.resume_state.get("discovery_complete"):
                run = self._discover(run, root, token, started, estimator, on_progress)
            if not is_root_available(root):
                with self.db.session() as session:
                    updated = AuditRunRepository(session).update(
                        run.id or 0,
                        resume_state={**run.resume_state, "discovery_complete": False},
                    )
                    if updated is not None:
                        run = updated
                return self._interrupt(run, "archive_unavailable")
            token.raise_if_cancelled()
            run = self._process(run, root, token, started, estimator, on_progress)
            token.raise_if_cancelled()
            if not is_root_available(root):
                return self._interrupt(run, "archive_unavailable")
            run = self._finalize(run, root, started, estimator, on_progress)
            return run
        except OperationCancelled:
            status = AuditStatus.PAUSED if token.reason == "pause" else AuditStatus.CANCELLED
            reason = token.reason or "cancelled"
            return self._stop(run.id or 0, status, reason)
        except ArchiveUnavailableError:
            return self._interrupt(run, "archive_unavailable")
        except Exception as exc:
            logger.exception("Audit run %s failed", run.id)
            with self.db.session() as session:
                updated = AuditRunRepository(session).update(
                    run.id or 0,
                    status=AuditStatus.FAILED,
                    completed_at=self.clock(),
                    error_summary=str(exc)[:1000],
                    interruption_reason="unexpected_error",
                )
                assert updated is not None
                return updated

    def _discover(
        self,
        run: AuditRun,
        root: Path,
        token: CancellationToken,
        started: float,
        estimator: EtaEstimator,
        callback: Callable[[AuditProgress], None] | None,
    ) -> AuditRun:
        skipped: list[dict[str, str]] = []
        skipped_count = 0
        discovered_count = 0
        batch: list[FileRecord] = []

        def on_skip(item: SkippedItem) -> None:
            nonlocal skipped_count
            skipped_count += 1
            if len(skipped) < 100:
                skipped.append({"path": item.relative_path, "reason": item.reason.value})

        def persist() -> None:
            nonlocal run, batch
            if not batch:
                return
            with self.db.session() as session:
                FileRecordRepository(session).upsert_batch(run.archive_id, batch)
                state = {**run.resume_state, "skipped": skipped}
                updated = AuditRunRepository(session).update(
                    run.id or 0,
                    files_discovered=discovered_count,
                    files_skipped=skipped_count,
                    resume_state=state,
                )
                assert updated is not None
                run = updated
            batch = []
            self._emit(run, AuditStage.DISCOVERING, started, estimator, None, callback)
            token.raise_if_cancelled()

        try:
            for item in discover_files(
                root,
                DiscoveryOptions(self.settings.follow_reparse_points),
                cancel=token,
                on_skip=on_skip,
            ):
                discovered_count += 1
                batch.append(
                    FileRecord(
                        archive_id=run.archive_id,
                        relative_path=item.relative_path,
                        normalized_path=item.normalized_path,
                        size=item.size,
                        mtime_ns=item.mtime_ns,
                        filesystem_identity=item.filesystem_identity,
                        first_seen_audit_id=run.id or 0,
                        last_seen_audit_id=run.id or 0,
                        present=True,
                        last_health=None,
                        last_deep_verified_at=None,
                        last_sha256=None,
                    )
                )
                if len(batch) >= self.settings.persistence_batch_size:
                    persist()
            persist()
        except OSError as exc:
            if not is_root_available(root):
                raise ArchiveUnavailableError from exc
            raise
        state = {**run.resume_state, "skipped": skipped, "discovery_complete": True}
        with self.db.session() as session:
            updated = AuditRunRepository(session).update(
                run.id or 0,
                files_discovered=discovered_count,
                files_skipped=skipped_count,
                resume_state=state,
            )
            assert updated is not None
            return updated

    def _process(
        self,
        run: AuditRun,
        root: Path,
        token: CancellationToken,
        started: float,
        estimator: EtaEstimator,
        callback: Callable[[AuditProgress], None] | None,
    ) -> AuditRun:
        while True:
            token.raise_if_cancelled()
            with self.db.session() as session:
                records = FileRecordRepository(session).next_pending_batch(
                    run.archive_id,
                    run.id or 0,
                    self.settings.identification_batch_size,
                )
                previous = ObservationRepository(session).latest_for_files(
                    [record.id or 0 for record in records]
                )
                previous_runs = {
                    observation.audit_run_id: AuditRunRepository(session).get(
                        observation.audit_run_id
                    )
                    for observation in previous.values()
                }
            if not records:
                return run
            now = self.clock()
            plans = {
                record.id or 0: self._plan(
                    record, previous.get(record.id or 0), previous_runs, run, now
                )
                for record in records
            }
            identification = self._identify_batch(records, plans, root, run, token)
            latest_started: list[str | None] = [None]
            started_lock = Lock()

            def process_record(
                record: FileRecord,
                current_plans: dict[int, WorkPlan] = plans,
                prior_observations: dict[int, Observation] = previous,
                identification_results: dict[int, IdentificationOutcome] = identification,
                path_state: list[str | None] = latest_started,
                path_lock: Lock = started_lock,
            ) -> FileWorkResult:
                with path_lock:
                    path_state[0] = record.relative_path
                return self._work_one(
                    record,
                    root,
                    current_plans[record.id or 0],
                    prior_observations.get(record.id or 0),
                    identification_results.get(record.id or 0),
                    token,
                )

            with ThreadPoolExecutor(max_workers=max(1, self.settings.worker_count)) as executor:
                futures = {
                    executor.submit(process_record, record): index
                    for index, record in enumerate(records)
                }
                pending = set(futures)
                completed_in_batch = 0
                last_progress_emit = time.monotonic()
                ordered_results: list[FileWorkResult | None] = [None] * len(records)
                while pending:
                    completed, pending = wait(
                        pending,
                        timeout=0.25,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in completed:
                        ordered_results[futures[future]] = future.result()
                    completed_in_batch += len(completed)
                    current_time = time.monotonic()
                    if callback is not None and current_time - last_progress_emit >= 0.25:
                        with started_lock:
                            current_path = latest_started[0]
                        self._emit(
                            run,
                            AuditStage.PROCESSING,
                            started,
                            estimator,
                            current_path,
                            callback,
                            files_processed_override=(run.files_processed + completed_in_batch),
                        )
                        last_progress_emit = current_time
                        token.raise_if_cancelled()
                work_results = [result for result in ordered_results if result is not None]
            if any(result.vanished for result in work_results) and not is_root_available(root):
                return self._interrupt(run, "archive_unavailable")
            classified = [
                classify_file(
                    result,
                    previous.get(result.record.id or 0),
                    self.policy,
                    run,
                    now,
                )
                for result in work_results
            ]
            with self.db.session() as session:
                observations = ObservationRepository(session)
                findings = FindingRepository(session)
                files = FileRecordRepository(session)
                observations.add_batch([item.observation for item in classified])
                existing = findings.open_for_files([record.id or 0 for record in records])
                updates: list[tuple[int, HealthState, str | None, object, object]] = []
                added = 0
                for result, item in zip(work_results, classified, strict=True):
                    record_id = result.record.id or 0
                    previous_findings = existing.get(record_id, [])
                    current_findings = list(item.findings)
                    if (
                        result.plan.reuse_previous_identification
                        and result.plan.reuse_previous_validation
                    ):
                        excluded = (
                            {
                                FindingCode.FORMAT_REVIEW.value,
                                FindingCode.POLICY_CLASSIFICATION_CHANGED.value,
                            }
                            if result.plan.policy_changed
                            else set()
                        )
                        current_codes = {finding.code for finding in current_findings}
                        current_findings.extend(
                            finding
                            for finding in previous_findings
                            if finding.code not in current_codes and finding.code not in excluded
                        )
                    reconciliation = reconcile(previous_findings, current_findings, now)
                    findings.add_batch(reconciliation.to_add)
                    findings.resolve_ids(reconciliation.to_resolve_ids, now)
                    findings.update_batch(reconciliation.to_update)
                    added += len(reconciliation.to_add)
                    sha_value: object = KEEP
                    verified_value: object = KEEP
                    if WorkStep.HASH in result.plan.steps:
                        sha_value = item.new_sha256 if item.deep_verified else None
                        if item.deep_verified:
                            verified_value = now
                    updates.append(
                        (
                            record_id,
                            item.observation.health,
                            item.observation.detected_format,
                            sha_value,
                            verified_value,
                        )
                    )
                files.update_after_observation(updates)
                failed = run.files_failed + sum(
                    bool(item.error or item.vanished) for item in work_results
                )
                identification_failures = sum(
                    outcome is not None and not outcome.available
                    for outcome in identification.values()
                )
                ffmpeg_failures = sum(
                    result.validation is not None
                    and EvidenceCode.TOOL_UNAVAILABLE in result.validation.codes
                    and isinstance(
                        self.validators.resolve(
                            puid=None,
                            extension=extension_of(result.record.relative_path),
                            mime=None,
                        )[0],
                        FFmpegMediaValidator,
                    )
                    for result in work_results
                )
                state = {
                    **run.resume_state,
                    "processed": run.files_processed + len(records),
                    "last_path": records[-1].relative_path,
                    "bytes_hashed": self._bytes_hashed,
                    "identification_failures": int(
                        run.resume_state.get("identification_failures", 0)
                    )
                    + identification_failures,
                    "ffmpeg_failures": int(run.resume_state.get("ffmpeg_failures", 0))
                    + ffmpeg_failures,
                }
                updated = AuditRunRepository(session).update(
                    run.id or 0,
                    files_processed=run.files_processed + len(records),
                    files_failed=failed,
                    findings_count=run.findings_count + added,
                    resume_state=state,
                )
                assert updated is not None
                run = updated
            self._emit(
                run,
                AuditStage.PROCESSING,
                started,
                estimator,
                records[-1].relative_path,
                callback,
            )
            token.raise_if_cancelled()

    def _plan(
        self,
        record: FileRecord,
        previous: Observation | None,
        previous_runs: dict[int, AuditRun | None],
        run: AuditRun,
        now: datetime,
    ) -> WorkPlan:
        state = None
        if previous is not None:
            previous_run = previous_runs.get(previous.audit_run_id)
            state = PreviousState(
                size=previous.observed_size,
                mtime_ns=previous.observed_mtime_ns,
                sha256=previous.sha256,
                last_deep_verified_at=record.last_deep_verified_at,
                identified=previous.puid is not None,
                structural_status=previous.structural_status,
                readability_status=previous.readability_status,
                change_kind=previous.change_kind,
                signature_version=previous_run.signature_version if previous_run else None,
                policy_version=previous_run.policy_version if previous_run else None,
            )
        return plan_file(
            state,
            CurrentStat(record.size, record.mtime_ns),
            PlanContext(
                mode=run.mode,
                force_deep_all=run.force_deep_all,
                now=now,
                deep_interval_days=self.settings.deep_verification_interval_days,
                signature_version=run.signature_version,
                policy_version=run.policy_version,
            ),
        )

    def _identify_batch(
        self,
        records: list[FileRecord],
        plans: dict[int, WorkPlan],
        root: Path,
        run: AuditRun,
        token: CancellationToken,
    ) -> dict[int, IdentificationOutcome]:
        selected = [
            record for record in records if WorkStep.IDENTIFY in plans[record.id or 0].steps
        ]
        if not selected:
            return {}
        if self.siegfried is None:
            return {record.id or 0: IdentificationOutcome(False, None, None) for record in selected}
        paths = [root / record.relative_path for record in selected]
        try:
            identified = self.siegfried.identify(paths, cancel=token)
        except (SiegfriedError, ToolNotFoundError, OSError):
            logger.warning("Siegfried identification failed for a batch")
            return {
                record.id or 0: IdentificationOutcome(False, None, run.signature_version)
                for record in selected
            }
        return {
            record.id or 0: IdentificationOutcome(
                True,
                identified.get(str(root / record.relative_path)),
                run.signature_version,
            )
            for record in selected
        }

    def _work_one(
        self,
        record: FileRecord,
        root: Path,
        plan: WorkPlan,
        previous: Observation | None,
        identification: IdentificationOutcome | None,
        token: CancellationToken,
    ) -> FileWorkResult:
        path = root / record.relative_path
        try:
            result = os.stat(extended_path(path))
        except FileNotFoundError:
            return FileWorkResult(
                record,
                plan,
                CurrentStat(record.size, record.mtime_ns),
                identification,
                None,
                None,
                "file vanished before processing",
                True,
            )
        current = CurrentStat(result.st_size, result.st_mtime_ns)
        hashed = None
        validation = None
        try:
            if WorkStep.HASH in plan.steps:
                hashed = hash_file(path, buffer_size=self.settings.hash_buffer_size, cancel=token)
                with self._hash_lock:
                    self._bytes_hashed += hashed.bytes_read
            if WorkStep.QUICK_STRUCTURE in plan.steps or WorkStep.DEEP_VALIDATE in plan.steps:
                puid = (
                    identification.result.best_match.puid
                    if identification and identification.result and identification.result.best_match
                    else previous.puid
                    if previous is not None and plan.reuse_previous_identification
                    else None
                )
                mime = (
                    identification.result.best_match.mime
                    if identification and identification.result and identification.result.best_match
                    else previous.mime_type
                    if previous is not None
                    else None
                )
                validator, _ = self.validators.resolve(
                    puid=puid,
                    extension=extension_of(record.relative_path),
                    mime=mime,
                )
                depth = (
                    ValidationDepth.DEEP
                    if WorkStep.DEEP_VALIDATE in plan.steps
                    else ValidationDepth.QUICK
                )
                if isinstance(validator, FFmpegMediaValidator):
                    with self._media_semaphore:
                        validation = validator.validate(path, depth=depth, cancel=token)
                else:
                    validation = validator.validate(path, depth=depth, cancel=token)
        except OperationCancelled:
            raise
        except Exception as exc:
            return FileWorkResult(
                record,
                plan,
                current,
                identification,
                hashed,
                validation,
                repr(exc),
                False,
            )
        return FileWorkResult(
            record,
            plan,
            current,
            identification,
            hashed,
            validation,
            None,
            False,
        )

    def _finalize(
        self,
        run: AuditRun,
        root: Path,
        started: float,
        estimator: EtaEstimator,
        callback: Callable[[AuditProgress], None] | None,
    ) -> AuditRun:
        self._emit(run, AuditStage.FINALIZING, started, estimator, None, callback)
        now = self.clock()
        added = 0
        with self.db.session() as session:
            files = FileRecordRepository(session)
            observations = ObservationRepository(session)
            findings = FindingRepository(session)
            missing = files.mark_missing_not_seen(run.archive_id, run.id or 0)
            existing = findings.open_for_files([record.id or 0 for record in missing])
            for record in missing:
                moved_to = None
                if run.mode is AuditMode.DEEP and record.last_sha256:
                    candidates = files.find_new_in_run_by_hash(
                        run.archive_id,
                        run.id or 0,
                        record.last_sha256,
                        record.size,
                    )
                    if candidates:
                        moved_to = candidates[0]
                        observations.update_change_kind(
                            moved_to.id or 0, run.id or 0, ChangeKind.MOVED
                        )
                text = finding_text(FindingCode.FILE_MISSING)
                finding = Finding(
                    file_record_id=record.id,
                    audit_run_id=run.id or 0,
                    code=FindingCode.FILE_MISSING.value,
                    severity=FindingSeverity.INFO if moved_to else FindingSeverity.MEDIUM,
                    category=FindingCategory.FILE_MISSING,
                    title="File appears to have moved" if moved_to else text.title,
                    description=text.description(),
                    evidence={
                        "previous_path": record.relative_path,
                        "new_path": moved_to.relative_path if moved_to else None,
                    },
                    created_at=now,
                    resolved_at=None,
                )
                result = reconcile(existing.get(record.id or 0, []), [finding], now)
                findings.add_batch(result.to_add)
                findings.resolve_ids(result.to_resolve_ids, now)
                findings.update_batch(result.to_update)
                added += len(result.to_add)
            if run.mode is AuditMode.DEEP:
                for sha256, size, records in files.duplicate_groups(run.archive_id):
                    first = records[0]
                    text = finding_text(FindingCode.DUPLICATE_CONTENT)
                    finding = Finding(
                        file_record_id=first.id,
                        audit_run_id=run.id or 0,
                        code=FindingCode.DUPLICATE_CONTENT.value,
                        severity=FindingSeverity.INFO,
                        category=FindingCategory.DUPLICATE,
                        title=f"{len(records)} byte-identical copies detected",
                        description=text.description(),
                        evidence={
                            "sha256": sha256,
                            "size": size,
                            "paths": [record.relative_path for record in records],
                        },
                        created_at=now,
                        resolved_at=None,
                    )
                    old = findings.open_for_file(first.id or 0)
                    result = reconcile(old, [finding], now)
                    findings.add_batch(result.to_add)
                    findings.resolve_ids(result.to_resolve_ids, now)
                    findings.update_batch(result.to_update)
                    added += len(result.to_add)
            added += self._add_tool_findings(findings, run, now)
            total_findings = len(findings.list(run_id=run.id))
            updated = AuditRunRepository(session).update(
                run.id or 0,
                status=AuditStatus.COMPLETED,
                completed_at=now,
                findings_count=total_findings,
                resume_state={**run.resume_state, "finalized": True},
            )
            ArchiveRepository(session).update_last_seen(run.archive_id, now)
            assert updated is not None
            run = updated
        self._emit(run, AuditStage.COMPLETED, started, estimator, None, callback)
        return run

    def _add_tool_findings(
        self, repository: FindingRepository, run: AuditRun, now: datetime
    ) -> int:
        additions: list[Finding] = []
        identification_failures = int(run.resume_state.get("identification_failures", 0))
        if identification_failures:
            missing = self.siegfried is None
            title = (
                "Siegfried is not installed"
                if missing
                else "Format identification was unavailable during this audit"
            )
            observed = (
                f"Siegfried is not installed; {identification_failures} files were not identified"
                if missing
                else (
                    f"Format identification was unavailable during this audit; "
                    f"{identification_failures} files were not identified"
                )
            )
            additions.append(
                self._run_finding(
                    run,
                    now,
                    title,
                    observed,
                    {"count": identification_failures, "tool": "siegfried"},
                )
            )
        ffmpeg_failures = int(run.resume_state.get("ffmpeg_failures", 0))
        if ffmpeg_failures:
            missing = self.ffmpeg is None
            title = (
                "FFmpeg is not installed"
                if missing
                else "Media probing was unavailable during this audit"
            )
            observed = (
                f"FFmpeg is not installed; {ffmpeg_failures} media files were not validated"
                if missing
                else (
                    f"Media probing was unavailable during this audit; "
                    f"{ffmpeg_failures} media files were not validated"
                )
            )
            additions.append(
                self._run_finding(
                    run,
                    now,
                    title,
                    observed,
                    {"count": ffmpeg_failures, "tool": "ffmpeg"},
                )
            )
        desired = {str(finding.evidence.get("tool")): finding for finding in additions}
        existing_by_tool: dict[str, list[Finding]] = {}
        for finding in repository.current_run_level_for_archive(run.archive_id):
            if finding.code == FindingCode.TOOL_UNAVAILABLE.value:
                existing_by_tool.setdefault(str(finding.evidence.get("tool")), []).append(finding)
        added = 0
        for tool in set(existing_by_tool) | set(desired):
            existing = existing_by_tool.get(tool, [])
            primary = existing[:1]
            duplicate_ids = [finding.id for finding in existing[1:] if finding.id is not None]
            result = reconcile(primary, [desired[tool]] if tool in desired else [], now)
            repository.add_batch(result.to_add)
            repository.resolve_ids([*duplicate_ids, *result.to_resolve_ids], now)
            repository.update_batch(result.to_update)
            added += len(result.to_add)
        return added

    @staticmethod
    def _run_finding(
        run: AuditRun,
        now: datetime,
        title: str,
        observed: str,
        evidence: dict[str, Any],
    ) -> Finding:
        text = finding_text(FindingCode.TOOL_UNAVAILABLE)
        return Finding(
            file_record_id=None,
            audit_run_id=run.id or 0,
            code=FindingCode.TOOL_UNAVAILABLE.value,
            severity=FindingSeverity.MEDIUM,
            category=FindingCategory.VALIDATION_UNAVAILABLE,
            title=title,
            description=text.description(observed),
            evidence=evidence,
            created_at=now,
            resolved_at=None,
        )

    def _increment_resume_counter(self, run_id: int, key: str, count: int) -> None:
        with self.db.session() as session:
            repository = AuditRunRepository(session)
            run = repository.get(run_id)
            if run is None:
                return
            state = dict(run.resume_state)
            state[key] = int(state.get(key, 0)) + count
            repository.update(run_id, resume_state=state)

    def _interrupt(self, run: AuditRun, reason: str) -> AuditRun:
        with self.db.session() as session:
            updated = AuditRunRepository(session).update(
                run.id or 0,
                status=AuditStatus.INTERRUPTED,
                interruption_reason=reason,
            )
            assert updated is not None
            return updated

    def _stop(self, run_id: int, status: AuditStatus, reason: str) -> AuditRun:
        with self.db.session() as session:
            updated = AuditRunRepository(session).update(
                run_id,
                status=status,
                completed_at=self.clock() if status is AuditStatus.CANCELLED else None,
                interruption_reason=reason,
            )
            assert updated is not None
            return updated

    def _emit(
        self,
        run: AuditRun,
        stage: AuditStage,
        started: float,
        estimator: EtaEstimator,
        current_path: str | None,
        callback: Callable[[AuditProgress], None] | None,
        files_processed_override: int | None = None,
    ) -> None:
        if callback is None or run.id is None:
            return
        elapsed = time.monotonic() - started
        processed = (
            run.files_processed if files_processed_override is None else files_processed_override
        )
        eta = estimator.update(processed, run.files_discovered, elapsed)
        callback(
            AuditProgress(
                run_id=run.id,
                stage=stage,
                files_discovered=run.files_discovered,
                files_total_estimate=run.files_discovered,
                files_processed=processed,
                files_failed=run.files_failed,
                files_skipped=run.files_skipped,
                findings_count=run.findings_count,
                current_path=current_path,
                elapsed_seconds=elapsed,
                bytes_hashed=self._bytes_hashed,
                estimated_remaining_seconds=eta,
            )
        )

    def _tool_versions(self) -> dict[str, str]:
        siegfried_version = "not installed"
        if self.siegfried is not None:
            with suppress(SiegfriedError, ToolNotFoundError, OSError):
                siegfried_version = self.siegfried.info().version
        return {
            "siegfried": siegfried_version,
            "ffmpeg": (self.ffmpeg.version() or "not installed")
            if self.ffmpeg
            else "not installed",
            "pillow": pillow_version,
            "pikepdf": pikepdf.__version__,
            "pypdf": pypdf.__version__,
            "python": platform.python_version(),
        }
