"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Upload,
  ArrowRight,
  Package,
  FileText,
  CreditCard,
  CheckCircle2,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  Search,
  RefreshCw,
  X,
  FileCheck,
  GitCompare,
  CheckSquare,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import DocumentDiffView from "@/components/documents/DocumentDiffView";
import { useAuditor } from "@/lib/auditor-session";
import { useDemoFilter } from "@/lib/demo-filter-context";
import {
  getReconciliationQueue,
  getDashboardSummary,
  decideMatch,
  investigateTransaction,
  ReconciliationQueueRow,
} from "@/lib/api";

export default function ReconciliationPage() {
  const queryClient = useQueryClient();
  const { auditorKey, reviewerLabel } = useAuditor();
  const { includeDemo } = useDemoFilter();

  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [search, setSearch] = useState("");
  const [selectedTxId, setSelectedTxId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"queue" | "diff">("queue");

  // Match decision modal state
  const [decisionModalMatch, setDecisionModalMatch] = useState<{
    id: string;
    ruleId: string;
    amount: string;
    currency: string;
  } | null>(null);
  const [decisionType, setDecisionType] = useState<"approved" | "rejected">("approved");
  const [decisionNotes, setDecisionNotes] = useState("");
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Fetch reconciliation queue with demo filter
  const {
    data: queueData,
    isLoading: isQueueLoading,
    isError: isQueueError,
    refetch: refetchQueue,
  } = useQuery({
    queryKey: ["reconciliationQueue", page, pageSize, search, includeDemo],
    queryFn: () =>
      getReconciliationQueue({
        page,
        page_size: pageSize,
        search: search.trim() || undefined,
        is_demo: includeDemo ? undefined : false,
      }),
  });

  // Fetch dashboard summary for top stat cards
  const { data: summaryData } = useQuery({
    queryKey: ["dashboardSummary", includeDemo],
    queryFn: () => getDashboardSummary({ include_demo: includeDemo }),
  });

  // Select first transaction or maintain valid selected transaction
  useEffect(() => {
    if (queueData && queueData.items.length > 0) {
      if (!selectedTxId || !queueData.items.some((item) => item.transaction_id === selectedTxId)) {
        setSelectedTxId(queueData.items[0].transaction_id);
      }
    } else if (queueData && queueData.items.length === 0) {
      setSelectedTxId(null);
    }
  }, [queueData, selectedTxId]);

  const selectedRecord: ReconciliationQueueRow | undefined = queueData?.items.find(
    (item) => item.transaction_id === selectedTxId
  );

  // Investigation query for grounded AI explanation
  const { data: investigationData, isLoading: isInvestigating } = useQuery({
    queryKey: ["investigation", selectedRecord?.reference],
    queryFn: () =>
      selectedRecord ? investigateTransaction(selectedRecord.reference, "Explain payment shortfall and missing evidence") : null,
    enabled: !!selectedRecord,
  });

  // Decide match mutation
  const matchDecisionMutation = useMutation({
    mutationFn: async (payload: { matchId: string; decision: "approved" | "rejected"; notes: string }) => {
      if (!auditorKey) {
        throw new Error("Auditor Key is required. Please click 'Config' in the sidebar footer to set your session key.");
      }
      return decideMatch(
        payload.matchId,
        {
          decision: payload.decision,
          reviewer_label: reviewerLabel,
          notes: payload.notes,
        },
        auditorKey
      );
    },
    onSuccess: () => {
      setDecisionModalMatch(null);
      setDecisionNotes("");
      setDecisionError(null);
      queryClient.invalidateQueries({ queryKey: ["reconciliationQueue"] });
      queryClient.invalidateQueries({ queryKey: ["dashboardSummary"] });
    },
    onError: (err: any) => {
      setDecisionError(err.message || "Failed to record match decision");
    },
  });

  const handleExportReport = () => {
    if (!queueData) return;
    const jsonStr = JSON.stringify(queueData.items, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reconciliation-report-${new Date().toISOString().split("T")[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDecisionSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!decisionNotes.trim() || decisionNotes.trim().length < 3) {
      setDecisionError("A justification comment of at least 3 characters is required.");
      return;
    }
    if (!decisionModalMatch) return;
    matchDecisionMutation.mutate({
      matchId: decisionModalMatch.id,
      decision: decisionType,
      notes: decisionNotes.trim(),
    });
  };

  return (
    <AppShell currentBreadcrumb="Demo workspace / Reconciliation">
      <div className="p-8 max-w-[1600px] mx-auto space-y-6">
        {/* Top Header Row matching screenshot */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Reconciliation</h1>
            <p className="text-xs text-slate-400 mt-1">
              Review trade records and resolve exceptions with source evidence.
            </p>
          </div>

          <div className="flex items-center space-x-3">
            {/* View Mode Switcher */}
            <div className="flex items-center space-x-1 bg-[#0c1322] border border-[#1e293b] p-1 rounded-xl shadow-sm">
              <button
                onClick={() => setViewMode("queue")}
                className={`inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  viewMode === "queue"
                    ? "bg-blue-600 text-white shadow-md shadow-blue-500/20"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <CheckSquare className="w-3.5 h-3.5" />
                <span>Reconciliation Queue</span>
              </button>
              <button
                onClick={() => setViewMode("diff")}
                className={`inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  viewMode === "diff"
                    ? "bg-blue-600 text-white shadow-md shadow-blue-500/20"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                <GitCompare className="w-3.5 h-3.5" />
                <span>Compare Documents</span>
              </button>
            </div>

            <button
              onClick={handleExportReport}
              className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-lg bg-[#111927] hover:bg-[#182338] border border-[#1e2d48] text-xs font-medium text-slate-200 transition-colors shadow-sm"
            >
              <Download className="w-3.5 h-3.5 text-slate-400" />
              <span>Export report</span>
            </button>
            <Link
              href="/documents"
              className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-sm transition-colors"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Upload document</span>
            </Link>
          </div>
        </div>

        {viewMode === "queue" ? (
          <>
            {/* 3 Top Summary Stat Cards matching screenshot */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-[#0f172a] border border-[#1e293b] rounded-xl p-5 space-y-2 shadow-sm">
            <p className="text-xs font-medium text-slate-400">Open records</p>
            <p className="text-3xl font-bold text-slate-100 tracking-tight">
              {summaryData?.open_records_count ?? (queueData?.total_count ?? 0)}
            </p>
            <p className="text-[11px] text-slate-400">Across demo transactions</p>
          </div>

          <div className="bg-[#0f172a] border border-[#1e293b] rounded-xl p-5 space-y-2 shadow-sm">
            <p className="text-xs font-medium text-slate-400">Need review</p>
            <p className="text-3xl font-bold text-slate-100 tracking-tight">
              {summaryData?.need_review_count ??
                (queueData?.items.filter((i) => i.requires_human_review).length ?? 0)}
            </p>
            <p className="text-[11px] text-amber-400/90 font-medium">Human decision required</p>
          </div>

          <div className="bg-[#0f172a] border border-[#1e293b] rounded-xl p-5 space-y-2 shadow-sm">
            <p className="text-xs font-medium text-slate-400">Sandbox payments</p>
            <p className="text-3xl font-bold text-slate-100 tracking-tight">
              {summaryData?.sandbox_payments_count ?? 0}
            </p>
            <p className="text-[11px] text-slate-400">Simulated PayPal events</p>
          </div>
        </div>

        {/* Main Grid: Worklist on Left, Exception Details on Right matching screenshot */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Trade records worklist table (lg:col-span-5) */}
          <div className="lg:col-span-5 bg-[#0f172a] border border-[#1e293b] rounded-xl p-5 space-y-4 shadow-sm">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-100">Trade records</h2>
                <p className="text-[11px] text-slate-400">Demo transactions · updated moments ago</p>
              </div>
              <button
                onClick={() => refetchQueue()}
                className="text-xs text-blue-400 hover:text-blue-300 font-medium inline-flex items-center space-x-1"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Refresh</span>
              </button>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                placeholder="Search by reference or buyer..."
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="w-full pl-9 pr-3 py-1.5 bg-[#141e33] border border-[#1e2d48] rounded-lg text-xs text-slate-100 placeholder-slate-400 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* High-density Worklist Table matching screenshot columns */}
            <div className="border border-[#182338] rounded-lg overflow-hidden bg-[#0c1322]">
              <div className="grid grid-cols-12 px-3 py-2 bg-[#121b2d] text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-[#182338]">
                <div className="col-span-6">Reference</div>
                <div className="col-span-6">Buyer</div>
              </div>

              {isQueueLoading ? (
                <div className="p-8 text-center text-xs text-slate-400">Loading trade records...</div>
              ) : isQueueError ? (
                <div className="p-8 text-center text-xs text-red-400">Failed to load reconciliation queue.</div>
              ) : queueData?.items.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-400">No trade records found.</div>
              ) : (
                <div className="divide-y divide-[#141e33]">
                  {queueData?.items.map((row) => {
                    const isSelected = row.transaction_id === selectedTxId;
                    const primaryInvoice = row.invoices[0];

                    return (
                      <div
                        key={row.transaction_id}
                        onClick={() => setSelectedTxId(row.transaction_id)}
                        className={`grid grid-cols-12 px-3 py-3 cursor-pointer transition-colors text-xs items-center ${
                          isSelected
                            ? "bg-[#182742] border-l-2 border-blue-500"
                            : "hover:bg-[#10192b]"
                        }`}
                      >
                        <div className="col-span-6 space-y-0.5">
                          <p className="font-semibold text-blue-400">{row.reference}</p>
                          <p className="text-[10px] text-slate-400">
                            {primaryInvoice ? primaryInvoice.invoice_number : "No invoice"}
                          </p>
                        </div>
                        <div className="col-span-6 flex items-center justify-between">
                          <span className="truncate text-slate-200 font-medium text-xs">
                            {row.buyer_name}
                          </span>
                          {row.requires_human_review && (
                            <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0 ml-2" />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Pagination Controls */}
            {queueData && queueData.total_pages > 1 && (
              <div className="flex items-center justify-between text-xs text-slate-400 pt-2">
                <span>
                  Page {queueData.page} of {queueData.total_pages} ({queueData.total_count} deals)
                </span>
                <div className="flex space-x-1">
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="p-1.5 rounded bg-[#141e33] border border-[#1e2d48] disabled:opacity-40"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>
                  <button
                    disabled={page >= queueData.total_pages}
                    onClick={() => setPage((p) => p + 1)}
                    className="p-1.5 rounded bg-[#141e33] border border-[#1e2d48] disabled:opacity-40"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Exception details pane (lg:col-span-7) matching screenshot */}
          <div className="lg:col-span-7 bg-[#0f172a] border border-[#1e293b] rounded-xl p-6 space-y-6 shadow-sm">
            {selectedRecord ? (
              <>
                {/* Header & Status */}
                <div>
                  <p className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
                    Exception details
                  </p>
                  <p className="text-xs text-slate-400">{selectedRecord.reference}</p>
                </div>

                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="text-xl font-bold text-slate-100">{selectedRecord.buyer_name}</h2>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {selectedRecord.invoices[0]
                        ? `Invoice ${selectedRecord.invoices[0].invoice_number} · ${selectedRecord.currency}`
                        : `Deal ${selectedRecord.reference} · ${selectedRecord.currency}`}
                    </p>
                  </div>

                  <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/80 shadow-sm">
                    {selectedRecord.status_label}
                  </span>
                </div>

                {/* Amount Comparison Cards matching screenshot */}
                {selectedRecord.invoices[0] && selectedRecord.payments[0] && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
                    <div className="bg-[#121c2e] border border-[#1e2d48] rounded-xl p-4 space-y-1">
                      <p className="text-[11px] font-medium text-slate-400">Invoice total</p>
                      <p className="text-xl font-bold text-slate-100">
                        ${Number(selectedRecord.invoices[0].total_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}
                      </p>
                    </div>

                    <div className="bg-[#121c2e] border border-[#1e2d48] rounded-xl p-4 space-y-1">
                      <p className="text-[11px] font-medium text-slate-400">Sandbox payment</p>
                      <p className="text-xl font-bold text-slate-100">
                        ${Number(selectedRecord.payments[0].gross_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}
                      </p>
                    </div>
                  </div>
                )}

                {/* Shortfall banner if exists matching screenshot */}
                {selectedRecord.shortfall_amount && (
                  <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-[#3d1a1a] border border-[#5c2424] text-xs font-semibold text-[#ff7b72]">
                    <span>Payment shortfall</span>
                    <span className="font-mono text-sm">
                      ${Number(selectedRecord.shortfall_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                )}

                {/* Evidence Used List matching screenshot */}
                <div className="space-y-3">
                  <p className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
                    Evidence Used
                  </p>

                  <div className="space-y-2">
                    {/* Commercial Invoice Citation */}
                    {selectedRecord.invoices[0] && (
                      <div className="flex items-start space-x-3 p-3 rounded-lg bg-[#111928] border border-[#182338]">
                        <FileText className="w-4 h-4 text-slate-400 mt-0.5 flex-shrink-0" />
                        <div className="text-xs space-y-0.5">
                          <p className="font-semibold text-slate-200">Commercial invoice</p>
                          <p className="text-[11px] text-slate-400">
                            Page 1 · total USD {Number(selectedRecord.invoices[0].total_amount).toFixed(2)}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* PayPal Sandbox Capture Citation */}
                    {selectedRecord.payments[0] && (
                      <div className="flex items-start space-x-3 p-3 rounded-lg bg-[#111928] border border-[#182338]">
                        <CreditCard className="w-4 h-4 text-slate-400 mt-0.5 flex-shrink-0" />
                        <div className="text-xs space-y-0.5">
                          <p className="font-semibold text-slate-200">PayPal Sandbox capture</p>
                          <p className="text-[11px] text-slate-400">
                            Gross USD {Number(selectedRecord.payments[0].gross_amount).toFixed(2)} · simulated payment
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Attached Evidence references */}
                    {selectedRecord.evidence_references.map((ev) => (
                      <div
                        key={ev.evidence_id}
                        className="flex items-start space-x-3 p-3 rounded-lg bg-[#111928] border border-[#182338]"
                      >
                        <FileCheck className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
                        <div className="text-xs space-y-0.5">
                          <p className="font-semibold text-slate-200">{ev.document_title}</p>
                          <p className="text-[11px] text-slate-400">
                            {ev.location_reference || "Attached record"} {ev.raw_snippet ? `· ${ev.raw_snippet}` : ""}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Grounded Explanation Card matching screenshot */}
                <div className="bg-[#14233c] border border-blue-900/50 rounded-xl p-4 space-y-2">
                  <div className="flex items-center space-x-2 text-[11px] font-semibold text-blue-300">
                    <ShieldCheck className="w-4 h-4 text-blue-400" />
                    <span>Grounded explanation · Human decision required</span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {isInvestigating
                      ? "Generating grounded audit investigation..."
                      : investigationData?.explanation ||
                        `The recorded payment is USD ${selectedRecord.shortfall_amount || "0.00"} below the invoice total. Review the payment evidence before deciding; ProcureMind has not approved or changed the records.`}
                  </p>
                </div>

                {/* Action Buttons matching screenshot */}
                <div className="flex items-center space-x-3 pt-2">
                  {selectedRecord.evidence_references[0]?.document_id ? (
                    <Link
                      href={`/documents/${selectedRecord.evidence_references[0].document_id}/review`}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
                    >
                      Open review
                    </Link>
                  ) : (
                    <Link
                      href="/documents"
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
                    >
                      Open review
                    </Link>
                  )}

                  {selectedRecord.matches[0] && (
                    <button
                      onClick={() => {
                        setDecisionModalMatch({
                          id: selectedRecord.matches[0].match_id,
                          ruleId: selectedRecord.matches[0].rule_id,
                          amount: selectedRecord.matches[0].allocated_amount,
                          currency: selectedRecord.matches[0].currency,
                        });
                        setDecisionType("approved");
                        setDecisionNotes("");
                        setDecisionError(null);
                      }}
                      className="px-4 py-2 bg-[#121c2e] hover:bg-[#182742] text-slate-200 border border-[#1e2d48] rounded-lg text-xs font-medium transition-colors"
                    >
                      Decide Match
                    </button>
                  )}

                  <button
                    onClick={() => setViewMode("diff")}
                    className="px-3.5 py-2 bg-[#121c2e] hover:bg-[#182742] text-slate-200 border border-[#1e2d48] rounded-lg text-xs font-medium transition-colors inline-flex items-center space-x-1.5"
                  >
                    <GitCompare className="w-3.5 h-3.5 text-blue-400" />
                    <span>Compare Documents</span>
                  </button>
                </div>
              </>
            ) : (
              <div className="p-12 text-center text-xs text-slate-400">
                Select a trade record from the left to view details and evidence.
              </div>
            )}
          </div>
        </div>
      </>
    ) : (
      <DocumentDiffView />
    )}
  </div>

      {/* Human Match Decision Modal */}
      {decisionModalMatch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-[#0f172a] border border-slate-700 rounded-xl shadow-2xl max-w-md w-full p-6 text-slate-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="font-semibold text-base text-slate-100">Human Match Decision</h3>
              <button
                onClick={() => setDecisionModalMatch(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleDecisionSubmit} className="space-y-4 pt-4">
              <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg text-xs space-y-1">
                <p className="text-slate-400">Reconciliation Rule: <span className="text-slate-200 font-mono">{decisionModalMatch.ruleId}</span></p>
                <p className="text-slate-400">Allocation Amount: <span className="text-slate-200 font-mono">${decisionModalMatch.amount} {decisionModalMatch.currency}</span></p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Decision</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setDecisionType("approved")}
                    className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                      decisionType === "approved"
                        ? "bg-emerald-950/80 border-emerald-600 text-emerald-300"
                        : "bg-slate-900 border-slate-700 text-slate-400"
                    }`}
                  >
                    Approve Match
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionType("rejected")}
                    className={`py-2 text-xs font-semibold rounded-lg border transition-all ${
                      decisionType === "rejected"
                        ? "bg-red-950/80 border-red-600 text-red-300"
                        : "bg-slate-900 border-slate-700 text-slate-400"
                    }`}
                  >
                    Reject Match
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Audit Notes / Justification (Required)
                </label>
                <textarea
                  required
                  rows={3}
                  value={decisionNotes}
                  onChange={(e) => setDecisionNotes(e.target.value)}
                  placeholder="Enter detailed audit justification for this decision (min 3 characters)..."
                  className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {decisionError && (
                <div className="p-2.5 bg-red-950/70 border border-red-800 rounded-lg text-xs text-red-300">
                  {decisionError}
                </div>
              )}

              <div className="flex items-center justify-end space-x-2 pt-2">
                <button
                  type="button"
                  onClick={() => setDecisionModalMatch(null)}
                  className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={matchDecisionMutation.isPending}
                  className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-sm transition-all"
                >
                  {matchDecisionMutation.isPending ? "Recording..." : "Confirm Decision"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}
