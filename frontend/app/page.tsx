"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  CreditCard,
  FileText,
  CheckSquare,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Coins,
  FileCheck,
  TrendingUp,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import { useDemoFilter } from "@/lib/demo-filter-context";
import {
  getDashboardSummary,
  DashboardSummaryResponse,
  CurrencyVolume,
  ActivityDataPoint,
} from "@/lib/api";

export default function OverviewPage() {
  const { includeDemo, setIncludeDemo, toggleDemo } = useDemoFilter();

  const {
    data: summary,
    isLoading,
    isRefetching,
    refetch,
  } = useQuery<DashboardSummaryResponse>({
    queryKey: ["dashboard-summary", includeDemo],
    queryFn: () => getDashboardSummary({ include_demo: includeDemo }),
    refetchInterval: 10000,
  });

  const totalDocuments = summary?.documents_by_status
    ? Object.values(summary.documents_by_status).reduce((acc, curr) => acc + curr, 0)
    : 0;

  return (
    <AppShell activeNav="overview">
      <div className="space-y-8 p-6 max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Executive Overview</h1>
            <p className="text-xs text-slate-400 mt-1">
              Real-time audit intelligence, PostgreSQL source-of-truth balances, and PayPal Sandbox settlement.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Seeded Data Toggle Switch */}
            <div className="flex items-center space-x-3 bg-[#0c1322] border border-[#1e293b] rounded-xl px-3.5 py-1.5 shadow-sm">
              <div className="flex flex-col">
                <span className="text-xs font-semibold text-slate-200">Include Seeded Demo Data</span>
                <span className="text-[10px] text-slate-400">
                  {includeDemo ? "Showing all data including seeds" : "Filtering to uploaded docs & real data only"}
                </span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={includeDemo}
                onClick={toggleDemo}
                className={`relative inline-flex h-5 w-10 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  includeDemo ? "bg-blue-600" : "bg-slate-700"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    includeDemo ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
              <span
                className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                  includeDemo
                    ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                    : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                }`}
              >
                {includeDemo ? "All Seeds" : "Uploaded Only"}
              </span>
            </div>

            <button
              onClick={() => refetch()}
              disabled={isRefetching}
              className="inline-flex items-center px-3.5 py-2 rounded-xl border border-[#1e293b] bg-[#0c1322] hover:bg-[#1e293b] text-xs font-medium text-slate-300 transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isRefetching ? "animate-spin" : ""}`} />
              Refresh Overview
            </button>
          </div>
        </div>

        {/* Filter Alert Banner when demo data is disabled */}
        {!includeDemo && (
          <div className="flex items-center justify-between p-3.5 rounded-xl bg-emerald-950/30 border border-emerald-500/30 text-emerald-300 text-xs shadow-md">
            <div className="flex items-center space-x-2.5">
              <ShieldCheck className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              <span>
                <strong>Uploaded Data Mode Active:</strong> Seeded demo records are excluded. Showing only your uploaded documents, invoices, and live non-demo records (<code className="font-mono text-[11px] bg-emerald-900/40 px-1 py-0.5 rounded">is_demo = false</code>).
              </span>
            </div>
            <button
              onClick={() => setIncludeDemo(true)}
              className="text-[11px] font-semibold underline hover:text-emerald-200 ml-4 flex-shrink-0"
            >
              Reset to show all seeded data
            </button>
          </div>
        )}

        {/* Top 3 Metric Cards (Dark Navy Screenshot Style) */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6">
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-5 shadow-xl space-y-3">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Open records
            </span>
            <div className="flex items-baseline space-x-2">
              <span className="text-3xl font-extrabold text-white">
                {isLoading ? "..." : summary?.open_records_count ?? 0}
              </span>
            </div>
            <p className="text-xs text-slate-500">Across export transactions</p>
          </div>

          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-5 shadow-xl space-y-3">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Need review
            </span>
            <div className="flex items-baseline space-x-2">
              <span className="text-3xl font-extrabold text-amber-400">
                {isLoading ? "..." : summary?.need_review_count ?? 0}
              </span>
            </div>
            <p className="text-xs text-slate-500">Human decision required</p>
          </div>

          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-5 shadow-xl space-y-3">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Sandbox payments
            </span>
            <div className="flex items-baseline space-x-2">
              <span className="text-3xl font-extrabold text-blue-400">
                {isLoading ? "..." : summary?.sandbox_payments_count ?? 0}
              </span>
            </div>
            <p className="text-xs text-slate-500">Simulated PayPal events</p>
          </div>
        </div>

        {/* Quick Workflow Action Banners */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            href="/reconciliation"
            className="p-5 rounded-2xl bg-gradient-to-br from-blue-900/30 to-[#0c1322] border border-blue-500/30 hover:border-blue-400 transition-all group shadow-lg"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 rounded-xl bg-blue-500/10 text-blue-400">
                  <CheckSquare className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white group-hover:text-blue-300 transition-colors">
                    Reconciliation Queue
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">Inspect matches & decide</p>
                </div>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-blue-300 transition-colors" />
            </div>
          </Link>

          <Link
            href="/documents"
            className="p-5 rounded-2xl bg-[#0c1322] border border-[#1e293b] hover:border-slate-600 transition-all group shadow-lg"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 rounded-xl bg-slate-800 text-slate-300">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white group-hover:text-slate-200 transition-colors">
                    Document Registry
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">Upload & verify hashes</p>
                </div>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-slate-200 transition-colors" />
            </div>
          </Link>

          <Link
            href="/payments"
            className="p-5 rounded-2xl bg-[#0c1322] border border-[#1e293b] hover:border-slate-600 transition-all group shadow-lg"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-400">
                  <CreditCard className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white group-hover:text-amber-300 transition-colors">
                    PayPal Sandbox
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">Checkout & receipts</p>
                </div>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-amber-300 transition-colors" />
            </div>
          </Link>
        </div>

        {/* Currency Volumes & Provenance Breakdown */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Payment Volume Grouped by Currency (Strictly no cross-currency sums!) */}
          <div className="lg:col-span-7 bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#1e293b] pb-4">
              <div className="flex items-center space-x-2">
                <Coins className="w-5 h-5 text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Payment Volumes by Currency</h2>
              </div>
              <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
                PostgreSQL Authoritative
              </span>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              In accordance with financial compliance rules, monetary figures are strictly grouped by currency
              and never combined into a single floating-point sum.
            </p>

            {isLoading ? (
              <div className="p-8 text-center text-slate-500 text-xs">Computing currency aggregates...</div>
            ) : !summary?.payments_by_currency || summary.payments_by_currency.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-xs">No captured payments recorded yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300 divide-y divide-[#1e293b]">
                  <thead className="bg-[#080d1a] text-[11px] font-semibold text-slate-400 uppercase">
                    <tr>
                      <th className="px-4 py-2.5">Currency</th>
                      <th className="px-4 py-2.5">Payments</th>
                      <th className="px-4 py-2.5 text-right">Total Gross</th>
                      <th className="px-4 py-2.5 text-right">Fees</th>
                      <th className="px-4 py-2.5 text-right">Total Net</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1e293b]/60 font-mono">
                    {summary.payments_by_currency.map((cv: CurrencyVolume) => (
                      <tr key={cv.currency} className="hover:bg-[#0f172a]">
                        <td className="px-4 py-3 font-bold text-white">{cv.currency}</td>
                        <td className="px-4 py-3 text-slate-300 font-sans">{cv.payment_count}</td>
                        <td className="px-4 py-3 text-right font-semibold text-white">{cv.total_gross}</td>
                        <td className="px-4 py-3 text-right text-slate-400">{cv.total_fee}</td>
                        <td className="px-4 py-3 text-right font-bold text-emerald-400">{cv.total_net}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Right: Demo vs Non-Demo Records & Ingestion Health */}
          <div className="lg:col-span-5 space-y-6">
            {/* Demo vs Non-Demo Breakdown */}
            <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-[#1e293b] pb-4">
                <div className="flex items-center space-x-2">
                  <ShieldCheck className="w-5 h-5 text-blue-400" />
                  <h2 className="text-base font-semibold text-white">Record Classification</h2>
                </div>
                <span
                  className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                    includeDemo
                      ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                      : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                  }`}
                >
                  {includeDemo ? "Viewing: All Records" : "Viewing: Uploaded Only"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Demo Deals</span>
                  <p className="text-lg font-bold text-white mt-1">
                    {summary?.demo_breakdown.demo_transactions ?? 0}
                  </p>
                </div>

                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Non-Demo Deals</span>
                  <p className="text-lg font-bold text-slate-300 mt-1">
                    {summary?.demo_breakdown.non_demo_transactions ?? 0}
                  </p>
                </div>

                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Demo Payments</span>
                  <p className="text-lg font-bold text-white mt-1">
                    {summary?.demo_breakdown.demo_payments ?? 0}
                  </p>
                </div>

                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-[10px] text-slate-500 uppercase font-semibold">Non-Demo Payments</span>
                  <p className="text-lg font-bold text-slate-300 mt-1">
                    {summary?.demo_breakdown.non_demo_payments ?? 0}
                  </p>
                </div>
              </div>
            </div>

            {/* Document Ingestion Breakdown */}
            <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
              <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-4">
                <FileCheck className="w-5 h-5 text-indigo-400" />
                <h2 className="text-base font-semibold text-white">Ingestion Pipeline</h2>
              </div>

              <div className="space-y-2 text-xs">
                <div className="flex justify-between items-center text-slate-300">
                  <span>Total Ingested Documents</span>
                  <span className="font-bold text-white">{totalDocuments}</span>
                </div>
                <div className="flex justify-between items-center text-slate-400">
                  <span>Extracted & Validated</span>
                  <span className="text-emerald-400 font-semibold">
                    {summary?.documents_by_status?.["extracted"] ?? 0}
                  </span>
                </div>
                <div className="flex justify-between items-center text-slate-400">
                  <span>Pending Review</span>
                  <span className="text-amber-400 font-semibold">
                    {summary?.documents_by_status?.["needs_review"] ?? 0}
                  </span>
                </div>
                <div className="flex justify-between items-center text-slate-400">
                  <span>Parsed & In Processing</span>
                  <span className="text-indigo-400 font-semibold">
                    {summary?.documents_by_status?.["parsed"] ?? 0}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Recent Activity Trend (Dark SVG Chart) */}
        {summary?.recent_activity && summary.recent_activity.length > 0 && (
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#1e293b] pb-4">
              <div className="flex items-center space-x-2">
                <TrendingUp className="w-5 h-5 text-blue-400" />
                <h2 className="text-base font-semibold text-white">Activity Trend</h2>
              </div>
              <span className="text-xs text-slate-400">Transactions & Payment Captures</span>
            </div>

            <div className="h-44 flex items-end space-x-2 pt-6">
              {summary.recent_activity.slice(-14).map((d: ActivityDataPoint) => {
                const total = d.payments_captured + d.matches_proposed;
                const heightPct = Math.min(100, Math.max(12, total * 20));
                return (
                  <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
                    <div className="text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity">
                      {total}
                    </div>
                    <div
                      style={{ height: `${heightPct}%` }}
                      className="w-full rounded-t bg-gradient-to-t from-blue-600 to-indigo-500 group-hover:from-blue-500 group-hover:to-indigo-400 transition-all shadow-md shadow-blue-500/10"
                    />
                    <span className="text-[9px] text-slate-500 mt-1 font-mono">
                      {d.date.slice(5)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
