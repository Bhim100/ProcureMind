"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, AlertCircle, Database, Server, ShieldCheck, RefreshCw, FileText, ArrowRight } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface HealthData {
  status: string;
  service: string;
  environment: string;
  timestamp: string;
}

interface ReadinessData {
  status: string;
  service: string;
  environment: string;
  database: {
    status: string;
    database?: string;
    error?: string;
  };
  storage: {
    backend: string;
    status: string;
  };
  secondary_services: {
    falkordb: string;
    chroma: string;
  };
  timestamp: string;
}

export default function Home() {
  const {
    data: health,
    error: healthError,
    isLoading: healthLoading,
    refetch: refetchHealth,
  } = useQuery<HealthData>({
    queryKey: ["health"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/v1/health`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 10000,
  });

  const {
    data: readiness,
    error: readinessError,
    isLoading: readinessLoading,
    refetch: refetchReadiness,
  } = useQuery<ReadinessData>({
    queryKey: ["readiness"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/v1/ready`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 10000,
  });

  const handleRefresh = () => {
    refetchHealth();
    refetchReadiness();
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900">
      {/* Top Navigation */}
      <header className="border-b border-slate-200 bg-white sticky top-0 z-10 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-9 w-9 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-lg shadow-sm">
              PM
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="font-semibold text-lg tracking-tight">ProcureMind</h1>
                <span className="bg-blue-100 text-blue-800 text-xs font-medium px-2 py-0.5 rounded-full">
                  Phase 0: Foundation
                </span>
              </div>
              <p className="text-xs text-slate-500">Autonomous Invoice & PO Reconciliation</p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <Link
              href="/documents"
              className="inline-flex items-center text-xs font-semibold px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-all"
            >
              <FileText className="w-3.5 h-3.5 mr-1.5" />
              Document Registry (Phase 2)
            </Link>
            <button
              onClick={handleRefresh}
              className="inline-flex items-center text-xs font-medium px-2.5 py-1.5 rounded-md border border-slate-300 hover:bg-slate-100 transition-colors"
            >
              <RefreshCw className="h-3 w-3 mr-1.5" />
              Refresh Status
            </button>
            <div className="flex items-center space-x-1.5 text-xs text-slate-600 border-l border-slate-200 pl-3">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>App Shell Active</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Banner */}
        <section className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-bold tracking-tight text-slate-900">
                System Foundation & Diagnostics
              </h2>
              <p className="mt-1 text-sm text-slate-600 max-w-2xl">
                Phase 0 establishes the monorepo foundation, strict boundary architecture, health probes, and runtime configurations. No business workflows (documents, matching, payments) are active.
              </p>
            </div>
            <div className="hidden sm:block text-right text-xs text-slate-400 font-mono">
              Target API: {API_BASE}
            </div>
          </div>
        </section>

        {/* Live Diagnostics Grid */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Health Status */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Server className="h-5 w-5 text-blue-600" />
                <h3 className="font-semibold text-slate-900">Backend Liveness (/health)</h3>
              </div>
              {healthLoading ? (
                <span className="text-xs text-slate-400">Checking...</span>
              ) : health?.status === "ok" ? (
                <span className="inline-flex items-center text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                  <CheckCircle2 className="h-3 w-3 mr-1" /> OK
                </span>
              ) : (
                <span className="inline-flex items-center text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
                  <AlertCircle className="h-3 w-3 mr-1" /> Unreachable
                </span>
              )}
            </div>

            <div className="bg-slate-50 rounded-lg p-3 text-xs font-mono space-y-1.5 border border-slate-100">
              <div className="flex justify-between">
                <span className="text-slate-500">Service:</span>
                <span className="text-slate-800">{health?.service ?? (healthLoading ? "..." : "Offline")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Environment:</span>
                <span className="text-slate-800">{health?.environment ?? "N/A"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Last Verified:</span>
                <span className="text-slate-800">{health?.timestamp ? new Date(health.timestamp).toLocaleTimeString() : "N/A"}</span>
              </div>
              {healthError && (
                <div className="pt-2 text-rose-600 text-2xs">
                  Error: {(healthError as Error).message}. Ensure FastAPI is running on port 8000.
                </div>
              )}
            </div>
          </div>

          {/* Readiness Status */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Database className="h-5 w-5 text-indigo-600" />
                <h3 className="font-semibold text-slate-900">System Readiness (/ready)</h3>
              </div>
              {readinessLoading ? (
                <span className="text-xs text-slate-400">Checking...</span>
              ) : readiness?.status === "ready" ? (
                <span className="inline-flex items-center text-xs font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                  <CheckCircle2 className="h-3 w-3 mr-1" /> Ready
                </span>
              ) : (
                <span className="inline-flex items-center text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
                  <Activity className="h-3 w-3 mr-1" /> Degraded / Standby
                </span>
              )}
            </div>

            <div className="bg-slate-50 rounded-lg p-3 text-xs font-mono space-y-1.5 border border-slate-100">
              <div className="flex justify-between">
                <span className="text-slate-500">Database (PostgreSQL):</span>
                <span className="text-slate-800 font-medium">
                  {readiness?.database?.status ?? (readinessLoading ? "..." : "Offline")}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Document Storage:</span>
                <span className="text-slate-800">
                  {readiness?.storage?.backend ? `${readiness.storage.backend} (${readiness.storage.status})` : "N/A"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">FalkorDB (Secondary):</span>
                <span className="text-slate-800">{readiness?.secondary_services?.falkordb ?? "N/A"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Chroma (Secondary):</span>
                <span className="text-slate-800">{readiness?.secondary_services?.chroma ?? "N/A"}</span>
              </div>
            </div>
          </div>
        </section>

        {/* Architectural Boundaries & Decisions */}
        <section className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center space-x-2">
            <ShieldCheck className="h-5 w-5 text-emerald-600" />
            <h3 className="font-semibold text-slate-900">Confirmed Architectural Boundaries</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-600">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-1">
              <span className="font-semibold text-slate-800 block">PostgreSQL Authoritative</span>
              <p>PostgreSQL (Neon) holds source of truth. FalkorDB and Chroma are secondary query layers and never hold authoritative balance or match status.</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-1">
              <span className="font-semibold text-slate-800 block">FastAPI Domain Authority</span>
              <p>FastAPI manages all business logic, credentials, and API routes. Next.js App Router serves as the UI client and invokes FastAPI endpoints.</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 space-y-1">
              <span className="font-semibold text-slate-800 block">Strict Data Integrity</span>
              <p>All financial balances use Decimal/integer minor units. Source provenance is preserved on every extraction, and AI never performs autonomous payouts.</p>
            </div>
          </div>
        </section>

        {/* Future Modules Placeholder */}
        <section className="border border-dashed border-slate-300 rounded-xl p-8 text-center bg-slate-50/50">
          <p className="text-sm font-medium text-slate-700">ProcureMind Workflows (Upcoming Phases)</p>
          <p className="text-xs text-slate-500 mt-1 max-w-lg mx-auto">
            Document extraction, Purchase Order / Invoice three-way matching, discrepancy resolution, and PayPal sandbox integrations will be introduced incrementally in subsequent phases.
          </p>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-500">
        ProcureMind Architecture Monorepo &bull; Phase 0 Foundation Complete
      </footer>
    </div>
  );
}

