"use client";

import React, { useState } from "react";
import {
  Settings,
  Shield,
  Key,
  Database,
  Activity,
  CreditCard,
  CheckCircle2,
  AlertCircle,
  Lock,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import { useQuery } from "@tanstack/react-query";
import { getPayPalConfig, checkHealth } from "@/lib/api";
import { useAuditorSession } from "@/lib/auditor-session";

export default function SettingsPage() {
  const { auditorKey, reviewer, openKeyModal, clearSession } = useAuditorSession();

  // API Health
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: checkHealth,
  });

  // PayPal config
  const { data: paypalConfig, isLoading: paypalLoading } = useQuery({
    queryKey: ["paypalConfig"],
    queryFn: getPayPalConfig,
  });

  return (
    <AppShell activeNav="settings">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">System Settings</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Workspace configuration, compliance controls, and integration endpoints.
          </p>
        </div>

        {/* 1. Auditor Session & Security */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-5">
          <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-4">
            <Shield className="w-5 h-5 text-emerald-400" />
            <h2 className="text-base font-bold text-white">Auditor Authorization Session</h2>
          </div>

          <div className="space-y-4 text-xs">
            <p className="text-slate-400 leading-relaxed">
              Auditor actions (invoice approval, match decisions, and field corrections) require an authorized
              Auditor API Key. To prevent secret leakage, keys are kept strictly in-memory during this browser session.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
                <span className="text-slate-500 text-[11px] font-semibold uppercase">Session Identity</span>
                <p className="font-semibold text-white text-xs">{reviewer}</p>
              </div>

              <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
                <span className="text-slate-500 text-[11px] font-semibold uppercase">Auditor API Key</span>
                <p className="font-mono text-slate-300 text-xs">
                  {auditorKey ? "•••••••••••••••• (Verified Active)" : "Not Configured"}
                </p>
              </div>
            </div>

            <div className="flex items-center space-x-3 pt-1">
              <button
                onClick={openKeyModal}
                className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-colors"
              >
                <Key className="w-3.5 h-3.5" />
                <span>{auditorKey ? "Update Session Key" : "Configure Auditor Key"}</span>
              </button>

              {auditorKey && (
                <button
                  onClick={clearSession}
                  className="px-4 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-slate-400 hover:text-white text-xs font-medium transition-colors"
                >
                  Clear Session Key
                </button>
              )}
            </div>
          </div>
        </div>

        {/* 2. Backend & Database Status */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-5">
          <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-4">
            <Database className="w-5 h-5 text-blue-400" />
            <h2 className="text-base font-bold text-white">Authoritative Persistence & Engine</h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Backend API Health</span>
              <div className="flex items-center space-x-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    health?.status === "ok" ? "bg-emerald-400" : "bg-rose-400"
                  }`}
                />
                <span className="font-semibold text-white capitalize">{health?.status || "Unknown"}</span>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Primary Database</span>
              <p className="font-semibold text-white">PostgreSQL (Authoritative Source of Truth)</p>
            </div>

            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Audit Retention Policy</span>
              <p className="font-semibold text-white">Permanent Snapshot Retention (No Cascade Deletes)</p>
            </div>

            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Currency Arithmetic</span>
              <p className="font-semibold text-emerald-400">Strict Decimal Numeric Minor-Units</p>
            </div>
          </div>
        </div>

        {/* 3. Payment Gateway Configuration */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-5">
          <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-4">
            <CreditCard className="w-5 h-5 text-amber-400" />
            <h2 className="text-base font-bold text-white">Payment Gateway Environment</h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Active Gateway</span>
              <p className="font-semibold text-white">PayPal REST Orders v2</p>
            </div>

            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Operating Mode</span>
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-amber-500/10 text-amber-300 border border-amber-500/30">
                Sandbox Simulation Only
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] space-y-1 sm:col-span-2">
              <span className="text-slate-500 text-[11px] font-semibold uppercase">Client ID</span>
              <p className="font-mono text-slate-300 text-xs break-all">
                {paypalConfig?.client_id || "Loaded from server environment"}
              </p>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

