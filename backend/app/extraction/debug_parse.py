"""CLI utility to debug document parsing and inspection.

Usage:
    python -m app.extraction.debug_parse <document_id>
"""

import sys
import uuid

from app.core.database import SessionLocal
from app.extraction.constants import ExtractionError
from app.extraction.image_parser import parse_image
from app.extraction.pdf_parser import parse_pdf
from app.extraction.spreadsheet_parser import parse_csv, parse_xlsx
from app.models.document import Document
from app.schemas.parser import ParsedDocument
from app.storage.interface import LocalStorageService


def run_debug_parse(document_id_str: str) -> int:
    """Parse a document and print structured summary to stdout."""
    try:
        doc_uuid = uuid.UUID(document_id_str)
    except ValueError:
        print(f"Error: Invalid document UUID '{document_id_str}'", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            print(
                f"Error: Document with ID '{document_id_str}' not found in database",
                file=sys.stderr,
            )
            return 1

        storage = LocalStorageService()
        try:
            file_bytes = storage.get_file(doc.storage_key)
        except (OSError, ValueError) as exc:
            print(f"Error: Failed to retrieve file from storage: {exc}", file=sys.stderr)
            return 1

        filename = doc.original_filename or "unknown"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        media_type = doc.media_type or "application/octet-stream"

        parsed: ParsedDocument
        if ext == "pdf":
            parsed = parse_pdf(
                file_bytes, document_id=str(doc.id), filename=filename, media_type=media_type
            )
        elif ext == "xlsx":
            parsed = parse_xlsx(
                file_bytes, document_id=str(doc.id), filename=filename, media_type=media_type
            )
        elif ext == "csv":
            parsed = parse_csv(
                file_bytes, document_id=str(doc.id), filename=filename, media_type=media_type
            )
        elif ext in ("png", "jpg", "jpeg"):
            parsed = parse_image(
                file_bytes, document_id=str(doc.id), filename=filename, media_type=media_type
            )
        else:
            print(f"Error: Unsupported file format '{ext}' for parsing", file=sys.stderr)
            return 1

        print("=" * 60)
        print("PROCUREMIND DETERMINISTIC PARSER SUMMARY")
        print("=" * 60)
        print(f"Document ID   : {parsed.document_id}")
        print(f"Filename      : {parsed.filename}")
        print(f"Media Type    : {parsed.media_type}")
        print(f"Parse Method  : {parsed.parse_method.value}")
        print(f"Page Count    : {parsed.page_count}")
        print(f"Text Blocks   : {parsed.total_text_blocks}")
        print(f"Tables/Sheets : {parsed.total_tables}")

        if parsed.pages:
            print("\n--- Pages Overview ---")
            for p in parsed.pages:
                print(
                    f"  Page {p.page_number}: source={p.source.value}, "
                    f"dimensions={p.width}x{p.height}, "
                    f"blocks={len(p.text_blocks)}, tables={len(p.tables)}"
                )

        if parsed.sheets:
            print("\n--- Sheets Overview ---")
            for s in parsed.sheets:
                print(f"  Sheet '{s.name}': rows={s.row_count}, columns={s.column_count}")

        if parsed.warnings:
            print("\n--- Warnings ---")
            for w in parsed.warnings:
                print(f"  - {w}")

        print("=" * 60)
        print("Parsing completed successfully.")
        return 0

    except ExtractionError as e:
        print(f"Extraction error: {e.safe_detail}", file=sys.stderr)
        return 1
    except (ValueError, TypeError, OSError) as e:
        print(f"Extraction processing error: {type(e).__name__}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.extraction.debug_parse <document_id>", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_debug_parse(sys.argv[1]))
