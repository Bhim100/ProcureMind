"""Deterministic source index compiling Phase 7 ParsedDocument content for LLM extraction."""

from dataclasses import dataclass

from app.models.enums import ExtractionMethod
from app.schemas.parser import ParsedDocument, SourceMethod


@dataclass
class SourceIndexEntry:
    """An indexed physical source element from a ParsedDocument."""

    source_id: str
    text: str
    page_number: int | None
    row_number: int | None
    bbox: dict[str, float] | None
    source_method: ExtractionMethod


class SourceIndex:
    """Registry of all physical text blocks, table cells, and sheet rows."""

    def __init__(self, entries: dict[str, SourceIndexEntry]) -> None:
        self.entries = entries

    def get_entry(self, source_id: str) -> SourceIndexEntry | None:
        return self.entries.get(source_id)

    def validate_source_ids(self, source_ids: list[str]) -> tuple[bool, list[str]]:
        """Verify that all source IDs exist in this index.

        Returns (is_valid, list_of_invalid_ids).
        """
        invalid_ids = [sid for sid in source_ids if sid not in self.entries]
        return (len(invalid_ids) == 0, invalid_ids)

    def resolve_provenance(
        self,
        source_ids: list[str],
    ) -> tuple[str | None, int | None, int | None, dict[str, float] | None, ExtractionMethod]:
        """Derive combined raw_value, page, row, bbox, and extraction method from cited source IDs.

        Reconstructs physical provenance directly from Phase 7 verified data;
        never trusts model-supplied coordinates or raw values.
        """
        valid_entries = [self.entries[sid] for sid in source_ids if sid in self.entries]
        if not valid_entries:
            return None, None, None, None, ExtractionMethod.LLM

        # Combine raw text snippets
        raw_values = [e.text.strip() for e in valid_entries if e.text.strip()]
        combined_raw = " ".join(raw_values) if raw_values else None

        primary = valid_entries[0]
        page_number = primary.page_number
        row_number = primary.row_number

        # Enclosing bounding box across all cited blocks
        bboxes = [e.bbox for e in valid_entries if e.bbox is not None]
        combined_bbox: dict[str, float] | None = None
        if bboxes:
            min_x0 = min(b["x0"] for b in bboxes)
            min_y0 = min(b["y0"] for b in bboxes)
            max_x1 = max(b["x1"] for b in bboxes)
            max_y1 = max(b["y1"] for b in bboxes)
            combined_bbox = {
                "x0": round(min_x0, 4),
                "y0": round(min_y0, 4),
                "x1": round(max_x1, 4),
                "y1": round(max_y1, 4),
            }

        # Any OCR source marks the underlying provenance method as OCR
        method = ExtractionMethod.LLM

        return combined_raw, page_number, row_number, combined_bbox, method

    def format_context_for_prompt(self) -> str:
        """Format index into structured lines with source IDs for the LLM prompt."""
        lines: list[str] = []
        for sid, entry in self.entries.items():
            clean_text = entry.text.strip()
            if clean_text:
                lines.append(f"[{sid}] {clean_text}")
        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        """Alias for format_context_for_prompt."""
        return self.format_context_for_prompt()


def build_source_index(parsed_doc: ParsedDocument) -> SourceIndex:
    """Build a deterministic SourceIndex from a Phase 7 ParsedDocument."""
    entries: dict[str, SourceIndexEntry] = {}

    # 1. Index pages, blocks, and tables
    for page in parsed_doc.pages:
        p_num = page.page_number
        for b_idx, block in enumerate(page.text_blocks):
            sid = f"page:{p_num}:block:{b_idx}"
            bbox_dict = (
                {"x0": block.bbox.x0, "y0": block.bbox.y0, "x1": block.bbox.x1, "y1": block.bbox.y1}
                if block.bbox
                else None
            )
            src_method = (
                ExtractionMethod.OCR if block.source == SourceMethod.OCR else ExtractionMethod.TEXT
            )
            entries[sid] = SourceIndexEntry(
                source_id=sid,
                text=block.text,
                page_number=p_num,
                row_number=None,
                bbox=bbox_dict,
                source_method=src_method,
            )

        for t_idx, table in enumerate(page.tables):
            for r_idx, row in enumerate(table.rows):
                for c_idx, cell in enumerate(row):
                    if cell and cell.strip():
                        sid = f"page:{p_num}:table:{t_idx}:row:{r_idx}:cell:{c_idx}"
                        entries[sid] = SourceIndexEntry(
                            source_id=sid,
                            text=cell.strip(),
                            page_number=p_num,
                            row_number=r_idx + 1,
                            bbox=None,
                            source_method=ExtractionMethod.TEXT,
                        )

    # 2. Index spreadsheet sheets and cells
    for sheet in parsed_doc.sheets:
        s_name = sheet.name
        for s_row in sheet.rows:
            r_num = s_row.row_index
            for c_idx, cell_val in enumerate(s_row.cells):
                if cell_val is not None and str(cell_val).strip():
                    sid = f"sheet:{s_name}:row:{r_num}:cell:{c_idx}"
                    entries[sid] = SourceIndexEntry(
                        source_id=sid,
                        text=str(cell_val).strip(),
                        page_number=None,
                        row_number=r_num,
                        bbox=None,
                        source_method=ExtractionMethod.TEXT,
                    )

    return SourceIndex(entries)
