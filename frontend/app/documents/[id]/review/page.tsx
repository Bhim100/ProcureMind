"use client";

import React, { useState, use } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  FileText,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Clock,
  Edit3,
  ExternalLink,
  History,
  X,
  Lock,
  Sparkles,
  GitCompare,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import {
  getDocumentFields,
  getPreviewUrl,
  correctDocumentField,
  getFieldAuditTrail,
  parseDocument,
  extractDocument,
  getDocuments,
  ExtractedFieldRead,
  FieldAuditLogRead,
  DocumentRead,
} from "@/lib/api";
import { useAuditorSession } from "@/lib/auditor-session";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function DocumentReviewPage({ params }: PageProps) {
  const resolvedParams = use(params);
  const documentId = resolvedParams.id;
  const queryClient = useQueryClient();
  const { auditorKey, reviewer, openKeyModal } = useAuditorSession();

  // Selected field for correction modal
  const [editingField, setEditingField] = useState<ExtractedFieldRead | null>(null);
  const [newValue, setNewValue] = useState("");
  const [correctionNotes, setCorrectionNotes] = useState("");
  const [reviewerInput, setReviewerInput] = useState(reviewer);
  const [actionError, setActionError] = useState<string | null>(null);

  // Active review tab
  const [activeTab, setActiveTab] = useState<"fields" | "compare">("fields");

  // Fetch all documents for metadata display & comparison
  const { data: allDocs = [] } = useQuery<DocumentRead[]>({
    queryKey: ["documents"],
    queryFn: () => getDocuments(),
  });
  const currentDoc = allDocs.find((d) => d.id === documentId);

  // Field for viewing audit trail
  const [viewingAuditField, setViewingAuditField] = useState<ExtractedFieldRead | null>(null);

  // 1. Fetch document preview URL
  const {
    data: previewData,
    isLoading: isPreviewLoading,
    error: previewError,
  } = useQuery({
    queryKey: ["document-preview", documentId],
    queryFn: () => getPreviewUrl(documentId),
    staleTime: 1000 * 60 * 10, // 10 minutes (token valid for 15)
  });

  // 2. Fetch document extracted fields
  const {
    data: fields = [],
    isLoading: isFieldsLoading,
    error: fieldsError,
  } = useQuery({
    queryKey: ["document-fields", documentId],
    queryFn: () => getDocumentFields(documentId),
  });

  // 3. Fetch audit trail for selected field
  const { data: auditTrail = [], isLoading: isAuditLoading } = useQuery<FieldAuditLogRead[]>({
    queryKey: ["field-audit", documentId, viewingAuditField?.id],
    queryFn: () =>
      viewingAuditField ? getFieldAuditTrail(documentId, viewingAuditField.id) : Promise.resolve([]),
    enabled: !!viewingAuditField,
  });

  // Extract & Parse mutation
  const [extractError, setExtractError] = useState<string | null>(null);
  const extractMutation = useMutation({
    mutationFn: async () => {
      setExtractError(null);
      await parseDocument(documentId);
      await extractDocument(documentId, "invoice");
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-fields", documentId] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      setExtractError(null);
    },
    onError: (err: any) => {
      setExtractError(err.message || "Failed to parse/extract document");
    },
  });

  // Correction mutation
  const correctionMutation = useMutation({
    mutationFn: async () => {
      if (!editingField) throw new Error("No field selected");
      if (!auditorKey) {
        throw new Error("Auditor API Key required. Click 'Auditor Session' in the top header to enter it.");
      }
      if (!correctionNotes.trim()) {
        throw new Error("Justification notes are required.");
      }
      if (!newValue.trim()) {
        throw new Error("New normalized value is required.");
      }

      return correctDocumentField(
        documentId,
        editingField.id,
        {
          new_normalized_value: newValue.trim(),
          reviewer_label: reviewerInput.trim() || reviewer || "Compliance Reviewer",
          notes: correctionNotes.trim(),
        },
        auditorKey
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document-fields", documentId] });
      setEditingField(null);
      setNewValue("");
      setCorrectionNotes("");
      setActionError(null);
    },
    onError: (err: any) => {
      setActionError(err.message || "Failed to submit field correction");
    },
  });

  const openCorrection = (f: ExtractedFieldRead) => {
    setEditingField(f);
    setNewValue(f.normalized_value || f.raw_value);
    setCorrectionNotes("");
    setReviewerInput(reviewer);
    setActionError(null);
  };

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const fullPreviewUrl = previewData?.preview_url
    ? previewData.preview_url.startsWith("http")
      ? previewData.preview_url
      : `${API_BASE}${previewData.preview_url}`
    : null;

  return (
    <AppShell activeNav="documents">
      <div className="space-y-6">
        {/* Top breadcrumb and page title */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <Link
              href="/documents"
              className="p-2 rounded-lg bg-[#0c1322] border border-[#1e293b] text-slate-400 hover:text-white transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-blue-400">
                  Document Review & Audit
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                  {documentId.slice(0, 8)}...
                </span>
              </div>
              <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                Extracted Field Provenance & Grounded Verification
              </h1>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            {!auditorKey && (
              <button
                onClick={openKeyModal}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-medium hover:bg-amber-500/20 transition-colors"
              >
                <Lock className="w-3.5 h-3.5" />
                <span>Auditor Key Needed to Edit</span>
              </button>
            )}
            <Link
              href="/reconciliation"
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#0c1322] border border-[#1e293b] text-blue-400 hover:text-white text-xs font-medium transition-colors"
            >
              <GitCompare className="w-3.5 h-3.5" />
              <span>Compare in Reconciliation →</span>
            </Link>
            {fullPreviewUrl && (
              <a
                href={fullPreviewUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#0c1322] border border-[#1e293b] text-slate-300 hover:text-white text-xs font-medium transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                <span>Open in Tab</span>
              </a>
            )}
          </div>
        </div>

        {/* Two-Pane Review Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[640px]">
          {/* Left Pane: Inline Document Preview */}
          <div className="lg:col-span-6 bg-[#0c1322] border border-[#1e293b] rounded-2xl flex flex-col overflow-hidden shadow-xl">
            <div className="px-4 py-3 border-b border-[#1e293b] flex items-center justify-between bg-[#080d1a]/60">
              <div className="flex items-center space-x-2">
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-semibold text-slate-200 uppercase tracking-wide">
                  Grounded Document Source View
                </span>
              </div>
              <span className="text-[11px] text-slate-400">Inline signed preview</span>
            </div>

            <div className="flex-1 bg-[#080d1a] relative flex items-center justify-center p-2 min-h-[500px]">
              {isPreviewLoading ? (
                <div className="text-center text-slate-400 space-y-2">
                  <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-xs">Generating secure signed preview...</p>
                </div>
              ) : previewError ? (
                <div className="text-center p-6 text-slate-400 space-y-2 max-w-sm">
                  <AlertCircle className="w-8 h-8 text-amber-400 mx-auto" />
                  <p className="text-sm font-semibold text-slate-200">Preview Not Available</p>
                  <p className="text-xs text-slate-400">
                    {(previewError as Error).message || "Could not generate inline preview token."}
                  </p>
                </div>
              ) : fullPreviewUrl ? (
                <iframe
                  src={fullPreviewUrl}
                  title="Document Preview"
                  className="w-full h-full rounded-lg border border-[#1e293b] bg-white min-h-[560px]"
                />
              ) : (
                <div className="text-center text-slate-400 text-xs">No preview available</div>
              )}
            </div>
          </div>

          {/* Right Pane: Extracted Fields Registry & Audit Controls */}
          <div className="lg:col-span-6 bg-[#0c1322] border border-[#1e293b] rounded-2xl flex flex-col overflow-hidden shadow-xl">
            <div className="px-5 py-3 border-b border-[#1e293b] flex items-center justify-between bg-[#080d1a]/60">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-semibold text-slate-200 uppercase tracking-wide">
                  Extracted Fields & Source Provenance
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium">
                  {fields.length} {fields.length === 1 ? "field" : "fields"}
                </span>
                <button
                  onClick={() => extractMutation.mutate()}
                  disabled={extractMutation.isPending}
                  className="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-blue-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 text-xs font-medium transition-colors disabled:opacity-50"
                  title="Run automated extraction"
                >
                  <Sparkles className={`w-3.5 h-3.5 ${extractMutation.isPending ? "animate-spin" : ""}`} />
                  <span>{extractMutation.isPending ? "Extracting..." : "Extract Fields"}</span>
                </button>
              </div>
            </div>

            <div className="p-4 flex-1 overflow-y-auto space-y-3">
              {extractError && (
                <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between">
                  <span>{extractError}</span>
                  <button onClick={() => setExtractError(null)} className="text-slate-400 hover:text-white text-xs underline ml-2">Dismiss</button>
                </div>
              )}

              {isFieldsLoading ? (
                <div className="p-12 text-center text-slate-400 space-y-2">
                  <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-xs">Loading structured field extractions...</p>
                </div>
              ) : fieldsError ? (
                <div className="p-6 text-center text-rose-400 text-sm">
                  Failed to load extracted fields: {(fieldsError as Error).message}
                </div>
              ) : fields.length === 0 ? (
                <div className="p-8 text-center text-slate-400 space-y-4">
                  <FileText className="w-10 h-10 text-slate-600 mx-auto" />
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-slate-200">No extracted fields recorded yet</p>
                    <p className="text-xs text-slate-400 max-w-sm mx-auto">
                      Click the button below to parse document tables, text, and extract verified invoice fields with source provenance.
                    </p>
                  </div>
                  <button
                    onClick={() => extractMutation.mutate()}
                    disabled={extractMutation.isPending}
                    className="inline-flex items-center space-x-2 px-4 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all"
                  >
                    <Sparkles className={`w-4 h-4 ${extractMutation.isPending ? "animate-spin" : ""}`} />
                    <span>{extractMutation.isPending ? "Extracting Fields..." : "Run AI Field Extraction"}</span>
                  </button>
                </div>
              ) : (
                fields.map((f) => (
                  <div
                    key={f.id}
                    className="p-4 rounded-xl bg-[#0f172a] border border-[#1e293b] hover:border-slate-600/60 transition-all space-y-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center space-x-2">
                          <span className="text-sm font-semibold text-white capitalize">
                            {f.field_name.replace(/_/g, " ")}
                          </span>
                          <span
                            className={`text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wider ${
                              f.review_state === "human_verified" || f.review_state === "auto_accepted"
                                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                                : f.review_state === "rejected"
                                ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                                : "bg-slate-700/50 text-slate-300 border border-slate-600/40"
                            }`}
                          >
                            {f.review_state}
                          </span>
                        </div>
                        <span className="text-[11px] text-slate-500 font-mono">ID: {f.id.slice(0, 8)}</span>
                      </div>

                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => setViewingAuditField(f)}
                          title="View field audit trail"
                          className="p-1.5 rounded-lg bg-[#0c1322] border border-[#1e293b] text-slate-400 hover:text-white transition-colors"
                        >
                          <History className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => openCorrection(f)}
                          className="inline-flex items-center space-x-1 px-2.5 py-1.5 rounded-lg bg-blue-600/15 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 text-xs font-medium transition-colors"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                          <span>Correct</span>
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                      <div className="bg-[#0c1322] p-2.5 rounded-lg border border-[#1e293b]/70">
                        <span className="text-[11px] text-slate-400 block mb-0.5">Raw Extracted Value:</span>
                        <span className="text-slate-300 font-mono break-all">{f.raw_value || "—"}</span>
                      </div>
                      <div className="bg-[#0c1322] p-2.5 rounded-lg border border-[#1e293b]/70">
                        <span className="text-[11px] text-slate-400 block mb-0.5">Normalized Value:</span>
                        <span className="text-emerald-400 font-semibold font-mono break-all">
                          {f.normalized_value ? String(f.normalized_value) : f.raw_value || "—"}
                        </span>
                      </div>
                    </div>

                    {f.confidence !== undefined && f.confidence !== null && (
                      <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                        <span>Extraction Confidence:</span>
                        <span
                          className={`font-semibold ${
                            Number(f.confidence) >= 0.85
                              ? "text-emerald-400"
                              : Number(f.confidence) >= 0.6
                              ? "text-amber-400"
                              : "text-rose-400"
                          }`}
                        >
                          {Math.round(Number(f.confidence) * 100)}%
                        </span>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Field Correction Modal */}
      {editingField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-bold text-white">Correct Extracted Field</h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Audited human override for field:{" "}
                  <span className="font-semibold text-blue-400">{editingField.field_name}</span>
                </p>
              </div>
              <button
                onClick={() => setEditingField(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {actionError && (
              <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center space-x-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>{actionError}</span>
              </div>
            )}

            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 font-medium mb-1">
                  Original Raw Value (Source Text - Immutable)
                </label>
                <div className="p-2.5 rounded-lg bg-[#080d1a] border border-[#1e293b] font-mono text-slate-300">
                  {editingField.raw_value || "—"}
                </div>
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  New Normalized Value <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-white focus:outline-none focus:border-blue-500 font-mono"
                  placeholder="Enter corrected value (e.g. 2500.00)"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Reviewer Name <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={reviewerInput}
                  onChange={(e) => setReviewerInput(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-white focus:outline-none focus:border-blue-500"
                  placeholder="e.g. John Doe (Lead Compliance Officer)"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Justification Notes <span className="text-rose-400">*</span>
                </label>
                <textarea
                  value={correctionNotes}
                  onChange={(e) => setCorrectionNotes(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-white focus:outline-none focus:border-blue-500"
                  placeholder="Explain reason for correction based on source document (e.g. OCR misread $2,500.00 as $2,300.00)..."
                />
              </div>

              {!auditorKey && (
                <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300">
                  Auditor key is not configured in this session. Click &quot;Auditor Session&quot; in the header or enter it to proceed.
                </div>
              )}
            </div>

            <div className="flex items-center justify-end space-x-3 pt-2">
              <button
                onClick={() => setEditingField(null)}
                className="px-4 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-slate-300 hover:text-white text-xs font-medium"
              >
                Cancel
              </button>
              <button
                onClick={() => correctionMutation.mutate()}
                disabled={correctionMutation.isPending || !newValue.trim() || !correctionNotes.trim()}
                className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-semibold shadow-lg shadow-blue-500/20"
              >
                {correctionMutation.isPending ? "Submitting..." : "Apply & Audit Correction"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Field Audit Trail Modal */}
      {viewingAuditField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-bold text-white">Immutable Field Audit Trail</h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Permanent history for: <span className="font-semibold text-blue-400">{viewingAuditField.field_name}</span>
                </p>
              </div>
              <button
                onClick={() => setViewingAuditField(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 max-h-96 overflow-y-auto">
              {isAuditLoading ? (
                <div className="p-8 text-center text-slate-400 text-xs">Loading audit records...</div>
              ) : auditTrail.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-xs">
                  No manual corrections recorded for this field. Value reflects initial automated extraction.
                </div>
              ) : (
                auditTrail.map((log) => (
                  <div
                    key={log.id}
                    className="p-3.5 rounded-xl bg-[#0f172a] border border-[#1e293b] text-xs space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-200">{log.reviewer_label}</span>
                      <span className="text-[11px] text-slate-500 font-mono">
                        {new Date(log.created_at).toLocaleString()}
                      </span>
                    </div>

                    <div className="flex items-center space-x-2 text-[11px]">
                      <span className="text-slate-400 line-through font-mono">
                        {log.old_normalized_value || "None"}
                      </span>
                      <span className="text-slate-500">&rarr;</span>
                      <span className="text-emerald-400 font-semibold font-mono">
                        {log.new_normalized_value}
                      </span>
                    </div>

                    <p className="text-slate-400 italic text-[11px]">&ldquo;{log.notes}&rdquo;</p>
                  </div>
                ))
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setViewingAuditField(null)}
                className="px-4 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-slate-300 hover:text-white text-xs font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

