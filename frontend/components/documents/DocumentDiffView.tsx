"use client";

import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  GitCompare,
  CheckCircle2,
  AlertTriangle,
  FileText,
  MinusCircle,
  ArrowRight,
  Filter,
  DollarSign,
  TrendingUp,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import {
  getDocumentFields,
  getDocuments,
  DocumentRead,
  ExtractedFieldRead,
} from "@/lib/api";
import { useDemoFilter } from "@/lib/demo-filter-context";

interface DocumentDiffViewProps {
  baseDocumentId: string;
  baseDocumentName?: string;
  baseDocumentType?: string;
}

interface FieldComparisonItem {
  key: string;
  category: "header" | "line_item" | "logistics" | "other";
  label: string;
  baseRaw: string | null;
  baseVal: any;
  targetRaw: string | null;
  targetVal: any;
  status: "match" | "variance" | "missing_in_target" | "missing_in_base";
  deltaDisplay?: string;
  isNumeric?: boolean;
}

export default function DocumentDiffView({
  baseDocumentId,
  baseDocumentName = "Current Document",
  baseDocumentType = "Document",
}: DocumentDiffViewProps) {
  const { includeDemo } = useDemoFilter();
  const [targetDocId, setTargetDocId] = useState<string>("");
  const [filterMode, setFilterMode] = useState<"all" | "variances" | "line_items" | "matches">("all");
  const [auditAcknowledged, setAuditAcknowledged] = useState<boolean>(false);

  // 1. Fetch all documents in workspace for selection
  const { data: allDocs = [], isLoading: isDocsLoading } = useQuery<DocumentRead[]>({
    queryKey: ["documents", includeDemo],
    queryFn: () => getDocuments({ is_demo: includeDemo ? undefined : false }),
  });

  const availableTargetDocs = useMemo(
    () => allDocs.filter((d) => d.id !== baseDocumentId),
    [allDocs, baseDocumentId]
  );

  // Auto-select related document if none chosen
  React.useEffect(() => {
    if (availableTargetDocs.length > 0 && !targetDocId) {
      // Intelligently find related counterpart (e.g. proforma if base is commercial, or packing list)
      const isBaseCommercial = baseDocumentName.toLowerCase().includes("commercial");
      const isBaseProforma = baseDocumentName.toLowerCase().includes("proforma");

      let autoPick = availableTargetDocs[0];
      if (isBaseCommercial) {
        const proforma = availableTargetDocs.find((d) =>
          d.original_filename.toLowerCase().includes("proforma")
        );
        if (proforma) autoPick = proforma;
      } else if (isBaseProforma) {
        const commercial = availableTargetDocs.find((d) =>
          d.original_filename.toLowerCase().includes("commercial")
        );
        if (commercial) autoPick = commercial;
      }
      setTargetDocId(autoPick.id);
    }
  }, [availableTargetDocs, targetDocId, baseDocumentName]);

  const activeTargetDoc = useMemo(
    () => allDocs.find((d) => d.id === targetDocId),
    [allDocs, targetDocId]
  );

  // 2. Fetch fields of base document
  const { data: baseFields = [], isLoading: isBaseLoading } = useQuery<ExtractedFieldRead[]>({
    queryKey: ["document-fields", baseDocumentId],
    queryFn: () => getDocumentFields(baseDocumentId),
  });

  // 3. Fetch fields of target document
  const { data: targetFields = [], isLoading: isTargetLoading } = useQuery<ExtractedFieldRead[]>({
    queryKey: ["document-fields", targetDocId],
    queryFn: () => getDocumentFields(targetDocId),
    enabled: !!targetDocId,
  });

  // 4. Compute Side-by-Side Diff
  const { comparisons, stats, financialDelta } = useMemo(() => {
    const baseMap = new Map<string, ExtractedFieldRead>();
    baseFields.forEach((f) => baseMap.set(f.field_name, f));

    const targetMap = new Map<string, ExtractedFieldRead>();
    targetFields.forEach((f) => targetMap.set(f.field_name, f));

    // Union of all unique field keys
    const allKeys = Array.from(new Set([...baseMap.keys(), ...targetMap.keys()]));

    // Sorting order priorities
    const orderPriority = (k: string) => {
      if (k === "invoice_number") return 1;
      if (k === "issue_date") return 2;
      if (k === "due_date") return 3;
      if (k === "seller_name" || k === "exporter_name") return 4;
      if (k === "buyer_name" || k === "consignee_name") return 5;
      if (k === "currency") return 6;
      if (k === "subtotal") return 7;
      if (k === "tax") return 8;
      if (k === "charges") return 9;
      if (k === "discounts") return 10;
      if (k === "total_amount") return 11;
      if (k.startsWith("line_item_")) return 20;
      if (k.includes("weight") || k.includes("container") || k.includes("vessel")) return 30;
      return 50;
    };

    allKeys.sort((a, b) => {
      const pA = orderPriority(a);
      const pB = orderPriority(b);
      if (pA !== pB) return pA - pB;
      return a.localeCompare(b);
    });

    const items: FieldComparisonItem[] = [];
    let matchesCount = 0;
    let variancesCount = 0;
    let missingCount = 0;

    for (const key of allKeys) {
      if (key.startsWith("rel_")) continue; // Skip raw graph relationships

      const bF = baseMap.get(key);
      const tF = targetMap.get(key);

      const baseRaw = bF?.raw_value ?? null;
      const baseVal = bF?.normalized_value ?? null;
      const targetRaw = tF?.raw_value ?? null;
      const targetVal = tF?.normalized_value ?? null;

      // Label derivation
      let label = key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      let category: FieldComparisonItem["category"] = "other";

      if (key.startsWith("line_item_")) {
        category = "line_item";
        const parts = key.split("_");
        const lineNum = parts[2];
        const attr = parts.slice(3).join(" ");
        label = `Line ${lineNum}: ${attr.charAt(0).toUpperCase() + attr.slice(1)}`;
      } else if (
        [
          "invoice_number",
          "issue_date",
          "due_date",
          "seller_name",
          "buyer_name",
          "currency",
          "subtotal",
          "total_amount",
          "tax",
          "charges",
          "discounts",
        ].includes(key)
      ) {
        category = "header";
      } else if (
        ["container_number", "seal_number", "vessel_name", "port_of_loading", "port_of_discharge", "total_gross_weight"].includes(
          key
        )
      ) {
        category = "logistics";
      }

      // Comparison logic
      let status: FieldComparisonItem["status"] = "variance";
      let deltaDisplay: string | undefined = undefined;
      let isNumeric = false;

      if (bF && !tF) {
        status = "missing_in_target";
        missingCount++;
      } else if (!bF && tF) {
        status = "missing_in_base";
        missingCount++;
      } else {
        // Both exist: check equivalence
        const bStr = String(baseVal ?? "").trim().toLowerCase();
        const tStr = String(targetVal ?? "").trim().toLowerCase();

        // Check if numeric
        const bNum = Number(baseVal);
        const tNum = Number(targetVal);

        if (!isNaN(bNum) && !isNaN(tNum) && baseVal !== null && targetVal !== null && baseVal !== "" && targetVal !== "") {
          isNumeric = true;
          const diff = bNum - tNum;
          if (Math.abs(diff) < 0.0001) {
            status = "match";
            matchesCount++;
          } else {
            status = "variance";
            variancesCount++;
            const sign = diff > 0 ? "+" : "";
            const pct = tNum !== 0 ? ((diff / tNum) * 100).toFixed(2) : "0";
            deltaDisplay = `${sign}${diff.toFixed(2)} (${sign}${pct}%)`;
          }
        } else if (bStr === tStr) {
          status = "match";
          matchesCount++;
        } else {
          status = "variance";
          variancesCount++;
        }
      }

      items.push({
        key,
        category,
        label,
        baseRaw,
        baseVal,
        targetRaw,
        targetVal,
        status,
        deltaDisplay,
        isNumeric,
      });
    }

    // Financial Total Delta
    const baseTotal = Number(baseMap.get("total_amount")?.normalized_value ?? 0);
    const targetTotal = Number(targetMap.get("total_amount")?.normalized_value ?? 0);
    const diffTotal = baseTotal - targetTotal;
    const diffSign = diffTotal > 0 ? "+" : "";
    const pctTotal = targetTotal !== 0 ? ((diffTotal / targetTotal) * 100).toFixed(2) : "0";

    const financialDelta = {
      baseTotal: isNaN(baseTotal) ? 0 : baseTotal,
      targetTotal: isNaN(targetTotal) ? 0 : targetTotal,
      diffTotal: isNaN(diffTotal) ? 0 : diffTotal,
      display: `${diffSign}${diffTotal.toFixed(2)} (${diffSign}${pctTotal}%)`,
    };

    return {
      comparisons: items,
      stats: {
        total: items.length,
        matches: matchesCount,
        variances: variancesCount,
        missing: missingCount,
      },
      financialDelta,
    };
  }, [baseFields, targetFields]);

  // Filtered comparisons list
  const filteredComparisons = useMemo(() => {
    switch (filterMode) {
      case "variances":
        return comparisons.filter((c) => c.status === "variance" || c.status.startsWith("missing"));
      case "matches":
        return comparisons.filter((c) => c.status === "match");
      case "line_items":
        return comparisons.filter((c) => c.category === "line_item");
      default:
        return comparisons;
    }
  }, [comparisons, filterMode]);

  const isLoading = isDocsLoading || isBaseLoading || isTargetLoading;

  return (
    <div className="space-y-6">
      {/* Comparison Selector Bar */}
      <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-5 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Left: Base Document Info */}
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-[10px] uppercase font-bold text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded-full border border-blue-500/20">
                Primary (This Document)
              </span>
              <span className="text-[11px] text-slate-400 capitalize">{baseDocumentType.replace("_", " ")}</span>
            </div>
            <h3 className="text-sm font-bold text-white mt-0.5 font-mono">{baseDocumentName}</h3>
          </div>
        </div>

        {/* Center: Compare Arrow */}
        <div className="hidden md:flex items-center justify-center px-4">
          <div className="w-8 h-8 rounded-full bg-[#121c2e] border border-[#1e2d48] flex items-center justify-center text-slate-400 shadow-inner">
            <GitCompare className="w-4 h-4 text-slate-300" />
          </div>
        </div>

        {/* Right: Target Document Selector */}
        <div className="flex-1 md:max-w-md">
          <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
            Compare Against Document:
          </label>
          <select
            value={targetDocId}
            onChange={(e) => setTargetDocId(e.target.value)}
            disabled={availableTargetDocs.length === 0}
            className="w-full px-3 py-2 rounded-xl bg-[#080d1a] border border-[#1e293b] text-white text-xs font-medium focus:outline-none focus:border-blue-500 disabled:opacity-50"
          >
            {availableTargetDocs.length === 0 ? (
              <option value="">No other documents available to compare</option>
            ) : (
              availableTargetDocs.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.original_filename} ({doc.document_type.replace("_", " ")})
                </option>
              ))
            )}
          </select>
        </div>
      </div>

      {/* KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Compared */}
        <div className="p-4 rounded-xl bg-[#0c1322] border border-[#1e293b] shadow-md flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Compared Fields</p>
            <p className="text-2xl font-bold text-white mt-1 font-mono">{stats.total}</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-400 border border-blue-500/20">
            <GitCompare className="w-4 h-4" />
          </div>
        </div>

        {/* Exact Matches */}
        <div className="p-4 rounded-xl bg-[#0c1322] border border-emerald-500/30 shadow-md flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">Exact Matches</p>
            <p className="text-2xl font-bold text-emerald-300 mt-1 font-mono">
              {stats.matches}{" "}
              <span className="text-xs font-normal text-emerald-400/80">
                ({stats.total > 0 ? ((stats.matches / stats.total) * 100).toFixed(0) : 0}%)
              </span>
            </p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-4 h-4" />
          </div>
        </div>

        {/* Variances */}
        <div className="p-4 rounded-xl bg-[#0c1322] border border-amber-500/30 shadow-md flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider">Variances & Deltas</p>
            <p className="text-2xl font-bold text-amber-300 mt-1 font-mono">{stats.variances}</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-4 h-4" />
          </div>
        </div>

        {/* Net Financial Delta */}
        <div
          className={`p-4 rounded-xl bg-[#0c1322] border shadow-md flex items-center justify-between ${
            Math.abs(financialDelta.diffTotal) > 0.001
              ? "border-rose-500/30"
              : "border-emerald-500/30"
          }`}
        >
          <div>
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Net Amount Variance</p>
            <p
              className={`text-2xl font-bold mt-1 font-mono ${
                Math.abs(financialDelta.diffTotal) > 0.001 ? "text-rose-400" : "text-emerald-400"
              }`}
            >
              {financialDelta.diffTotal === 0 ? "USD 0.00" : `USD ${financialDelta.display}`}
            </p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-rose-500/10 flex items-center justify-center text-rose-400 border border-rose-500/20">
            <DollarSign className="w-4 h-4" />
          </div>
        </div>
      </div>

      {/* Main Diff Table Container */}
      <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl shadow-xl overflow-hidden">
        {/* Table Toolbar */}
        <div className="px-5 py-3.5 border-b border-[#1e293b] flex flex-wrap items-center justify-between gap-3 bg-[#080d1a]/50">
          <div className="flex items-center space-x-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <span className="text-xs font-semibold text-slate-300">Filter View:</span>
            <div className="flex items-center space-x-1.5 ml-2">
              <button
                onClick={() => setFilterMode("all")}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  filterMode === "all"
                    ? "bg-blue-600 text-white font-bold"
                    : "bg-[#121c2e] text-slate-400 hover:text-white"
                }`}
              >
                All ({comparisons.length})
              </button>
              <button
                onClick={() => setFilterMode("variances")}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  filterMode === "variances"
                    ? "bg-amber-600 text-white font-bold"
                    : "bg-[#121c2e] text-slate-400 hover:text-white"
                }`}
              >
                Variances Only ({stats.variances + stats.missing})
              </button>
              <button
                onClick={() => setFilterMode("line_items")}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  filterMode === "line_items"
                    ? "bg-indigo-600 text-white font-bold"
                    : "bg-[#121c2e] text-slate-400 hover:text-white"
                }`}
              >
                Line Items Only
              </button>
              <button
                onClick={() => setFilterMode("matches")}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  filterMode === "matches"
                    ? "bg-emerald-600 text-white font-bold"
                    : "bg-[#121c2e] text-slate-400 hover:text-white"
                }`}
              >
                Matches ({stats.matches})
              </button>
            </div>
          </div>

          {/* Quick Auditor Acknowledge */}
          <div>
            {auditAcknowledged ? (
              <span className="inline-flex items-center text-xs font-semibold px-3 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
                Variances Acknowledged by Auditor
              </span>
            ) : (
              <button
                onClick={() => setAuditAcknowledged(true)}
                className="px-3 py-1 rounded-lg bg-[#141e32] hover:bg-[#1c2a44] border border-[#233554] text-slate-200 text-xs font-medium transition-colors"
              >
                Acknowledge Variance
              </button>
            )}
          </div>
        </div>

        {/* Diff Data Table */}
        {isLoading ? (
          <div className="p-16 text-center text-slate-400 flex flex-col items-center justify-center space-y-3">
            <RefreshCw className="w-7 h-7 animate-spin text-blue-500" />
            <p className="text-xs">Aligning and comparing document field structures...</p>
          </div>
        ) : filteredComparisons.length === 0 ? (
          <div className="p-16 text-center text-slate-400 space-y-2">
            <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto opacity-70" />
            <p className="text-sm font-semibold text-slate-200">No discrepancies under selected filter</p>
            <p className="text-xs text-slate-500">All matching fields align with the compared document.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300 divide-y divide-[#1e293b]">
              <thead className="bg-[#080d1a] text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-5 py-3.5">
                    Field / Line Item
                  </th>
                  <th scope="col" className="px-5 py-3.5">
                    {baseDocumentName} (This Document)
                  </th>
                  <th scope="col" className="px-5 py-3.5">
                    {activeTargetDoc?.original_filename || "Compared Document"}
                  </th>
                  <th scope="col" className="px-5 py-3.5">
                    Variance / Delta
                  </th>
                  <th scope="col" className="px-5 py-3.5 text-right">
                    Audit Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1e293b]/60">
                {filteredComparisons.map((item) => {
                  const isMatch = item.status === "match";
                  const isVariance = item.status === "variance";
                  const isMissing = item.status.startsWith("missing");

                  return (
                    <tr
                      key={item.key}
                      className={`transition-colors ${
                        isVariance
                          ? "bg-amber-500/[0.04] hover:bg-amber-500/[0.08]"
                          : isMissing
                          ? "bg-slate-800/10 hover:bg-slate-800/20"
                          : "hover:bg-[#0f172a]"
                      }`}
                    >
                      {/* Field Name & Category */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <div className="flex items-center space-x-2">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              isMatch ? "bg-emerald-400" : isVariance ? "bg-amber-400 animate-pulse" : "bg-slate-500"
                            }`}
                          />
                          <div>
                            <p className="font-semibold text-slate-100 text-xs font-mono">{item.label}</p>
                            <p className="text-[10px] text-slate-500 font-mono">{item.key}</p>
                          </div>
                        </div>
                      </td>

                      {/* Base Value */}
                      <td className="px-5 py-3.5 font-mono text-xs">
                        {item.baseVal !== null && item.baseVal !== undefined ? (
                          <span className="font-semibold text-slate-200 bg-[#080d1a] px-2 py-1 rounded border border-[#1e293b]">
                            {String(item.baseVal)}
                          </span>
                        ) : (
                          <span className="text-slate-600 italic">None / Absent</span>
                        )}
                      </td>

                      {/* Target Value */}
                      <td className="px-5 py-3.5 font-mono text-xs">
                        {item.targetVal !== null && item.targetVal !== undefined ? (
                          <span className="font-semibold text-slate-200 bg-[#080d1a] px-2 py-1 rounded border border-[#1e293b]">
                            {String(item.targetVal)}
                          </span>
                        ) : (
                          <span className="text-slate-600 italic">None / Absent</span>
                        )}
                      </td>

                      {/* Variance / Delta */}
                      <td className="px-5 py-3.5 whitespace-nowrap font-mono text-xs">
                        {isMatch ? (
                          <span className="text-emerald-400 text-[11px] font-semibold">0.00 (Match)</span>
                        ) : item.deltaDisplay ? (
                          <span className="inline-flex items-center font-bold px-2 py-0.5 rounded text-amber-300 bg-amber-500/10 border border-amber-500/20">
                            <TrendingUp className="w-3 h-3 mr-1" />
                            {item.deltaDisplay}
                          </span>
                        ) : isVariance ? (
                          <span className="text-amber-400/90 text-[11px]">Value Mismatch</span>
                        ) : (
                          <span className="text-slate-500 text-[11px] italic">Not Present</span>
                        )}
                      </td>

                      {/* Audit Status Pill */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-right">
                        {isMatch ? (
                          <span className="inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            <CheckCircle2 className="w-3 h-3 mr-1" />
                            Identical
                          </span>
                        ) : isVariance ? (
                          <span className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30">
                            <AlertTriangle className="w-3 h-3 mr-1" />
                            Price / Qty Variance
                          </span>
                        ) : (
                          <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                            <MinusCircle className="w-3 h-3 mr-1" />
                            {item.status === "missing_in_target" ? "Only in This Doc" : "Only in Target"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

