"""
Compass — Career Copilot Database Access Repository.

Manages persistence for Resume Studio (master resumes, tailored variants, validation reports)
and Application Center (applications, batches, submission audit logs).
Features graceful in-memory fallback with cooldown retry for resilient PostgreSQL connectivity,
material modification invalidation for approved applications/batches, and explicit persistence status.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from backend.memory.db import get_pool as _raw_get_pool
from backend.models_career import (
    CareerApplicationOut,
    CareerApplicationStatus,
    OriginalResumeDocument,
    ResumeContent,
    ResumeOut,
    ResumeValidationReport,
    ResumeValidationStatus,
    SubmissionMethod,
)

logger = logging.getLogger("compass.memory.career")

_in_memory_resumes: Dict[int, Dict[str, Any]] = {}
_in_memory_original_resumes: Dict[str, Dict[str, Any]] = {}
_in_memory_applications: Dict[int, Dict[str, Any]] = {}
_in_memory_batches: Dict[str, Dict[str, Any]] = {}
_in_memory_events: List[Dict[str, Any]] = []
_resume_id_seq = 2000
_app_id_seq = 3000

_db_pool_available: bool = True
_last_db_failure_time: float = 0.0
_DB_RETRY_INTERVAL_SEC: float = 10.0


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return database pool with cooldown retry instead of permanent latch."""
    global _db_pool_available, _last_db_failure_time
    now = time.monotonic()
    if not _db_pool_available:
        if now - _last_db_failure_time < _DB_RETRY_INTERVAL_SEC:
            return None
        _db_pool_available = True
    try:
        pool = await asyncio.wait_for(_raw_get_pool(), timeout=8.0)
        if pool is not None:
            _db_pool_available = True
            return pool
        else:
            _db_pool_available = False
            _last_db_failure_time = now
            return None
    except Exception as e:
        _db_pool_available = False
        _last_db_failure_time = now
        logger.info(f"Database pool unavailable ({e}); switching Career Copilot to in-memory storage (retry in {_DB_RETRY_INTERVAL_SEC}s).")
        return None


