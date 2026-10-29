"""
Compass — Career Copilot Resume File Extraction Service.

Extracts structured resume data from uploaded PDF, TXT, and Markdown files.
Safely handles malformed, encrypted, empty, and image-only documents.
Never silently saves or overwrites the master resume without explicit user confirmation.
"""
from __future__ import annotations

import codecs
import io
import logging
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.models_career import ResumeContent
from backend.services.career_resume import analyze_extraction_diagnostics, parse_uploaded_resume_text

logger = logging.getLogger(__name__)

# Maximum file size: 5 MB
MAX_RESUME_FILE_SIZE = 5 * 1024 * 1024

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# Only the first pages of a PDF are parsed; a resume never needs more.
MAX_PDF_PAGES = 15
# Guards against zip-bomb style DOCX uploads (checked from zip metadata before opening).
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000


class ResumeParseResult(BaseModel):
    success: bool
    filename: str
    file_type: str
    raw_text: str = ""
    # Complete extracted text for server-side provenance storage; never sent to the client.
    full_text: str = Field(default="", exclude=True)
    extracted_content: Optional[ResumeContent] = None
    page_count: Optional[int] = None
    confidence_warning: Optional[str] = None
    error_message: Optional[str] = None
    requires_user_review: bool = True
    missing_fields: List[str] = Field(default_factory=list)
    ambiguous_fields: List[str] = Field(default_factory=list)
    field_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    field_confidence: Dict[str, float] = Field(default_factory=dict)
    links_detected: List[str] = Field(default_factory=list)
    original_document_id: Optional[str] = None


def is_pdf_parser_available() -> bool:
    """Check if pypdf or pdfplumber is installed and functional."""
    try:
        import pypdf
        return True
    except ImportError:
        try:
            import pdfplumber
            return True
        except ImportError:
            return False


def is_docx_parser_available() -> bool:
    """Check if python-docx is installed and functional."""
    try:
        import docx
        return True
    except ImportError:
        return False


def _decode_text_bytes(data: bytes) -> str:
    """Decode uploaded text: UTF-16 (BOM), UTF-8 (BOM stripped), else Windows-1252."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _check_docx_archive(file_bytes: bytes) -> Optional[str]:
    """Return an error message when the DOCX zip metadata looks like a zip bomb, else None."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        return None  # python-docx reports the malformed file with its own message
    if len(infos) > MAX_DOCX_ENTRIES:
        return f"DOCX file has too many entries ({len(infos)} entries; limit {MAX_DOCX_ENTRIES})."
    total = sum(info.file_size for info in infos)
    if total > MAX_DOCX_UNCOMPRESSED_BYTES:
        return (
            f"DOCX file expands to {total // (1024 * 1024)} MB uncompressed; "
            f"the limit is {MAX_DOCX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB."
        )
    return None


def _page_cap_warnings(total_pages: int) -> List[str]:
    if total_pages > MAX_PDF_PAGES:
        return [f"PDF has {total_pages} pages; only the first {MAX_PDF_PAGES} were parsed."]
    return []


def _decrypt_with_empty_password(reader: Any) -> bool:
    """Owner-password-only PDFs open with an empty user password; True when decryption worked."""
    try:
        return bool(reader.decrypt(""))
    except Exception as exc:
        logger.debug("PDF empty-password decrypt failed: %s", exc)
        return False


