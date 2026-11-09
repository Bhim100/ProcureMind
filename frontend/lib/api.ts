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
  document_type: "invoice" | "shipping_bill" | "bank_statement" | "customs_declaration" | "other";
  upload_time: string;
  processing_status: "uploaded" | "parsed" | "extracted" | "needs_review" | "approved" | "rejected";
  page_count?: number | null;
  is_demo: boolean;
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

export async function getDocuments(): Promise<DocumentRead[]> {
  const res = await fetch(`${API_BASE}/api/v1/documents`);
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

// --- Phase 5: PayPal Sandbox & Invoices ---

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

export interface OrderInitiationResponse {
  order_id: string;
  status: string;
  currency: string;
  amount: string;
  invoice_number: string;
  approval_url?: string | null;
}

export async function getPayPalConfig(): Promise<PayPalConfigResponse> {
  const res = await fetch(`${API_BASE}/api/v1/payments/config`);
  if (!res.ok) {
    throw new Error(`Failed to fetch PayPal config: HTTP ${res.status}`);
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

export async function getPayments(params?: {
  export_transaction_id?: string;
  invoice_id?: string;
  status?: string;
}): Promise<PaymentRead[]> {
  const query = new URLSearchParams();
  if (params?.export_transaction_id) query.append("export_transaction_id", params.export_transaction_id);
  if (params?.invoice_id) query.append("invoice_id", params.invoice_id);
  if (params?.status) query.append("status", params.status);

  const url = `${API_BASE}/api/v1/payments${query.toString() ? `?${query.toString()}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch payments: HTTP ${res.status}`);
  }
  return res.json();
}

