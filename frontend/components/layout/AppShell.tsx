"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  CheckSquare,
  FileText,
  CreditCard,
  Link2,
  Settings,
  ChevronDown,
  Key,
  ShieldCheck,
  X,
  ExternalLink,
} from "lucide-react";
import { useAuditor } from "@/lib/auditor-session";
import { useDemoFilter } from "@/lib/demo-filter-context";

interface AppShellProps {
  children: React.ReactNode;
  currentBreadcrumb?: string;
  activeNav?: string;
}

export function AppShell({ children, currentBreadcrumb }: AppShellProps) {
  const pathname = usePathname();
  const {
    auditorKey,
    setAuditorKey,
    reviewerLabel,
    setReviewerLabel,
    hasKey,
    clearKey,
    isKeyModalOpen,
    openKeyModal,
    closeKeyModal,
  } = useAuditor();
  const { includeDemo, toggleDemo } = useDemoFilter();
  const [tempKey, setTempKey] = useState(auditorKey);
  const [tempLabel, setTempLabel] = useState(reviewerLabel);

  useEffect(() => {
    setTempKey(auditorKey);
    setTempLabel(reviewerLabel);
  }, [auditorKey, reviewerLabel, isKeyModalOpen]);

  const navItems = [
    { label: "Overview", href: "/", icon: LayoutGrid },
    { label: "Reconciliation", href: "/reconciliation", icon: CheckSquare },
    { label: "Documents", href: "/documents", icon: FileText },
    { label: "Payments", href: "/payments", icon: CreditCard },
  ];

  const connectionItems = [
    { label: "Zoho Books", href: "/integrations/zoho", icon: Link2 },
    { label: "Settings", href: "/settings", icon: Settings },
  ];

  const handleSaveKey = (e: React.FormEvent) => {
    e.preventDefault();
    setAuditorKey(tempKey);
    setReviewerLabel(tempLabel);
    closeKeyModal();
  };

  const getBreadcrumb = () => {
    if (currentBreadcrumb) return currentBreadcrumb;
    if (pathname === "/reconciliation") return "Demo workspace / Reconciliation";
    if (pathname === "/documents") return "Demo workspace / Documents";
    if (pathname === "/payments") return "Demo workspace / Payments";
    if (pathname === "/integrations/zoho") return "Demo workspace / Zoho Books";
    if (pathname === "/settings") return "Demo workspace / Settings";
    return "Demo workspace / Overview";
  };

  return (
    <div className="flex h-screen bg-[#080d1a] text-slate-100 font-sans overflow-hidden">
      {/* Sidebar matching dark navy screenshot */}
      <aside className="w-64 flex-shrink-0 bg-[#0c1322] border-r border-[#182338] flex flex-col justify-between">
        <div className="p-4 space-y-6">
          {/* Logo & Brand */}
          <div className="flex items-center space-x-3 px-1 py-1">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white text-base shadow-sm">
              P
            </div>
            <span className="font-semibold text-lg text-slate-100 tracking-tight">ProcureMind</span>
          </div>

          {/* Workspace dropdown selector */}
          <div>
            <button className="w-full flex items-center justify-between px-3 py-2 bg-[#121b2d] hover:bg-[#182338] border border-[#1e2d48] rounded-lg text-xs font-medium text-slate-200 transition-colors">
              <span className="truncate">Demo workspace</span>
              <ChevronDown className="w-4 h-4 text-slate-400" />
            </button>
          </div>

          {/* Workspace Navigation */}
          <div className="space-y-1">
            <p className="px-3 text-[10px] font-semibold tracking-wider text-slate-400 uppercase mb-2">
              Workspace
            </p>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(item.href + "/");

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                    isActive
                      ? "bg-[#182742] text-blue-400 font-semibold border-l-2 border-blue-500 shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-[#121c2e]"
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? "text-blue-400" : "text-slate-400"}`} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>

          {/* Connections Navigation */}
          <div className="space-y-1 pt-2">
            <p className="px-3 text-[10px] font-semibold tracking-wider text-slate-400 uppercase mb-2">
              Connections
            </p>
            {connectionItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                    isActive
                      ? "bg-[#182742] text-blue-400 font-semibold border-l-2 border-blue-500 shadow-sm"
                      : "text-slate-400 hover:text-slate-200 hover:bg-[#121c2e]"
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? "text-blue-400" : "text-slate-400"}`} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>

        {/* Sidebar Footer matching screenshot */}
        <div className="p-4 border-t border-[#182338] space-y-2">
          {/* Auditor session key status */}
          <button
            onClick={() => {
              setTempKey(auditorKey);
              setTempLabel(reviewerLabel);
              openKeyModal();
            }}
            className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-md bg-[#121b2d] hover:bg-[#182338] border border-[#1e2d48] text-[11px] text-slate-300 transition-colors"
          >
            <span className="flex items-center space-x-2">
              <Key className={`w-3.5 h-3.5 ${hasKey ? "text-emerald-400" : "text-amber-400"}`} />
              <span className="truncate">Auditor Key: {hasKey ? "Active" : "Unset"}</span>
            </span>
            <span className="text-[10px] text-blue-400 font-semibold">Config</span>
          </button>

          <div className="text-[11px] text-slate-400 px-1 pt-1 leading-snug">
            <p className="font-medium text-slate-300">Demo data only</p>
            <p className="text-[10px] text-slate-400">PayPal Sandbox · No real funds</p>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header matching screenshot */}
        <header className="h-14 bg-[#0c1322] border-b border-[#182338] px-6 flex items-center justify-between flex-shrink-0">
          <div className="text-xs text-slate-300 font-medium tracking-tight">
            {getBreadcrumb()}
          </div>

          <div className="flex items-center space-x-3">
            {/* Global Seeded Demo Data Toggle */}
            <div className="flex items-center space-x-2 bg-[#121c2e] border border-[#1e2d48] rounded-xl px-2.5 py-1 shadow-sm">
              <span className="text-[11px] font-medium text-slate-300">Seeded Data</span>
              <button
                type="button"
                role="switch"
                aria-checked={includeDemo}
                onClick={toggleDemo}
                className={`relative inline-flex h-4 w-8 flex-shrink-0 cursor-pointer rounded-full border border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  includeDemo ? "bg-blue-600" : "bg-slate-700"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    includeDemo ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
              <span
                className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider ${
                  includeDemo
                    ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                    : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                }`}
              >
                {includeDemo ? "All Data" : "Uploaded Only"}
              </span>
            </div>

            {/* PAYPAL SANDBOX badge */}
            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-800/90 text-slate-300 border border-slate-700/80 shadow-sm">
              PAYPAL SANDBOX
            </span>

            {/* Connect Zoho Books CTA matching screenshot */}
            <Link
              href="/integrations/zoho"
              className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-[#141e32] hover:bg-[#1c2a44] text-slate-200 text-xs font-medium border border-[#233554] transition-colors"
            >
              <Link2 className="w-3.5 h-3.5 text-slate-400" />
              <span>Connect Zoho Books</span>
            </Link>
          </div>
        </header>

        {/* Page Content viewport */}
        <main className="flex-1 overflow-y-auto bg-[#080d1a]">{children}</main>
      </div>

      {/* Auditor Key Session Modal */}
      {isKeyModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-[#0f172a] border border-slate-700 rounded-xl shadow-2xl max-w-md w-full p-6 text-slate-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-5 h-5 text-blue-400" />
                <h3 className="font-semibold text-base text-slate-100">Auditor Session Key</h3>
              </div>
              <button
                onClick={closeKeyModal}
                className="text-slate-400 hover:text-slate-200 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveKey} className="space-y-4 pt-4">
              <p className="text-xs text-slate-400 leading-relaxed">
                Protected financial actions (approving invoices, confirming match decisions, and saving
                manual field corrections) require an auditor authorization key verified by the server.
                This key is held strictly in browser memory for the active session and is never persisted to disk.
              </p>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Auditor API Key (X-Auditor-Key)
                </label>
                <input
                  type="password"
                  value={tempKey}
                  onChange={(e) => setTempKey(e.target.value)}
                  placeholder="Enter server AUDITOR_API_KEY"
                  className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Auditor / Reviewer Identity Label
                </label>
                <input
                  type="text"
                  value={tempLabel}
                  onChange={(e) => setTempLabel(e.target.value)}
                  placeholder="e.g. auditor@procuremind.io"
                  className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div className="flex items-center justify-between pt-2">
                {hasKey ? (
                  <button
                    type="button"
                    onClick={() => {
                      clearKey();
                      setTempKey("");
                      closeKeyModal();
                    }}
                    className="text-xs text-red-400 hover:text-red-300 font-medium"
                  >
                    Clear Session Key
                  </button>
                ) : (
                  <span />
                )}

                <div className="flex space-x-2">
                  <button
                    type="button"
                    onClick={closeKeyModal}
                    className="px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-all"
                  >
                    Set Key for Session
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default AppShell;