def _build_success_result(
    filename: str,
    file_type: str,
    full_text: str,
    page_count: Optional[int] = None,
    extra_warnings: Optional[List[str]] = None,
) -> ResumeParseResult:
    """Helper to assemble truthful extraction results with diagnostics."""
    parsed_content = parse_uploaded_resume_text(full_text)
    diag = analyze_extraction_diagnostics(parsed_content, full_text)
    extra = list(extra_warnings or [])
    warning = None
    if not parsed_content.skills and not parsed_content.education:
        warning = "Standard skills or education sections were not clearly identified. Please review the extracted data."
    elif diag.get("missing_fields"):
        warning = f"Missing fields detected: {', '.join(diag['missing_fields'])}."
    if extra:
        warning = " ".join([w for w in [warning, *extra] if w])
    field_confidence = dict(diag.get("field_confidence", {}))
    overall = float(diag.get("overall_confidence", 0.0))
    field_confidence["overall"] = overall
    field_confidence["overall_confidence"] = overall

    return ResumeParseResult(
        success=True,
        filename=filename,
        file_type=file_type,
        page_count=page_count,
        raw_text=full_text[:3000],
        full_text=full_text,
        extracted_content=parsed_content,
        confidence_warning=warning,
        requires_user_review=True,
        missing_fields=diag.get("missing_fields", []),
        ambiguous_fields=[*diag.get("ambiguous_fields", []), *extra],
        field_conflicts=diag.get("field_conflicts", []),
        field_confidence=field_confidence,
        links_detected=parsed_content.relevant_links,
    )


def _extract_pdf_with_pdfplumber(file_bytes: bytes, filename: str) -> ResumeParseResult:
    """Fallback PDF extraction when only pdfplumber is installed (pypdf missing)."""
    try:
        import pdfplumber

        chunks: List[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            total_pages = len(pdf.pages)
            for page in pdf.pages[:MAX_PDF_PAGES]:
                text = page.extract_text() or ""
                if text.strip():
                    chunks.append(text.strip())
        full_text = "\n\n".join(chunks).strip()
        if not full_text:
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".pdf",
                page_count=total_pages,
                error_message="PDF contains no extractable text. Please ensure the file contains selectable text.",
            )
        return _build_success_result(
            filename=filename,
            file_type=".pdf",
            full_text=full_text,
            page_count=total_pages,
            extra_warnings=_page_cap_warnings(total_pages),
        )
    except Exception as e:
        return ResumeParseResult(
            success=False,
            filename=filename,
            file_type=".pdf",
            error_message=f"Unexpected error parsing PDF file: {e}",
        )


