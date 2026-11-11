"""Pydantic v2 schemas for deterministic document extraction and OCR parsing."""

import math
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentParseMethod(str, Enum):
    """Document-level parse method."""

    TEXT = "text"
    OCR = "ocr"
    MIXED = "mixed"


class SourceMethod(str, Enum):
    """Page-level and block-level extraction source method."""

    TEXT = "text"
    OCR = "ocr"


class BoundingBox(BaseModel):
    """Normalized bounding box geometry [x0, y0, x1, y1] on a page (0.0 to 1.0).

    Spatial coordinates only (not financial amounts).
    Must be finite, ordered, and clamped within [0.0, 1.0].
    """

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0.0, le=1.0, description="Normalized left coordinate")
    y0: float = Field(ge=0.0, le=1.0, description="Normalized top coordinate")
    x1: float = Field(ge=0.0, le=1.0, description="Normalized right coordinate")
    y1: float = Field(ge=0.0, le=1.0, description="Normalized bottom coordinate")

    @model_validator(mode="after")
    def validate_geometry(self) -> "BoundingBox":
        for coord_name, val in [("x0", self.x0), ("y0", self.y0), ("x1", self.x1), ("y1", self.y1)]:
            if not math.isfinite(val):
                raise ValueError(f"BoundingBox coordinate {coord_name} must be finite")
        if self.x0 > self.x1:
            raise ValueError(f"BoundingBox x0 ({self.x0}) cannot exceed x1 ({self.x1})")
        if self.y0 > self.y1:
            raise ValueError(f"BoundingBox y0 ({self.y0}) cannot exceed y1 ({self.y1})")
        return self


class ParsedTextBlock(BaseModel):
    """A discrete block of parsed text with geometry and provenance."""

    model_config = ConfigDict(extra="forbid")

    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="OCR confidence score between 0.0 and 1.0. None for native text or when unavailable.",
    )
    source: SourceMethod
    page_number: int = Field(ge=1, description="1-based page number")
    block_index: int = Field(ge=0, description="0-based block index on the page")

    @model_validator(mode="after")
    def validate_confidence(self) -> "ParsedTextBlock":
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("OCR confidence must be a finite float")
        return self


class ParsedTable(BaseModel):
    """A tabular grid extracted from a document page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, description="1-based page number")
    rows: list[list[str]] = Field(default_factory=list)
    bbox: BoundingBox | None = None


class ParsedPage(BaseModel):
    """A parsed page of a document containing text blocks and tables."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, description="1-based page number")
    width: float = Field(gt=0.0, description="Page width in points or pixels")
    height: float = Field(gt=0.0, description="Page height in points or pixels")
    source: SourceMethod
    text_blocks: list[ParsedTextBlock] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)


class ParsedRow(BaseModel):
    """A single row from a parsed spreadsheet sheet."""

    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=1, description="1-based row index")
    cells: list[str | None] = Field(default_factory=list)


class ParsedSheet(BaseModel):
    """A parsed sheet from a spreadsheet (XLSX, CSV)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rows: list[ParsedRow] = Field(default_factory=list)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class ParsedDocument(BaseModel):
    """Complete structured output of deterministic document parsing."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    filename: str
    media_type: str
    parse_method: DocumentParseMethod
    page_count: int = Field(ge=0)
    pages: list[ParsedPage] = Field(default_factory=list)
    sheets: list[ParsedSheet] = Field(default_factory=list)
    total_text_blocks: int = Field(ge=0, default=0)
    total_tables: int = Field(ge=0, default=0)
    warnings: list[str] = Field(default_factory=list)
