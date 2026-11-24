"""
Compass — Career Profile Import API Router.

Provides authenticated, rate-limited file upload endpoint for candidate
profile auto-fill (LinkedIn Save to PDF, LinkedIn archive zip, CSV exports).
Files are read in-memory up to 25 MB and never persisted to disk.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from backend.dependencies import _get_or_create_user_id, rate_limit
from backend.models_career import ResumeContent
from backend.services.career_profile_sources import ingest_external_profile_file

router = APIRouter(prefix="/api/career", tags=["career_copilot"])

MAX_ALLOWED_FILE_BYTES = 25 * 1024 * 1024  # 25 MB


@router.post(
    "/intelligence/external-profile-file",
    response_model=ResumeContent,
    dependencies=[Depends(rate_limit)],
)
async def ingest_external_profile_file_endpoint(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Ingests candidate-provided external profile file (LinkedIn PDF export, data archive ZIP, or CSV).
    Never performs unauthorized scraping. Reads at most 25 MB in-memory and returns structured ResumeContent.
    """
    _get_or_create_user_id(request)

    # Read at most 25 MB + 1 byte to check size limit
    chunk = await file.read(MAX_ALLOWED_FILE_BYTES + 1)
    if len(chunk) > MAX_ALLOWED_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "That file is larger than 25 MB. In LinkedIn choose only Profile, Positions, "
                "Education, Skills and Certifications when you request your data, or use Save to PDF."
            ),
        )

    filename = file.filename or "uploaded_profile"
    content_type: Optional[str] = file.content_type

    try:
        content, _notes = await asyncio.to_thread(
            ingest_external_profile_file,
            chunk,
            filename=filename,
            content_type=content_type,
        )
        return content
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