def _parse_resume_row(row: Dict[str, Any], is_persisted: bool = True) -> ResumeOut:
    content_raw = row["content"] if isinstance(row["content"], dict) else json.loads(row["content"] or "{}")
    report_raw = row["validation_report"] if isinstance(row["validation_report"], dict) else json.loads(row["validation_report"] or "{}")
    status_raw = str(row.get("validation_status") or "DRAFT").strip()
    try:
        val_status = ResumeValidationStatus(status_raw)
    except (ValueError, TypeError):
        val_status = ResumeValidationStatus.DRAFT
    return ResumeOut(
        id=row["id"],
        user_id=row["user_id"],
        opportunity_id=row.get("opportunity_id"),
        is_master=bool(row.get("is_master", False)),
        title=row["title"],
        version=row.get("version", 1),
        content=ResumeContent(**content_raw),
        cover_letter=row.get("cover_letter"),
        validation_status=val_status,
        validation_report=ResumeValidationReport(**report_raw),
        is_persisted=is_persisted,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _parse_app_row(row: Dict[str, Any], is_persisted: bool = True) -> CareerApplicationOut:
    form_answers = row["form_answers"] if isinstance(row["form_answers"], dict) else json.loads(row["form_answers"] or "{}")
    sub_payload = row["submission_payload"] if isinstance(row["submission_payload"], dict) else json.loads(row["submission_payload"] or "{}")
    sub_result = row["submission_result"] if isinstance(row["submission_result"], dict) else json.loads(row["submission_result"] or "{}")

    return CareerApplicationOut(
        id=row["id"],
        user_id=row["user_id"],
        opportunity_id=row["opportunity_id"],
        resume_id=row.get("resume_id"),
        cover_letter=row.get("cover_letter"),
        status=CareerApplicationStatus(row.get("status", "SAVED")),
        submission_method=SubmissionMethod(row.get("submission_method", "manual_handoff")),
        form_answers=form_answers,
        submission_payload=sub_payload,
        submission_result=sub_result,
        batch_id=row.get("batch_id"),
        approved_at=row.get("approved_at"),
        submitted_at=row.get("submitted_at"),
        target_deadline=row.get("target_deadline"),
        private_notes=row.get("private_notes"),
        is_persisted=is_persisted,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ===========================================================================
# 1. Resume Studio Persistence
# ===========================================================================

async def get_master_resume(user_id: str) -> Optional[ResumeOut]:
    pool = await get_pool()
    if not pool:
        for r in _in_memory_resumes.values():
            if r["user_id"] == user_id and r.get("is_master"):
                return _parse_resume_row(r, is_persisted=False)
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM resumes WHERE user_id = $1 AND is_master IS TRUE ORDER BY updated_at DESC, id DESC LIMIT 1",
            user_id,
        )
        return _parse_resume_row(dict(row), is_persisted=True) if row else None


async def upsert_master_resume(user_id: str, content: ResumeContent, title: str = "Master Resume") -> ResumeOut:
    global _resume_id_seq
    pool = await get_pool()
    content_dict = content.model_dump()

    if not pool:
        from backend.services.career_resume import validate_resume_against_master
        init_report = validate_resume_against_master(content, content)
        report_dict = init_report.model_dump()
        status_val = "APPROVED" if init_report.is_valid else "DRAFT"

        for r in _in_memory_resumes.values():
            if r["user_id"] == user_id and r.get("is_master"):
                r["title"] = title
                r["content"] = content_dict
                r["version"] = r.get("version", 1) + 1
                r["validation_status"] = status_val
                r["validation_report"] = report_dict
                r["updated_at"] = datetime.now(timezone.utc)
                result = _parse_resume_row(r, is_persisted=False)
                try:
                    from backend.memory.radar import sync_candidate_profile_from_master
                    await sync_candidate_profile_from_master(user_id, content)
                except Exception as e:
                    logger.debug(f"Candidate profile sync omitted: {e}")
                return result
        _resume_id_seq += 1
        record = {
            "id": _resume_id_seq,
            "user_id": user_id,
            "opportunity_id": None,
            "is_master": True,
            "title": title,
            "version": 1,
            "content": content_dict,
            "validation_status": status_val,
            "validation_report": report_dict,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        _in_memory_resumes[_resume_id_seq] = record
        result = _parse_resume_row(record, is_persisted=False)
        try:
            from backend.memory.radar import sync_candidate_profile_from_master
            await sync_candidate_profile_from_master(user_id, content)
        except Exception as e:
            logger.debug(f"Candidate profile sync omitted: {e}")
        return result

    async with pool.acquire() as conn:
        from backend.services.career_resume import validate_resume_against_master
        init_report = validate_resume_against_master(content, content)
        report_dict = init_report.model_dump()
        status_val = "APPROVED" if init_report.is_valid else "DRAFT"

        existing = await conn.fetchrow(
            "SELECT id, version FROM resumes WHERE user_id = $1 AND is_master IS TRUE ORDER BY updated_at DESC, id DESC LIMIT 1",
            user_id,
        )
        if existing:
            row = await conn.fetchrow(
                """
                UPDATE resumes
                SET title = $2,
                    content = $3::jsonb,
                    validation_status = $4,
                    validation_report = $5::jsonb,
                    version = version + 1,
                    updated_at = now()
                WHERE id = $1
                RETURNING *;
                """,
                existing["id"],
                title,
                json.dumps(content_dict),
                status_val,
                json.dumps(report_dict),
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO resumes (user_id, is_master, title, version, content, validation_status, validation_report, created_at, updated_at)
                VALUES ($1, TRUE, $2, 1, $3::jsonb, $4, $5::jsonb, now(), now())
                RETURNING *;
                """,
                user_id,
                title,
                json.dumps(content_dict),
                status_val,
                json.dumps(report_dict),
            )
        result = _parse_resume_row(dict(row), is_persisted=True)
        try:
            from backend.memory.radar import sync_candidate_profile_from_master
            await sync_candidate_profile_from_master(user_id, content)
        except Exception as e:
            logger.debug(f"Candidate profile sync omitted: {e}")
        return result


async def create_tailored_resume(
    user_id: str,
    opportunity_id: Optional[int],
    title: str,
    content: ResumeContent,
    validation_report: ResumeValidationReport,
    validation_status: ResumeValidationStatus,
    cover_letter: Optional[str] = None,
) -> ResumeOut:
    global _resume_id_seq
    safe_opp_id = opportunity_id if (opportunity_id and opportunity_id > 0) else None
    pool = await get_pool()
    content_dict = content.model_dump()
    report_dict = validation_report.model_dump()

    if not pool:
        _resume_id_seq += 1
        record = {
            "id": _resume_id_seq,
            "user_id": user_id,
            "opportunity_id": safe_opp_id,
            "is_master": False,
            "title": title,
            "version": 1,
            "content": content_dict,
            "cover_letter": cover_letter,
            "validation_status": validation_status.value,
            "validation_report": report_dict,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        _in_memory_resumes[_resume_id_seq] = record
        return _parse_resume_row(record, is_persisted=False)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO resumes (
                user_id, opportunity_id, is_master, title, version, content, cover_letter, validation_status, validation_report, created_at, updated_at
            ) VALUES ($1, $2, FALSE, $3, 1, $4::jsonb, $5, $6, $7::jsonb, now(), now())
            RETURNING *;
            """,
            user_id,
            safe_opp_id,
            title,
            json.dumps(content_dict),
            cover_letter,
            validation_status.value,
            json.dumps(report_dict),
        )
        return _parse_resume_row(dict(row), is_persisted=True)


async def save_original_resume_document(
    user_id: str,
    filename: str,
    file_type: str,
    raw_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> OriginalResumeDocument:
    """Preserves raw original uploaded resume file text separately from generated resumes."""
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    rec = {
        "id": doc_id,
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "raw_text": raw_text,
        "uploaded_at": now,
        "metadata": metadata or {},
    }
    _in_memory_original_resumes[doc_id] = rec

    pool = await get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO original_resume_documents (id, user_id, filename, file_type, raw_text, metadata, uploaded_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    ON CONFLICT (id) DO UPDATE SET raw_text = EXCLUDED.raw_text, metadata = EXCLUDED.metadata;
                    """,
                    doc_id,
                    user_id,
                    filename,
                    file_type,
                    raw_text,
                    json.dumps(metadata or {}),
                    now,
                )
        except Exception as e:
            logger.warning(f"Database error saving original resume doc ({e}); preserved in memory store.")

    return OriginalResumeDocument(**rec)


async def get_original_resume_document(doc_id: str, user_id: str) -> Optional[OriginalResumeDocument]:
    """Retrieve original uploaded document by id ensuring tenant isolation."""
    pool = await get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM original_resume_documents WHERE id = $1 AND user_id = $2",
                    doc_id,
                    user_id,
                )
                if row:
                    meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
                    return OriginalResumeDocument(
                        id=row["id"],
                        user_id=row["user_id"],
                        filename=row["filename"],
                        file_type=row["file_type"],
                        raw_text=row["raw_text"],
                        uploaded_at=row["uploaded_at"],
                        metadata=meta,
                    )
        except Exception:
            pass

    rec = _in_memory_original_resumes.get(doc_id)
    if rec and rec["user_id"] == user_id:
        return OriginalResumeDocument(**rec)
    return None


async def list_original_resume_documents(user_id: str) -> List[OriginalResumeDocument]:
    """List all original uploaded resume documents for a user."""
    pool = await get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM original_resume_documents WHERE user_id = $1 ORDER BY uploaded_at DESC",
                    user_id,
                )
                if rows:
                    res = []
                    for row in rows:
                        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
                        res.append(
                            OriginalResumeDocument(
                                id=row["id"],
                                user_id=row["user_id"],
                                filename=row["filename"],
                                file_type=row["file_type"],
                                raw_text=row["raw_text"],
                                uploaded_at=row["uploaded_at"],
                                metadata=meta,
                            )
                        )
                    return res
        except Exception:
            pass

    return [
        OriginalResumeDocument(**r)
        for r in _in_memory_original_resumes.values()
        if r["user_id"] == user_id
    ]


async def get_resume_by_id(resume_id: int, user_id: str) -> Optional[ResumeOut]:
    pool = await get_pool()
    if not pool:
        record = _in_memory_resumes.get(resume_id)
        if record and record["user_id"] == user_id:
            return _parse_resume_row(record, is_persisted=False)
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM resumes WHERE id = $1 AND user_id = $2", resume_id, user_id)
        return _parse_resume_row(dict(row), is_persisted=True) if row else None


async def list_resumes(user_id: str) -> List[ResumeOut]:
    pool = await get_pool()
    if not pool:
        return [
            _parse_resume_row(r, is_persisted=False)
            for r in _in_memory_resumes.values()
            if r["user_id"] == user_id
        ]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM resumes WHERE user_id = $1 ORDER BY is_master DESC, updated_at DESC",
            user_id,
        )
        return [_parse_resume_row(dict(r), is_persisted=True) for r in rows]


async def update_resume(resume_id: int, user_id: str, updates: Dict[str, Any]) -> Optional[ResumeOut]:
    pool = await get_pool()
    content_val = updates.get("content")
    content_json = (
        json.dumps(content_val.model_dump() if hasattr(content_val, "model_dump") else content_val)
        if content_val is not None
        else None
    )

    report_val = updates.get("validation_report")
    report_json = (
        json.dumps(report_val.model_dump() if hasattr(report_val, "model_dump") else report_val)
        if report_val is not None
        else None
    )

    if not pool:
        record = _in_memory_resumes.get(resume_id)
        if record and record["user_id"] == user_id:
            safe_updates = dict(updates)
            if content_val is not None and hasattr(content_val, "model_dump"):
                safe_updates["content"] = content_val.model_dump()
            if report_val is not None and hasattr(report_val, "model_dump"):
                safe_updates["validation_report"] = report_val.model_dump()
            record.update(safe_updates)
            record["updated_at"] = datetime.now(timezone.utc)
            return _parse_resume_row(record, is_persisted=False)
        return None

    has_cover_letter = "cover_letter" in updates
    cover_letter_val = updates.get("cover_letter")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE resumes SET
                title = COALESCE($3, title),
                content = COALESCE($4::jsonb, content),
                validation_status = COALESCE($5, validation_status),
                validation_report = COALESCE($6::jsonb, validation_report),
                cover_letter = CASE WHEN $7::boolean THEN $8 ELSE cover_letter END,
                updated_at = now()
            WHERE id = $1 AND user_id = $2
            RETURNING *;
            """,
            resume_id,
            user_id,
            updates.get("title"),
            content_json,
            updates.get("validation_status"),
            report_json,
            has_cover_letter,
            cover_letter_val,
        )
        return _parse_resume_row(dict(row), is_persisted=True) if row else None


# ===========================================================================
# 2. Application Center Persistence
# ===========================================================================

async def get_or_create_career_application(user_id: str, opportunity_id: int) -> CareerApplicationOut:
    global _app_id_seq
    pool = await get_pool()
    if not pool:
        for a in _in_memory_applications.values():
            if a["user_id"] == user_id and a["opportunity_id"] == opportunity_id:
                return _parse_app_row(a, is_persisted=False)
        _app_id_seq += 1
        record = {
            "id": _app_id_seq,
            "user_id": user_id,
            "opportunity_id": opportunity_id,
            "resume_id": None,
            "status": CareerApplicationStatus.SAVED.value,
            "submission_method": SubmissionMethod.MANUAL_HANDOFF.value,
            "form_answers": {},
            "submission_payload": {},
            "submission_result": {},
            "batch_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        _in_memory_applications[_app_id_seq] = record
        return _parse_app_row(record, is_persisted=False)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO career_applications (user_id, opportunity_id, status, created_at, updated_at)
            VALUES ($1, $2, 'SAVED', now(), now())
            ON CONFLICT (user_id, opportunity_id) DO UPDATE SET updated_at = now()
            RETURNING *;
            """,
            user_id,
            opportunity_id,
        )
        return _parse_app_row(dict(row), is_persisted=True)


async def get_career_application_by_id(app_id: int, user_id: str) -> Optional[CareerApplicationOut]:
    pool = await get_pool()
    if not pool:
        record = _in_memory_applications.get(app_id)
        if record and record["user_id"] == user_id:
            return _parse_app_row(record, is_persisted=False)
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM career_applications WHERE id = $1 AND user_id = $2", app_id, user_id)
        return _parse_app_row(dict(row), is_persisted=True) if row else None


async def get_career_application_by_opportunity(user_id: str, opportunity_id: int) -> Optional[CareerApplicationOut]:
    """Read-only lookup of an existing career application without creating records."""
    pool = await get_pool()
    if not pool:
        for a in _in_memory_applications.values():
            if a["user_id"] == user_id and a["opportunity_id"] == opportunity_id:
                return _parse_app_row(a, is_persisted=False)
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM career_applications WHERE user_id = $1 AND opportunity_id = $2",
            user_id,
            opportunity_id,
        )
        return _parse_app_row(dict(row), is_persisted=True) if row else None



async def list_career_applications(user_id: str, status: Optional[str] = None) -> List[CareerApplicationOut]:
    pool = await get_pool()
    if not pool:
        items = [a for a in _in_memory_applications.values() if a["user_id"] == user_id]
        if status:
            items = [a for a in items if a.get("status") == status]
        return [_parse_app_row(a, is_persisted=False) for a in items]

    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM career_applications WHERE user_id = $1 AND status = $2 ORDER BY updated_at DESC",
                user_id,
                status,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM career_applications WHERE user_id = $1 ORDER BY updated_at DESC",
                user_id,
            )
        return [_parse_app_row(dict(r), is_persisted=True) for r in rows]


async def update_career_application(app_id: int, user_id: str, updates: Dict[str, Any]) -> Optional[CareerApplicationOut]:
    pool = await get_pool()

    # Material modification detection: if reviewed content is modified, invalidate previous approval
    material_content_keys = {"cover_letter", "form_answers", "resume_id"}
    content_modified = any(k in updates for k in material_content_keys)

    if not pool:
        record = _in_memory_applications.get(app_id)
        if record and record["user_id"] == user_id:
            # If application was approved and content is modified, reset status to READY_FOR_REVIEW
            if content_modified and record.get("status") == CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value:
                if "status" not in updates:
                    updates["status"] = CareerApplicationStatus.READY_FOR_REVIEW.value
                updates["approved_at"] = None

                # Invalidate associated batch if any
                batch_id = record.get("batch_id")
                if batch_id and batch_id in _in_memory_batches:
                    _in_memory_batches[batch_id]["status"] = "DRAFT"
                    _in_memory_batches[batch_id]["approval_token"] = None
                    _in_memory_batches[batch_id]["approved_at"] = None
                    _in_memory_batches[batch_id]["updated_at"] = datetime.now(timezone.utc)

            record.update(updates)
            record["updated_at"] = datetime.now(timezone.utc)
            return _parse_app_row(record, is_persisted=False)
        return None

    async with pool.acquire() as conn:
        # Check current status if content modified
        if content_modified:
            curr = await conn.fetchrow(
                "SELECT status, batch_id FROM career_applications WHERE id = $1 AND user_id = $2",
                app_id,
                user_id,
            )
            if curr and curr["status"] == CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value:
                if "status" not in updates:
                    updates["status"] = CareerApplicationStatus.READY_FOR_REVIEW.value
                updates["approved_at"] = None

                batch_id = curr["batch_id"]
                if batch_id:
                    await conn.execute(
                        "UPDATE application_batches SET status = 'DRAFT', approval_token = NULL, approved_at = NULL, updated_at = now() WHERE id = $1 AND user_id = $2",
                        batch_id,
                        user_id,
                    )

        row = await conn.fetchrow(
            """
            UPDATE career_applications SET
                status = COALESCE($3, status),
                resume_id = COALESCE($4, resume_id),
                submission_method = COALESCE($5, submission_method),
                form_answers = COALESCE($6::jsonb, form_answers),
                submission_payload = COALESCE($7::jsonb, submission_payload),
                submission_result = COALESCE($8::jsonb, submission_result),
                batch_id = COALESCE($9, batch_id),
                approved_at = COALESCE($10, approved_at),
                submitted_at = COALESCE($11, submitted_at),
                target_deadline = COALESCE($12, target_deadline),
                private_notes = COALESCE($13, private_notes),
                cover_letter = COALESCE($14, cover_letter),
                updated_at = now()
            WHERE id = $1 AND user_id = $2
            RETURNING *;
            """,
            app_id,
            user_id,
            updates.get("status"),
            updates.get("resume_id"),
            updates.get("submission_method"),
            json.dumps(updates["form_answers"]) if "form_answers" in updates else None,
            json.dumps(updates["submission_payload"]) if "submission_payload" in updates else None,
            json.dumps(updates["submission_result"]) if "submission_result" in updates else None,
            updates.get("batch_id"),
            updates.get("approved_at"),
            updates.get("submitted_at"),
            updates.get("target_deadline"),
            updates.get("private_notes"),
            updates.get("cover_letter"),
        )
        return _parse_app_row(dict(row), is_persisted=True) if row else None


# ===========================================================================
# 3. Batch Review & Explicit Approval
# ===========================================================================

async def create_application_batch(user_id: str, app_ids: List[int]) -> str:
    batch_id = f"batch_{uuid.uuid4().hex[:10]}"
    pool = await get_pool()

    if not pool:
        _in_memory_batches[batch_id] = {
            "id": batch_id,
            "user_id": user_id,
            "application_ids": app_ids,
            "status": "DRAFT",
            "approval_token": None,
            "approved_at": None,
            "results": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        for aid in app_ids:
            if aid in _in_memory_applications and _in_memory_applications[aid]["user_id"] == user_id:
                _in_memory_applications[aid]["batch_id"] = batch_id
        return batch_id

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO application_batches (id, user_id, application_ids, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'DRAFT', now(), now());
            """,
            batch_id,
            user_id,
            app_ids,
        )
        await conn.execute(
            "UPDATE career_applications SET batch_id = $1 WHERE id = ANY($2::int[]) AND user_id = $3",
            batch_id,
            app_ids,
            user_id,
        )
        return batch_id


async def get_application_batch(batch_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        b = _in_memory_batches.get(batch_id)
        if b and b["user_id"] == user_id:
            res = dict(b)
            res["is_persisted"] = False
            return res
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM application_batches WHERE id = $1 AND user_id = $2", batch_id, user_id)
        if row:
            res = dict(row)
            res["is_persisted"] = True
            return res
        return None


async def approve_application_batch(batch_id: str, user_id: str, token: str) -> bool:
    pool = await get_pool()
    now_ts = datetime.now(timezone.utc)
    if not pool:
        b = _in_memory_batches.get(batch_id)
        if b and b["user_id"] == user_id:
            b["status"] = "APPROVED"
            b["approval_token"] = token
            b["approved_at"] = now_ts
            b["updated_at"] = now_ts
            for aid in b["application_ids"]:
                if aid in _in_memory_applications and _in_memory_applications[aid]["user_id"] == user_id:
                    _in_memory_applications[aid]["status"] = CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value
                    _in_memory_applications[aid]["approved_at"] = now_ts
                    _in_memory_applications[aid]["updated_at"] = now_ts
            return True
        return False

    async with pool.acquire() as conn:
        batch_row = await conn.fetchrow(
            """
            UPDATE application_batches SET
                status = 'APPROVED',
                approval_token = $3,
                approved_at = now(),
                updated_at = now()
            WHERE id = $1 AND user_id = $2
            RETURNING application_ids;
            """,
            batch_id,
            user_id,
            token,
        )
        if not batch_row:
            return False

        app_ids = batch_row["application_ids"]
        await conn.execute(
            """
            UPDATE career_applications SET
                status = 'APPROVED_FOR_SUBMISSION',
                approved_at = now(),
                updated_at = now()
            WHERE id = ANY($1::int[]) AND user_id = $2
            """,
            app_ids,
            user_id,
        )
        return True


async def claim_application_batch_for_submission(batch_id: str, user_id: str) -> bool:
    """
    Atomically claims an approved batch for submission across multi-worker environments.
    Guarantees that two concurrent requests or separate server worker processes cannot
    both acquire the submission lock for the same batch.
    Transitions status: 'APPROVED' -> 'SUBMITTING'.
    Returns True if successfully claimed, False if already claimed or not in APPROVED status.
    """
    pool = await get_pool()
    now_ts = datetime.now(timezone.utc)
    if not pool:
        b = _in_memory_batches.get(batch_id)
        if b and b["user_id"] == user_id and b.get("status") == "APPROVED":
            b["status"] = "SUBMITTING"
            b["updated_at"] = now_ts
            return True
        return False

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE application_batches
            SET status = 'SUBMITTING', updated_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'APPROVED'
            RETURNING id;
            """,
            batch_id,
            user_id,
        )
        return bool(row)


async def release_application_batch_claim(batch_id: str, user_id: str, reset_status: str = "APPROVED") -> bool:
    """Reverts a claimed SUBMITTING batch back to APPROVED if aborted prior to submission execution."""
    pool = await get_pool()
    now_ts = datetime.now(timezone.utc)
    if not pool:
        b = _in_memory_batches.get(batch_id)
        if b and b["user_id"] == user_id and b.get("status") == "SUBMITTING":
            b["status"] = reset_status
            b["updated_at"] = now_ts
            return True
        return False

    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE application_batches
            SET status = $3, updated_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'SUBMITTING'
            """,
            batch_id,
            user_id,
            reset_status,
        )
        return "UPDATE 1" in res


async def claim_career_application_for_submission(app_id: int, user_id: str) -> bool:
    """
    Atomically claims a career application for submission, transitioning it to SUBMITTING.
    Guarantees an application cannot be submitted concurrently twice across workers.
    """
    pool = await get_pool()
    now_ts = datetime.now(timezone.utc)
    if not pool:
        rec = _in_memory_applications.get(app_id)
        if rec and rec["user_id"] == user_id and rec.get("status") == CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value:
            rec["status"] = "SUBMITTING"
            rec["updated_at"] = now_ts
            return True
        return False

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE career_applications
            SET status = 'SUBMITTING', updated_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'APPROVED_FOR_SUBMISSION'
            RETURNING id;
            """,
            app_id,
            user_id,
        )
        return bool(row)


async def reconcile_stale_submission_claims(user_id: Optional[str] = None, max_age_seconds: int = 600) -> Dict[str, int]:
    """
    Reconciles stale submission claims where a worker process may have died or timed out mid-flight.
    Applications stuck in 'SUBMITTING' are marked 'SUBMISSION_OUTCOME_UNKNOWN' to prevent silent duplicate submissions.
    Batches stuck in 'SUBMITTING' are reverted to 'READY_FOR_REVIEW' requiring candidate verification.
    """
    pool = await get_pool()
    now_ts = datetime.now(timezone.utc)
    reconciled_apps = 0
    reconciled_batches = 0

    if not pool:
        for aid, rec in _in_memory_applications.items():
            if rec.get("status") == "SUBMITTING":
                if user_id is None or rec.get("user_id") == user_id:
                    updated_at = rec.get("updated_at") or rec.get("created_at") or now_ts
                    if (now_ts - updated_at).total_seconds() > max_age_seconds:
                        rec["status"] = CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value
                        rec["updated_at"] = now_ts
                        reconciled_apps += 1

        for bid, b in _in_memory_batches.items():
            if b.get("status") == "SUBMITTING":
                if user_id is None or b.get("user_id") == user_id:
                    updated_at = b.get("updated_at") or b.get("created_at") or now_ts
                    if (now_ts - updated_at).total_seconds() > max_age_seconds:
                        b["status"] = "READY_FOR_REVIEW"
                        b["approval_token"] = None
                        b["updated_at"] = now_ts
                        reconciled_batches += 1

        return {"reconciled_applications": reconciled_apps, "reconciled_batches": reconciled_batches}

    async with pool.acquire() as conn:
        # Reconcile applications in DB
        app_query = """
            UPDATE career_applications
            SET status = 'SUBMISSION_OUTCOME_UNKNOWN', updated_at = now()
            WHERE status = 'SUBMITTING'
              AND updated_at < now() - ($1 || ' seconds')::interval
        """
        params_app = [str(max_age_seconds)]
        if user_id:
            app_query += " AND user_id = $2"
            params_app.append(user_id)
        res_app = await conn.execute(app_query, *params_app)
        reconciled_apps = int(res_app.split()[-1]) if res_app else 0

        # Reconcile batches in DB
        batch_query = """
            UPDATE application_batches
            SET status = 'READY_FOR_REVIEW', approval_token = NULL, updated_at = now()
            WHERE status = 'SUBMITTING'
              AND updated_at < now() - ($1 || ' seconds')::interval
        """
        params_batch = [str(max_age_seconds)]
        if user_id:
            batch_query += " AND user_id = $2"
            params_batch.append(user_id)
        res_batch = await conn.execute(batch_query, *params_batch)
        reconciled_batches = int(res_batch.split()[-1]) if res_batch else 0

    return {"reconciled_applications": reconciled_apps, "reconciled_batches": reconciled_batches}


async def update_application_batch_status(batch_id: str, user_id: str, status: str) -> bool:
    """Updates batch status atomically (e.g. SUBMITTING, SUBMITTED)."""
    pool = await get_pool()
    if not pool:
        b = _in_memory_batches.get(batch_id)
        if b and b["user_id"] == user_id:
            b["status"] = status
            b["updated_at"] = datetime.now(timezone.utc)
            return True
        return False

    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE application_batches SET status = $1, updated_at = now() WHERE id = $2 AND user_id = $3",
            status,
            batch_id,
            user_id,
        )
        return "UPDATE 1" in res


async def finish_application_batch(batch_id: str, user_id: str, results: List[Dict[str, Any]]) -> str:
    all_manual = all(r.get("status") == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value for r in results) if results else False
    any_submitted = any(r.get("status") == CareerApplicationStatus.SUBMITTED.value for r in results)
    any_uncertain = any(r.get("status") == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value for r in results)
    any_failed = any(r.get("status") in {"FAILED", "BLOCKED", CareerApplicationStatus.SUBMISSION_FAILED.value} for r in results)

    if all_manual:
        final_status = "MANUAL_HANDOFF_GENERATED"
    elif any_submitted and not any_failed and not any_uncertain:
        final_status = "SUBMITTED"
    elif any_uncertain or any_failed:
        final_status = "PARTIALLY_SUBMITTED"
    else:
        final_status = "COMPLETED"

    pool = await get_pool()
    if not pool:
        if batch_id in _in_memory_batches:
            _in_memory_batches[batch_id]["results"] = results
            _in_memory_batches[batch_id]["status"] = final_status
            _in_memory_batches[batch_id]["updated_at"] = datetime.now(timezone.utc)
        return final_status

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE application_batches SET results = $1::jsonb, status = $2, updated_at = now() WHERE id = $3 AND user_id = $4",
            json.dumps(results),
            final_status,
            batch_id,
            user_id,
        )
    return final_status


async def log_application_event(application_id: int, event_type: str, details: Dict[str, Any]) -> None:
    pool = await get_pool()
    if not pool:
        _in_memory_events.append({
            "application_id": application_id,
            "event_type": event_type,
            "details": details,
            "created_at": datetime.now(timezone.utc),
        })
        return

    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM career_applications WHERE id = $1", application_id)
        if not exists:
            _in_memory_events.append({
                "application_id": application_id,
                "event_type": event_type,
                "details": details,
                "created_at": datetime.now(timezone.utc),
            })
            return

        await conn.execute(
            "INSERT INTO application_events (application_id, event_type, details, created_at) VALUES ($1, $2, $3::jsonb, now())",
            application_id,
            event_type,
            json.dumps(details),
        )
