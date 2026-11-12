"use client";

import React from "react";
import Link from "next/link";
import { Link2Off, ExternalLink, ShieldAlert, ArrowLeft, Key, BookOpen } from "lucide-react";
import AppShell from "@/components/layout/AppShell";

export default function ZohoIntegrationPage() {
  return (
    <AppShell activeNav="zoho">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center space-x-3">
          <Link
            href="/reconciliation"
            className="p-2 rounded-lg bg-[#0c1322] border border-[#1e293b] text-slate-400 hover:text-white transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
              Zoho Books Integration
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Enterprise accounting synchronization & general ledger posting.
            </p>
          </div>
        </div>

        {/* Integration Status Card */}
        <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 sm:p-8 shadow-xl space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#1e293b] pb-6">
            <div className="flex items-center space-x-4">
              <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
                <Link2Off className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center space-x-2">
                  <h2 className="text-base font-bold text-white">Zoho Books API Connector</h2>
                  <span className="text-[11px] px-2.5 py-0.5 rounded-full font-semibold uppercase tracking-wider bg-amber-500/10 text-amber-300 border border-amber-500/30">
                    Not Connected
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  OAuth 2.0 credentials have not been configured for this workspace.
                </p>
              </div>
            </div>
          </div>

          {/* Honest Notice */}
          <div className="bg-[#080d1a] border border-[#1e293b] rounded-xl p-5 space-y-3">
            <div className="flex items-center space-x-2 text-slate-200 text-xs font-semibold">
              <ShieldAlert className="w-4 h-4 text-amber-400 flex-shrink-0" />
              <span>Production Audit Rule: No Simulated Sync</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              ProcureMind enforces strict accounting boundaries. Invoices and payments are matched against
              our authoritative PostgreSQL ledger. To connect Zoho Books, your organization administrator
              must register an OAuth client in the Zoho Developer Console and supply the credentials in your
              backend environment configuration (`.env`).
            </p>
          </div>

          {/* Setup Guide */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-white flex items-center space-x-2">
              <BookOpen className="w-4 h-4 text-blue-400" />
              <span>Configuration Steps</span>
            </h3>

            <div className="space-y-3 text-xs text-slate-300">
              <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] flex items-start space-x-3">
                <span className="w-5 h-5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center justify-center font-bold text-[11px] flex-shrink-0">
                  1
                </span>
                <div>
                  <p className="font-semibold text-slate-200">Register Zoho API Client</p>
                  <p className="text-slate-400 mt-0.5">
                    Navigate to the Zoho API Console (<a href="https://api-console.zoho.com" target="_blank" rel="noreferrer" className="text-blue-400 underline inline-flex items-center">api-console.zoho.com <ExternalLink className="w-3 h-3 ml-0.5" /></a>) and create a &ldquo;Server-based Application&rdquo;.
                  </p>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] flex items-start space-x-3">
                <span className="w-5 h-5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center justify-center font-bold text-[11px] flex-shrink-0">
                  2
                </span>
                <div>
                  <p className="font-semibold text-slate-200">Configure OAuth Scopes</p>
                  <p className="text-slate-400 mt-0.5">
                    Request <code className="text-blue-300 bg-slate-900 px-1 py-0.5 rounded">ZohoBooks.invoices.READ</code> and <code className="text-blue-300 bg-slate-900 px-1 py-0.5 rounded">ZohoBooks.customerpayments.READ</code> scopes.
                  </p>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-[#080d1a] border border-[#1e293b] flex items-start space-x-3">
                <span className="w-5 h-5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center justify-center font-bold text-[11px] flex-shrink-0">
                  3
                </span>
                <div>
                  <p className="font-semibold text-slate-200">Provide Backend Environment Keys</p>
                  <p className="text-slate-400 mt-0.5">
                    Set <code className="text-blue-300 bg-slate-900 px-1 py-0.5 rounded">ZOHO_CLIENT_ID</code> and <code className="text-blue-300 bg-slate-900 px-1 py-0.5 rounded">ZOHO_CLIENT_SECRET</code> in the backend environment.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

