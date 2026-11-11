"""Utility script to generate small synthetic test fixtures for Phase 7."""

import io
import zipfile
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def make_pdf(pages_text: list[str]) -> bytes:
    """Generate a minimal valid multi-page PDF with accurate xref offsets."""
    objects: list[bytes] = []
    # obj 1: Catalog
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    # obj 2: Pages
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages_text)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages_text)} >>".encode("ascii"))

    font_obj_idx = 3 + len(pages_text) * 2

    for i, text in enumerate(pages_text):
        c_obj_num = 4 + i * 2
        p_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {c_obj_num} 0 R /Resources << /Font << /F1 {font_obj_idx} 0 R >> >> >>"
        ).encode("ascii")
        objects.append(p_obj)

        stream_content = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET\n".encode()
        c_obj = (
            f"<< /Length {len(stream_content)} >>\nstream\n".encode("ascii")
            + stream_content
            + b"endstream"
        )
        objects.append(c_obj)

    # Font obj
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects):
        offsets.append(out.tell())
        out.write(f"{i + 1} 0 obj\n".encode("ascii"))
        out.write(obj)
        out.write(b"\nendobj\n")

    xref_offset = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return out.getvalue()


def generate_all() -> None:
    # 1. Digital PDF (38 non-whitespace characters >= 30 threshold)
    digital_pdf = make_pdf(["COMMERCIAL INVOICE NUMBER: INV-2026-001-A"])
    (FIXTURES_DIR / "sample_digital.pdf").write_bytes(digital_pdf)

    # 2. Scanned PDF (low text < 30 non-whitespace threshold)
    scanned_pdf = make_pdf([" . ... "])
    (FIXTURES_DIR / "sample_scanned.pdf").write_bytes(scanned_pdf)

    # 3. Mixed PDF (page 1 digital, page 2 scanned)
    mixed_pdf = make_pdf(["COMMERCIAL INVOICE NUMBER: INV-2026-001-A", " . ... "])
    (FIXTURES_DIR / "sample_mixed.pdf").write_bytes(mixed_pdf)

    # 4. Table PDF
    (FIXTURES_DIR / "sample_table.pdf").write_bytes(digital_pdf)

    # 5. Receipt PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x03\x05\xfe"
        b"\x02\xfe\x1c\xc4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (FIXTURES_DIR / "sample_receipt.png").write_bytes(png_bytes)

    # 6. Minimal valid XLSX
    wb_bytes = io.BytesIO()
    with zipfile.ZipFile(wb_bytes, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Invoices" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            '<row r="1"><c r="A1" t="inlineStr"><is><t>Item</t></is></c><c r="B1" t="inlineStr"><is><t>Amount</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>Service</t></is></c><c r="B2"><v>1000</v></c></row>'
            '<row r="3"><c r="A3" t="inlineStr"><is><t>Total</t></is></c><c r="B3"><f>SUM(B2:B2)</f><v>1000</v></c></row>'
            "</sheetData></worksheet>",
        )
    (FIXTURES_DIR / "sample_data.xlsx").write_bytes(wb_bytes.getvalue())


if __name__ == "__main__":
    generate_all()
    print("All fixtures generated successfully.")
