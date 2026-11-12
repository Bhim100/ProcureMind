# Sample Trade Documents for Evaluation

This directory contains authentic synthetic trade documents formatted for cross-border export evaluation:

1. **`01-proforma-invoice.pdf`**:
   - Initial quotation/proforma invoice (`PI-BW-2026-0417`).
   - Line 2: 300 PCS @ $8.20 = $2,460.00. Total: **USD 11,520.00**.

2. **`02-commercial-invoice.pdf`**:
   - Final accounting commercial invoice (`BW-INV-26-0882`).
   - Line 2: 300 PCS @ $8.45 = $2,535.00. Total: **USD 11,595.00**.
   - *Cross-document variance*: Line 2 unit price increased by **+$0.25/unit (+3.05%)**, resulting in a net **+$75.00** discrepancy detected by ProcureMind's diff engine.

3. **`03-packing-list.pdf`**:
   - Shipping packing list verifying 1,100 total packages and net weight across line items.

4. **`04-bill-of-lading.pdf`**:
   - Bill of Lading (`BL-BW-2026-9901`) with container logistics reference.

### How Judges Can Use These
1. Open the **Documents Registry** (`http://localhost:3000/documents`).
2. Drag and drop any of these PDFs into the dropzone.
3. Watch the system compute the cryptographic SHA-256 digest, extract structured line items, and link them to the **Reconciliation Queue**.
4. Open **Reconciliation** -> **Compare Documents** to view the instant line-by-line comparison between `01-proforma-invoice.pdf` and `02-commercial-invoice.pdf`.
