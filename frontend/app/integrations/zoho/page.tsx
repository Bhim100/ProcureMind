"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Link2,
  Link2Off,
  ExternalLink,
  ArrowLeft,
  Sparkles,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  FileText,
  DollarSign,
  Building2,
  Clock,
  Layers,
  ArrowRight,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import {
  getZohoStatus,
  getZohoAuthUrl,
  syncZohoInvoices,
  simulateZohoSync,
  disconnectZoho,
  ZohoSyncResult,
} from "@/lib/api";

export default function ZohoIntegrationPage() {
  const queryClient = useQueryClient();
  const [syncFeedback, setSyncFeedback] = useState<{
    type: "success" | "error";
    message: string;
    result?: ZohoSyncResult;
  } | null>(null);

  const {
    data: status,
    isLoading,
    error: statusError,
  } = useQuery({
    queryKey: ["zoho-status"],
    queryFn: getZohoStatus,
    refetchInterval: 10000,
  });

  const { data: authUrlData } = useQuery({
    queryKey: ["zoho-auth-url"],
    queryFn: getZohoAuthUrl,
  });

  const syncMutation = useMutation({
    mutationFn: () => syncZohoInvoices(10),
    onSuccess: (data) => {
      setSyncFeedback({
        type: "success",
        message: data.message,
        result: data,
      });
      queryClient.invalidateQueries({ queryKey: ["zoho-status"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: Error) => {
      setSyncFeedback({
        type: "error",
        message: err.message || "Failed to synchronize invoices with Zoho Books.",
      });
    },
  });

  const simulateMutation = useMutation({
    mutationFn: () => simulateZohoSync(1),
    onSuccess: (data) => {
      setSyncFeedback({
        type: "success",
        message: data.message,
        result: data,
      });
      queryClient.invalidateQueries({ queryKey: ["zoho-status"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: Error) => {
      setSyncFeedback({
        type: "error",
        message: err.message || "Simulation failed.",
      });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectZoho,
    onSuccess: () => {
      setSyncFeedback({
        type: "success",
        message: "Zoho Books organization disconnected.",
      });
      queryClient.invalidateQueries({ queryKey: ["zoho-status"] });
    },
    onError: (err: Error) => {
      setSyncFeedback({
        type: "error",
        message: err.message || "Disconnect failed.",
      });
    },
  });

  return (
    <AppShell activeNav="zoho">
      <div className="max-w-5xl mx-auto space-y-6 pb-12">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Link
              href="/reconciliation"
              className="p-2 rounded-lg bg-[#0c1322] border border-[#1e293b] text-slate-400 hover:text-white transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div>
              <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
                Zoho Books ERP Connector
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Automated commercial invoice ingestion & general ledger synchronization.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => simulateMutation.mutate()}
              disabled={simulateMutation.isPending}
              className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all disabled:opacity-50"
              title="Test ingestion of commercial invoices and vector PDFs without API credentials"
            >
              <Sparkles className={`w-3.5 h-3.5 ${simulateMutation.isPending ? "animate-spin" : ""}`} />
              <span>{simulateMutation.isPending ? "Importing..." : "⚡ Simulate Zoho Import"}</span>
            </button>
          </div>
        </div>

        {/* Feedback Alert */}
        {syncFeedback && (
          <div
            className={`p-4 rounded-xl border flex items-start justify-between text-xs animate-in fade-in duration-200 ${
              syncFeedback.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}
          >
            <div className="flex items-center space-x-2.5">
              {syncFeedback.type === "success" ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              ) : (
                <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
              )}
              <span>{syncFeedback.message}</span>
            </div>
            <button
              onClick={() => setSyncFeedback(null)}
              className="text-slate-400 hover:text-white font-medium ml-4 underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Connection Status Card */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#1e293b] pb-6">
            <div className="flex items-center space-x-4">
              <div
                className={`w-12 h-12 rounded-2xl flex items-center justify-center border ${
                  status?.is_connected
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                    : "bg-amber-500/10 border-amber-500/30 text-amber-400"
                }`}
              >
                {status?.is_connected ? (
                  <Link2 className="w-6 h-6" />
                ) : (
                  <Link2Off className="w-6 h-6" />
                )}
              </div>
              <div>
                <div className="flex items-center space-x-2.5">
                  <h2 className="text-base font-bold text-white">
                    {status?.organization_name || "Zoho Books Organization"}
                  </h2>
                  <span
                    className={`text-[11px] px-2.5 py-0.5 rounded-full font-semibold uppercase tracking-wider border ${
                      status?.is_connected
                        ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                        : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                    }`}
                  >
                    {status?.is_connected ? "Connected & Active" : "Disconnected"}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  {status?.is_connected
                    ? `Org ID: ${status.organization_id} • API Domain: ${status.api_domain}`
                    : "Connect via OAuth 2.0 or simulate invoice sync to test automated document extraction."}
                </p>
              </div>
            </div>

            <div className="flex items-center space-x-3">
              {status?.is_connected ? (
                <>
                  <button
                    onClick={() => syncMutation.mutate()}
                    disabled={syncMutation.isPending}
                    className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-blue-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${syncMutation.isPending ? "animate-spin" : ""}`} />
                    <span>{syncMutation.isPending ? "Syncing..." : "Sync Invoices Now"}</span>
                  </button>
                  <button
                    onClick={() => disconnectMutation.mutate()}
                    disabled={disconnectMutation.isPending}
                    className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 hover:bg-rose-500/20 text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    <span>Disconnect</span>
                  </button>
                </>
              ) : (
                <a
                  href={authUrlData?.auth_url || "https://api-console.zoho.com"}
                  target={authUrlData?.configured ? "_self" : "_blank"}
                  rel="noreferrer"
                  className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-colors"
                >
                  <Link2 className="w-3.5 h-3.5" />
                  <span>Connect Zoho Books</span>
                  <ExternalLink className="w-3 h-3 ml-1" />
                </a>
              )}
            </div>
          </div>

          {/* Telemetry KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-[#080d1a] border border-[#1e293b] rounded-xl p-4 flex items-center space-x-3">
              <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 flex-shrink-0">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Synced Documents</p>
                <p className="text-xl font-bold text-white mt-0.5">
                  {isLoading ? "..." : status?.synced_documents_count ?? 0}
                </p>
              </div>
            </div>

            <div className="bg-[#080d1a] border border-[#1e293b] rounded-xl p-4 flex items-center space-x-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 flex-shrink-0">
                <DollarSign className="w-5 h-5" />
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Total Synced Volume</p>
                <p className="text-xl font-bold text-emerald-400 mt-0.5">
                  {isLoading
                    ? "..."
                    : `$${Number(status?.total_synced_amount || 0).toLocaleString("en-US", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })} ${status?.currency || "USD"}`}
                </p>
              </div>
            </div>

            <div className="bg-[#080d1a] border border-[#1e293b] rounded-xl p-4 flex items-center space-x-3">
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 flex-shrink-0">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Last Sync Time</p>
                <p className="text-sm font-semibold text-slate-200 mt-1 truncate">
                  {status?.last_sync_at
                    ? new Date(status.last_sync_at).toLocaleString()
                    : "Never synced"}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Synced Invoices Section */}
        {syncFeedback?.result && syncFeedback.result.invoices.length > 0 && (
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#1e293b] pb-4">
              <div className="flex items-center space-x-2">
                <Layers className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  Recently Ingested Invoices
                </h3>
              </div>
              <span className="text-xs text-slate-400">
                {syncFeedback.result.invoices.length} document(s) registered
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#1e293b] text-slate-400 bg-[#080d1a]/50">
                    <th className="py-2.5 px-3">Invoice Number</th>
                    <th className="py-2.5 px-3">Document Filename</th>
                    <th className="py-2.5 px-3 text-right">Amount</th>
                    <th className="py-2.5 px-3 text-center">Extraction Status</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1e293b]">
                  {syncFeedback.result.invoices.map((inv) => (
                    <tr key={inv.document_id} className="hover:bg-[#080d1a]/40 transition-colors">
                      <td className="py-3 px-3 font-mono font-semibold text-blue-400">
                        {inv.invoice_number}
                      </td>
                      <td className="py-3 px-3 text-slate-300 font-medium truncate max-w-xs">
                        {inv.filename}
                      </td>
                      <td className="py-3 px-3 text-right font-mono text-emerald-400 font-semibold">
                        ${Number(inv.total_amount).toFixed(2)} {inv.currency}
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                          {inv.status}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right space-x-2">
                        <Link
                          href={`/documents/${inv.document_id}/review`}
                          className="inline-flex items-center space-x-1 px-2.5 py-1 rounded bg-[#080d1a] border border-[#1e293b] text-slate-300 hover:text-white transition-colors"
                        >
                          <span>Review</span>
                          <ArrowRight className="w-3 h-3" />
                        </Link>
                        <Link
                          href="/reconciliation"
                          className="inline-flex items-center space-x-1 px-2.5 py-1 rounded bg-blue-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 transition-colors"
                        >
                          <span>Reconcile</span>
                          <ArrowRight className="w-3 h-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Configuration Guide */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-3">
            <Building2 className="w-4 h-4 text-blue-400" />
            <h3 className="text-sm font-bold text-white">How Zoho Books Ingestion Works</h3>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            ProcureMind connects directly to the Zoho Books REST API v3 to pull commercial invoices and official PDF copies into our secure private document storage.
            Each ingested PDF is fingerprinted with SHA-256 for duplicate prevention and audit traceability, then parsed by our AI pipeline to link line items and trade deals directly into the Reconciliation Queue.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-blue-400 font-bold text-xs">1. Direct Stream</span>
              <p className="text-[11px] text-slate-400">
                Pulls invoice metadata and binary vector PDFs via official Zoho endpoints.
              </p>
            </div>
            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-emerald-400 font-bold text-xs">2. SHA-256 Digest</span>
              <p className="text-[11px] text-slate-400">
                Cryptographically dedupes files and logs source provenance in PostgreSQL.
              </p>
            </div>
            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-purple-400 font-bold text-xs">3. Instant Recon</span>
              <p className="text-[11px] text-slate-400">
                Auto-generates trade transactions ready for cross-document diff and payment matching.
              </p>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