def extract_resume_from_file_bytes(
    file_bytes: bytes,
    filename: str,
    content_type: Optional[str] = None,
) -> ResumeParseResult:
    """
    Safely extract and parse text from a resume file.

    Guarantees:
    - Validates size <= 5MB
    - Rejects unsupported binary formats (.docx, images, etc.) with explicit explanation
    - Handles malformed, corrupt, encrypted, empty, and image-only PDFs
    - Does NOT save or overwrite master resume; returns structured result for review
    """
    if not file_bytes:
        return ResumeParseResult(
            success=False,
            filename=filename,
            file_type="unknown",
            error_message="Uploaded file is empty (0 bytes).",
        )

    if len(file_bytes) > MAX_RESUME_FILE_SIZE:
        return ResumeParseResult(
            success=False,
            filename=filename,
            file_type="unknown",
            error_message=f"File exceeds maximum allowed size of 5 MB ({len(file_bytes)} bytes).",
        )

    # Determine extension
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return ResumeParseResult(
            success=False,
            filename=filename,
            file_type=ext or "unknown",
            error_message=(
                f"Unsupported file format '{ext}'. Supported formats are: PDF (.pdf), Word (.docx), Plain Text (.txt), Markdown (.md). "
                "Scanned image files require OCR."
            ),
        )

    # 1. Plain Text and Markdown
    if ext in {".txt", ".md"}:
        try:
            # Simple check to ensure it's not a binary file masquerading as text
            if len(file_bytes) > 0 and file_bytes[0] == 0x00:
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=ext,
                    error_message="File appears to be binary and cannot be read as text.",
                )
            text = _decode_text_bytes(file_bytes).strip()
            if not text:
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=ext,
                    error_message="File contains no readable text content.",
                )
            return _build_success_result(filename=filename, file_type=ext, full_text=text, page_count=1)
        except Exception as e:
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=ext,
                error_message=f"Failed to read text file: {e}",
            )

    # 2. Microsoft Word (.docx) Parsing
    if ext == ".docx":
        if not is_docx_parser_available():
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".docx",
                error_message="DOCX parser (python-docx) is not installed in the environment.",
            )
        import docx
        archive_error = _check_docx_archive(file_bytes)
        if archive_error:
            return ResumeParseResult(success=False, filename=filename, file_type=".docx", error_message=archive_error)
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = []
            for p in doc.paragraphs:
                txt = p.text.strip()
                if not txt:
                    continue
                style_name = (p.style.name if p.style else "").lower()
                if ("list" in style_name or "bullet" in style_name) and not txt.startswith(("•", "-", "*", "·")):
                    txt = "• " + txt
                paragraphs.append(txt)
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        paragraphs.append(row_text)
            full_text = "\n\n".join(paragraphs).strip()
            if not full_text:
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=".docx",
                    error_message="DOCX file contains no readable text content.",
                )
            return _build_success_result(filename=filename, file_type=".docx", full_text=full_text, page_count=None)
        except Exception as e:
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".docx",
                error_message=f"Malformed or corrupted DOCX file: {e}",
            )

    # 2. PDF Parsing via pypdf
    if ext == ".pdf":
        if not is_pdf_parser_available():
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".pdf",
                error_message="PDF parser (pypdf) is not installed in the environment.",
            )

        try:
            import pypdf
            import pypdf.errors
        except ImportError:
            return _extract_pdf_with_pdfplumber(file_bytes, filename)

        try:
            stream = io.BytesIO(file_bytes)
            reader = pypdf.PdfReader(stream)

            # Check encryption
            if reader.is_encrypted and not _decrypt_with_empty_password(reader):
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=".pdf",
                    error_message="PDF is password-protected or encrypted. Please upload an unprotected PDF.",
                )

            total_pages = len(reader.pages)
            if total_pages == 0:
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=".pdf",
                    error_message="PDF contains zero pages.",
                    page_count=0,
                )

            extracted_chunks = []
            has_images = False

            for idx, page in enumerate(reader.pages):
                if idx >= MAX_PDF_PAGES:
                    break
                try:
                    p_text = page.extract_text() or ""
                    if p_text.strip():
                        extracted_chunks.append(p_text.strip())
                    if hasattr(page, "images") and len(page.images) > 0:
                        has_images = True
                except Exception as page_err:
                    logger.warning("Error reading PDF page %d: %s", idx, page_err)

            if not extracted_chunks:
                try:
                    import pdfplumber
                    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                        for page in pdf.pages[:MAX_PDF_PAGES]:
                            t = page.extract_text() or ""
                            if t.strip():
                                extracted_chunks.append(t.strip())
                except Exception as plumber_err:
                    logger.debug("pdfplumber fallback attempt: %s", plumber_err)

            full_text = "\n\n".join(extracted_chunks).strip()

            # Detect image-only / scanned PDF
            if not full_text or len(full_text) < 20:
                if has_images:
                    return ResumeParseResult(
                        success=False,
                        filename=filename,
                        file_type=".pdf",
                        page_count=total_pages,
                        error_message=(
                            "PDF appears to be a scanned or image-only document. "
                            "Text could not be extracted without optical character recognition (OCR). "
                            "Please upload a text-based PDF or paste raw resume text."
                        ),
                    )
                return ResumeParseResult(
                    success=False,
                    filename=filename,
                    file_type=".pdf",
                    page_count=total_pages,
                    error_message="PDF contains no extractable text. Please ensure the file contains selectable text.",
                )

            # Parse structured content truthfully
            return _build_success_result(
                filename=filename,
                file_type=".pdf",
                full_text=full_text,
                page_count=total_pages,
                extra_warnings=_page_cap_warnings(total_pages),
            )

        except pypdf.errors.PdfReadError as pre:
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".pdf",
                error_message=f"Malformed or corrupted PDF file: {pre}",
            )
        except Exception as e:
            return ResumeParseResult(
                success=False,
                filename=filename,
                file_type=".pdf",
                error_message=f"Unexpected error parsing PDF file: {e}",
            )

    return ResumeParseResult(
        success=False,
        filename=filename,
        file_type=ext or "unknown",
        error_message=f"Unhandled or unsupported file format '{ext}'.",
    )
