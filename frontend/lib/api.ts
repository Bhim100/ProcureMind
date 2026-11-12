/**
 * Typed API Client for ProcureMind Backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DocumentRead {
  id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  storage_key: string;
  document_type: "invoice" | "shipping_bill" | "bank_statement" | "customs_declaration" | "receipt" | "other";
  upload_time: string;
  processing_status: "uploaded" | "parsed" | "extracted" | "needs_review" | "approved" | "rejected";
  page_count?: number | null;
  is_demo: boolean;
  source_system?: string;
  source_external_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  document: DocumentRead;
  is_duplicate: boolean;
  message: string;
}

export interface DownloadUrlResponse {
  download_url: string;
  expires_in_seconds: number;
  expires_at: string;
}

export interface PreviewUrlResponse {
  preview_url: string;
  expires_in_seconds: number;
  expires_at: string;
}

export interface ExtractedFieldRead {
  id: string;
  document_id: string;
  field_name: string;
  raw_value: string | null;
  normalized_value: any;
  page_number?: number | null;
  row_number?: number | null;
  bounding_box?: { x0: number; y0: number; x1: number; y1: number } | null;
  confidence?: string | number | null;
  review_state: "pending" | "auto_accepted" | "human_verified" | "rejected";
  extraction_method: "text" | "ocr" | "llm" | "manual";
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface FieldAuditLogRead {
  id: string;
  document_id?: string | null;
  extracted_field_id?: string | null;
  document_id_snapshot: string;
  extracted_field_id_snapshot: string;
  field_name: string;
  old_normalized_value: any;
  new_normalized_value: any;
  reviewer_label: string;
  notes?: string | null;
  created_at: string;
}

export interface ExtractedFieldCorrectionResponse {
  field: ExtractedFieldRead;
  audit_log: FieldAuditLogRead;
}

export interface MatchSummaryItem {
  match_id: string;
  rule_id: string;
  match_type: string;
  match_status: "matched" | "partial" | "ambiguous" | "unmatched" | "requires_human_review";
  review_status: "suggested" | "approved" | "rejected" | "superseded";
  allocated_amount: string;
  currency: string;
  severity: "info" | "warning" | "error" | "critical";
  calculation?: Record<string, any> | null;
  compared_values?: Record<string, any> | null;
  created_at: string;
}

export interface TransactionInvoiceSummary {
  invoice_id: string;
  invoice_number: string;
  total_amount: string;
  currency: string;
  is_approved: boolean;
  remaining_balance: string;
}

export interface TransactionPaymentSummary {
  payment_id: string;
  provider_order_id?: string | null;
  provider_capture_id?: string | null;
  gross_amount: string;
  currency: string;
  status: string;
}

export interface DiscrepancyItemSummary {
  discrepancy_id: string;
  rule_id: string;
  severity: string;
  status: string;
  difference_amount?: string | null;
  description: string;
  recommended_action?: string | null;
}

export interface EvidenceItemSummary {
  evidence_id: string;
  document_id: string;
  document_title: string;
  document_type: string;
  location_reference?: string | null;
  raw_snippet?: string | null;
}

export interface ReconciliationQueueRow {
  transaction_id: string;
  reference: string;
  buyer_name: string;
  exporter_name: string;
  status: string;
  status_label: string;
  is_demo: boolean;
  currency: string;
  created_at: string;
  updated_at: string;
  invoices: TransactionInvoiceSummary[];
  payments: TransactionPaymentSummary[];
  matches: MatchSummaryItem[];
  discrepancies: DiscrepancyItemSummary[];
  evidence_references: EvidenceItemSummary[];
  requires_human_review: boolean;
  has_matches: boolean;
  shortfall_amount?: string | null;
  active_match_count: number;
  discrepancy_count: number;
  evidence_count: number;
}

export interface ReconciliationQueueResponse {
  items: ReconciliationQueueRow[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface CurrencyVolume {
  currency: string;
  payment_count: number;
  total_gross: string;
  total_fee: string;
  total_net: string;
}

export interface DemoBreakdown {
  demo_transactions: number;
  non_demo_transactions: number;
  demo_documents: number;
  non_demo_documents: number;
  demo_payments: number;
  non_demo_payments: number;
}

export interface ActivityDataPoint {
  date: string;
  transactions_created: number;
  matches_proposed: number;
  matches_approved: number;
  payments_captured: number;
}

export interface DashboardSummaryResponse {
  open_records_count: number;
  need_review_count: number;
  sandbox_payments_count: number;
  documents_by_status: Record<string, number>;
  payments_by_currency: CurrencyVolume[];
  demo_breakdown: DemoBreakdown;
  recent_activity: ActivityDataPoint[];
}

export interface PayPalConfigResponse {
  client_id: string;
  environment: string;
}

export interface PaymentRead {
  id: string;
  provider: string;
  invoice_id?: string | null;
  provider_order_id?: string | null;
  provider_capture_id?: string | null;
  provider_refund_id?: string | null;
  parent_payment_id?: string | null;
  invoice_reference?: string | null;
  currency: string;
  gross_amount: string;
  fee_amount?: string | null;
  net_amount?: string | null;
  status: "pending" | "completed" | "refunded" | "failed";
  environment: "sandbox" | "live" | "simulated";
  description: string;
  is_demo?: boolean;
  payer_email?: string | null;
  created_at: string;
  event_time?: string | null;
}

export interface InvoiceDetailResponse {
  id: string;
  invoice_number: string;
  export_transaction_id?: string | null;
  seller_name: string;
  buyer_name: string;
  issue_date?: string | null;
  currency: string;
  total_amount: string;
  is_approved: boolean;
  approval_details?: {
    reviewer_label: string;
    decided_at: string;
    notes: string;
  } | null;
  remaining_balance: string;
}

export type InvoiceSummaryItem = InvoiceDetailResponse;

export interface PaginatedInvoiceListResponse {
  items: InvoiceDetailResponse[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface OrderInitiationResponse {
  order_id: string;
  status: string;
  currency: string;
  amount: string;
  invoice_number: string;
  approval_url?: string | null;
}

export interface InvestigationResponse {
  transaction_id: string;
  transaction_reference: string;
  discrepancy_id: string | null;
  status: "success" | "unavailable" | "refusal";
  explanation: string;
  authoritative_facts: {
    invoice_total: { amount: string; currency: string } | null;
    payment_gross: { amount: string; currency: string } | null;
    fee_amount: { amount: string; currency: string } | null;
    net_amount: { amount: string; currency: string } | null;
    unexplained_difference: { amount: string; currency: string } | null;
    currencies_match: boolean;
    currency_mismatch_warning: string | null;
    calculation_breakdown: Record<string, unknown> | null;
    is_reconciled: boolean;
    open_discrepancy_count: number;
  };
  cited_record_ids: string[];
  missing_information: string[];
  suggested_next_action: string | null;
  draft_clarification_message: string | null;
  requires_human_review: boolean;
  provider: string;
  warnings: string[];
}

// --- Documents API ---

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/v1/documents`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Upload failed with status HTTP ${res.status}`);
  }

  return res.json();
}

export async function getDocuments(
  skipOrParams: number | { skip?: number; limit?: number; is_demo?: boolean } = 0,
  limitArg = 50
): Promise<DocumentRead[]> {
  const query = new URLSearchParams();
  if (typeof skipOrParams === "object") {
    if (skipOrParams.skip !== undefined) query.append("skip", String(skipOrParams.skip));
    if (skipOrParams.limit !== undefined) query.append("limit", String(skipOrParams.limit));
    if (skipOrParams.is_demo !== undefined) query.append("is_demo", String(skipOrParams.is_demo));
  } else {
    query.append("skip", String(skipOrParams));
    query.append("limit", String(limitArg));
  }

  const url = `${API_BASE}/api/v1/documents${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch documents: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getDocument(id: string): Promise<DocumentRead> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch document ${id}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getDownloadUrl(id: string): Promise<DownloadUrlResponse> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}/download-url`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to generate download URL: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getPreviewUrl(id: string): Promise<PreviewUrlResponse> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${id}/preview-url`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to generate preview URL: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getDocumentFields(documentId: string): Promise<ExtractedFieldRead[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/fields`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch document fields: HTTP ${res.status}`);
  }
  return res.json();
}

export async function parseDocument(documentId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/parse`, {
    method: "POST",
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Parse failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function extractDocument(documentId: string, documentKind = "invoice"): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_kind: documentKind }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Extraction failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function correctDocumentField(
  documentId: string,
  fieldId: string,
  payload: { new_normalized_value: any; reviewer_label: string; notes?: string },
  auditorKey: string
): Promise<ExtractedFieldCorrectionResponse> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/fields/${fieldId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-Auditor-Key": auditorKey,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Field correction failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function getFieldAuditTrail(documentId: string, fieldId: string): Promise<FieldAuditLogRead[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents/${documentId}/fields/${fieldId}/audit-trail`);
  if (!res.ok) {
    throw new Error(`Failed to fetch field audit trail: HTTP ${res.status}`);
  }
  return res.json();
}

// --- Reconciliation Queue API ---

export async function getReconciliationQueue(params?: {
  page?: number;
  page_size?: number;
  review_status?: string;
  match_status?: string;
  is_demo?: boolean;
  search?: string;
}): Promise<ReconciliationQueueResponse> {
  const query = new URLSearchParams();
  if (params?.page) query.append("page", String(params.page));
  if (params?.page_size) query.append("page_size", String(params.page_size));
  if (params?.review_status) query.append("review_status", params.review_status);
  if (params?.match_status) query.append("match_status", params.match_status);
  if (params?.is_demo !== undefined) query.append("is_demo", String(params.is_demo));
  if (params?.search) query.append("search", params.search);

  const url = `${API_BASE}/api/v1/reconciliation/queue${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch reconciliation queue: HTTP ${res.status}`);
  }
  return res.json();
}

export async function decideMatch(
  matchId: string,
  payload: { decision: "approved" | "rejected"; reviewer_label: string; notes: string },
  auditorKey: string
): Promise<MatchSummaryItem> {
  const res = await fetch(`${API_BASE}/api/v1/matches/${matchId}/decision`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Auditor-Key": auditorKey,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Match decision failed with status HTTP ${res.status}`);
  }
  return res.json();
}

// --- Dashboard API ---

export async function getDashboardSummary(params?: {
  include_demo?: boolean;
}): Promise<DashboardSummaryResponse> {
  const query = new URLSearchParams();
  if (params?.include_demo !== undefined) {
    query.append("include_demo", String(params.include_demo));
  }
  const url = `${API_BASE}/api/v1/dashboard/summary${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch dashboard summary: HTTP ${res.status}`);
  }
  return res.json();
}

// --- Invoices API ---

export async function getInvoices(params?: {
  limit?: number;
  offset?: number;
  approval_status?: string;
  is_demo?: boolean;
  search?: string;
}): Promise<PaginatedInvoiceListResponse> {
  const query = new URLSearchParams();
  if (params?.limit) query.append("limit", String(params.limit));
  if (params?.offset !== undefined) query.append("offset", String(params.offset));
  if (params?.approval_status) query.append("approval_status", params.approval_status);
  if (params?.is_demo !== undefined) query.append("is_demo", String(params.is_demo));
  if (params?.search) query.append("search", params.search);

  const url = `${API_BASE}/api/v1/invoices${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch invoices: HTTP ${res.status}`);
  }
  return res.json();
}

export async function getInvoiceDetail(invoiceId: string): Promise<InvoiceDetailResponse> {
  const res = await fetch(`${API_BASE}/api/v1/invoices/${invoiceId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch invoice ${invoiceId}: HTTP ${res.status}`);
  }
  return res.json();
}

export async function approveInvoice(
  invoiceId: string,
  reviewerLabel: string,
  notes: string,
  auditorKey: string
): Promise<{ invoice_id: string; status: string; decision_id: string }> {
  const res = await fetch(`${API_BASE}/api/v1/invoices/${invoiceId}/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Auditor-Key": auditorKey,
    },
    body: JSON.stringify({
      reviewer_label: reviewerLabel,
      notes,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Invoice approval failed with status HTTP ${res.status}`);
  }
  return res.json();
}

// --- Payments API ---

export async function getPayPalConfig(): Promise<PayPalConfigResponse> {
  const res = await fetch(`${API_BASE}/api/v1/payments/config`);
  if (!res.ok) {
    throw new Error(`Failed to fetch PayPal config: HTTP ${res.status}`);
  }
  return res.json();
}

export async function initiatePayment(invoiceId: string): Promise<OrderInitiationResponse> {
  const res = await fetch(`${API_BASE}/api/v1/payments/invoices/${invoiceId}/pay`, {
    method: "POST",
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Order creation failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function captureOrder(orderId: string): Promise<PaymentRead> {
  const res = await fetch(`${API_BASE}/api/v1/payments/orders/${orderId}/capture`, {
    method: "POST",
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Order capture failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function simulatePaymentCapture(invoiceId: string): Promise<PaymentRead> {
  const res = await fetch(`${API_BASE}/api/v1/payments/invoices/${invoiceId}/simulate-capture`, {
    method: "POST",
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Simulated payment failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export async function getPayments(params?: {
  export_transaction_id?: string;
  invoice_id?: string;
  status?: string;
  environment?: string;
  is_demo?: boolean;
  limit?: number;
  offset?: number;
}): Promise<PaymentRead[]> {
  const query = new URLSearchParams();
  if (params?.export_transaction_id) query.append("export_transaction_id", params.export_transaction_id);
  if (params?.invoice_id) query.append("invoice_id", params.invoice_id);
  if (params?.status) query.append("status", params.status);
  if (params?.environment) query.append("environment", params.environment);
  if (params?.is_demo !== undefined) query.append("is_demo", String(params.is_demo));
  if (params?.limit) query.append("limit", String(params.limit));
  if (params?.offset !== undefined) query.append("offset", String(params.offset));

  const url = `${API_BASE}/api/v1/payments${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch payments: HTTP ${res.status}`);
  }
  return res.json();
}

// --- Investigation API ---

export async function investigateTransaction(
  transactionIdOrReference: string,
  question: string
): Promise<InvestigationResponse> {
  const res = await fetch(
    `${API_BASE}/api/v1/transactions/${encodeURIComponent(transactionIdOrReference)}/investigate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }
  );
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Investigation failed with status HTTP ${res.status}`);
  }
  return res.json();
}

export interface HealthResponse {
  status: string;
  service?: string;
  environment?: string;
  timestamp?: string;
}

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/health`);
  if (!res.ok) throw new Error(`Health check failed: HTTP ${res.status}`);
  return res.json();
}

// --- Zoho Books Integration API ---

export interface ZohoStatusResponse {
  is_connected: boolean;
  organization_id: string | null;
  organization_name: string | null;
  api_domain: string;
  last_sync_at: string | null;
  synced_documents_count: number;
  total_synced_amount: string | number;
  currency: string;
  has_oauth_config: boolean;
}

export interface ZohoAuthUrlResponse {
  auth_url: string;
  configured: boolean;
}

export interface ZohoInvoiceItem {
  document_id: string;
  invoice_number: string;
  filename: string;
  total_amount: string | number;
  currency: string;
  status: string;
  source_external_id: string;
}

export interface ZohoSyncResult {
  synced_count: number;
  skipped_duplicate_count: number;
  failed_count: number;
  invoices: ZohoInvoiceItem[];
  message: string;
}

export async function getZohoStatus(): Promise<ZohoStatusResponse> {
  const res = await fetch(`${API_BASE}/api/v1/integrations/zoho/status`);
  if (!res.ok) throw new Error(`Failed to fetch Zoho status: HTTP ${res.status}`);
  return res.json();
}

export async function getZohoAuthUrl(): Promise<ZohoAuthUrlResponse> {
  const res = await fetch(`${API_BASE}/api/v1/integrations/zoho/auth-url`);
  if (!res.ok) throw new Error(`Failed to fetch Zoho auth URL: HTTP ${res.status}`);
  return res.json();
}

export async function syncZohoInvoices(limit = 10): Promise<ZohoSyncResult> {
  const res = await fetch(`${API_BASE}/api/v1/integrations/zoho/sync?limit=${limit}`, {
    method: "POST",
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Zoho sync failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function simulateZohoSync(count = 1): Promise<ZohoSyncResult> {
  const res = await fetch(`${API_BASE}/api/v1/integrations/zoho/simulate-sync?count=${count}`, {
    method: "POST",
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Zoho simulation failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function disconnectZoho(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/v1/integrations/zoho/disconnect`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to disconnect Zoho: HTTP ${res.status}`);
  return res.json();
}
