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

