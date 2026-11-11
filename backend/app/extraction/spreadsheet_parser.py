"""Deterministic spreadsheet parser for XLSX and CSV files with archive inspection and limits."""

import csv
import io
import logging
import zipfile

from app.core.config import settings
from app.extraction.constants import ExtractionError
from app.schemas.parser import (
    DocumentParseMethod,
    ParsedDocument,
    ParsedRow,
    ParsedSheet,
)

logger = logging.getLogger(__name__)

try:
    import openpyxl  # type: ignore[import-untyped,import-not-found]
except ImportError:
    openpyxl = None


def parse_xlsx(
    file_bytes: bytes,
    document_id: str,
    filename: str,
    media_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> ParsedDocument:
    """Parse XLSX files with pre-decompression ZIP safety checks and cell limits."""
    # 1. Pre-decompression ZIP archive inspection (Standard library zipfile, independent of openpyxl)
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > settings.PARSER_MAX_XLSX_ARCHIVE_BYTES:
                raise ExtractionError(
                    f"XLSX uncompressed archive size ({total_uncompressed} bytes) "
                    f"exceeds limit of {settings.PARSER_MAX_XLSX_ARCHIVE_BYTES} bytes",
                    safe_detail="Spreadsheet archive size limit exceeded",
                )
    except zipfile.BadZipFile as exc:
        logger.error("Corrupted or invalid XLSX archive")
        raise ExtractionError("Invalid or corrupted XLSX file") from exc

    if openpyxl is None:
        raise ExtractionError(
            "openpyxl is not installed",
            safe_detail="Spreadsheet parser dependency unavailable",
        )

    # 2. Load workbook with openpyxl
    try:
        # data_only=False preserves formula strings (e.g. '=SUM(A1:A10)')
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes),
            data_only=False,
            read_only=True,
        )
    except Exception as exc:
        logger.error("openpyxl failed to read workbook")
        raise ExtractionError("Corrupted spreadsheet workbook") from exc

    sheet_names = wb.sheetnames
    if len(sheet_names) > settings.PARSER_MAX_XLSX_SHEETS:
        wb.close()
        raise ExtractionError(
            f"XLSX sheet count ({len(sheet_names)}) exceeds limit of {settings.PARSER_MAX_XLSX_SHEETS}",
            safe_detail="Spreadsheet sheet count limit exceeded",
        )

    parsed_sheets: list[ParsedSheet] = []
    total_cells_processed = 0

    try:
        for sname in sheet_names:
            ws = wb[sname]
            rows: list[ParsedRow] = []
            max_col_seen = 0

            for row_idx, raw_row in enumerate(ws.iter_rows(values_only=True), start=1):
                if row_idx > settings.PARSER_MAX_XLSX_ROWS:
                    raise ExtractionError(
                        f"Sheet '{sname}' row count exceeds limit of {settings.PARSER_MAX_XLSX_ROWS}",
                        safe_detail="Spreadsheet row limit exceeded",
                    )

                # Trim row to max column limit
                if len(raw_row) > settings.PARSER_MAX_XLSX_COLS:
                    raise ExtractionError(
                        f"Sheet '{sname}' column count exceeds limit of {settings.PARSER_MAX_XLSX_COLS}",
                        safe_detail="Spreadsheet column limit exceeded",
                    )

                cell_values: list[str | None] = []
                for val in raw_row:
                    total_cells_processed += 1
                    if total_cells_processed > settings.PARSER_MAX_XLSX_CELLS:
                        raise ExtractionError(
                            f"Total spreadsheet cells exceeded limit of {settings.PARSER_MAX_XLSX_CELLS}",
                            safe_detail="Spreadsheet total cell limit exceeded",
                        )
                    if val is None:
                        cell_values.append(None)
                    else:
                        cell_values.append(str(val))

                max_col_seen = max(max_col_seen, len(cell_values))
                rows.append(ParsedRow(row_index=row_idx, cells=cell_values))

            parsed_sheets.append(
                ParsedSheet(
                    name=sname,
                    rows=rows,
                    row_count=len(rows),
                    column_count=max_col_seen,
                )
            )
    finally:
        wb.close()

    return ParsedDocument(
        document_id=document_id,
        filename=filename,
        media_type=media_type,
        parse_method=DocumentParseMethod.TEXT,
        page_count=len(parsed_sheets),
        pages=[],
        sheets=parsed_sheets,
        total_text_blocks=0,
        total_tables=len(parsed_sheets),
        warnings=[],
    )


def parse_csv(
    file_bytes: bytes,
    document_id: str,
    filename: str,
    media_type: str = "text/csv",
) -> ParsedDocument:
    """Parse CSV files using Python's standard csv library with bounded field and record limits."""
    # Validate and decode UTF-8 content
    try:
        text_content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text_content = file_bytes.decode("latin-1")
        except Exception as exc:
            logger.error("Failed to decode CSV text content")
            raise ExtractionError("Invalid text encoding in CSV document") from exc

    # Set field size limit
    csv.field_size_limit(settings.PARSER_MAX_CSV_FIELD_BYTES)

    # Sniff or default delimiter
    sample = text_content[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delimiter = dialect.delimiter
    except (csv.Error, TypeError):
        delimiter = ","

    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
    rows: list[ParsedRow] = []
    max_col_seen = 0

    try:
        for raw_row in reader:
            # Skip empty or whitespace-only lines (e.g. trailing newlines)
            if not raw_row or not any(c.strip() for c in raw_row if c):
                continue

            row_idx = len(rows) + 1
            if row_idx > settings.PARSER_MAX_CSV_ROWS:
                raise ExtractionError(
                    f"CSV row count exceeds limit of {settings.PARSER_MAX_CSV_ROWS}",
                    safe_detail="CSV row limit exceeded",
                )

            if len(raw_row) > settings.PARSER_MAX_CSV_COLS:
                raise ExtractionError(
                    f"CSV column count exceeds limit of {settings.PARSER_MAX_CSV_COLS}",
                    safe_detail="CSV column limit exceeded",
                )

            # Track total record bytes (including multiline quoted content)
            record_bytes = sum(len(c.encode("utf-8")) for c in raw_row)
            if record_bytes > settings.PARSER_MAX_CSV_RECORD_BYTES:
                raise ExtractionError(
                    f"CSV record byte size ({record_bytes}) exceeds limit of {settings.PARSER_MAX_CSV_RECORD_BYTES}",
                    safe_detail="CSV record size limit exceeded",
                )

            cells = [str(c) if c != "" else None for c in raw_row]
            max_col_seen = max(max_col_seen, len(cells))
            rows.append(ParsedRow(row_index=row_idx, cells=cells))
    except csv.Error as exc:
        raise ExtractionError(
            f"CSV parsing error: {exc}",
            safe_detail="CSV field or record size limit exceeded",
        ) from exc

    sheet = ParsedSheet(
        name="Sheet1",
        rows=rows,
        row_count=len(rows),
        column_count=max_col_seen,
    )

    return ParsedDocument(
        document_id=document_id,
        filename=filename,
        media_type=media_type,
        parse_method=DocumentParseMethod.TEXT,
        page_count=1,
        pages=[],
        sheets=[sheet],
        total_text_blocks=0,
        total_tables=1,
        warnings=[],
    )
