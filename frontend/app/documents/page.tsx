"use client";

import React, { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  UploadCloud,
  FileText,
  FileSpreadsheet,
  FileImage,
  FileCheck,
  AlertCircle,
  CheckCircle2,
  Download,
  Copy,
  RefreshCw,
  Info,
  SlidersHorizontal,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import { useDemoFilter } from "@/lib/demo-filter-context";
import { getDocuments, uploadDocument, getDownloadUrl, DocumentRead } from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function formatDate(isoString: string): string {
  try {
    const d = new Date(isoString);
    return d.toLocaleString("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return isoString;
  }
}

function getFileIcon(mediaType: string) {
  if (mediaType.includes("pdf")) return <FileText className="w-5 h-5 text-red-400" />;
  if (mediaType.includes("spreadsheet") || mediaType.includes("csv"))
    return <FileSpreadsheet className="w-5 h-5 text-emerald-400" />;
  if (mediaType.includes("image")) return <FileImage className="w-5 h-5 text-blue-400" />;
  return <FileCheck className="w-5 h-5 text-slate-400" />;
}

function getStatusBadge(status: string) {
  switch (status) {
    case "uploaded":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
          Uploaded
        </span>
      );
    case "parsed":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
          Parsed
        </span>
      );
    case "extracted":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-green-500/10 text-green-400 border border-green-500/20">
          Extracted
        </span>
      );
    case "needs_review":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
          Needs Review
        </span>
      );
    case "approved":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          Approved
        </span>
      );
    case "rejected":
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
          Rejected
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-300 border border-slate-700">
          {status}
        </span>
      );
  }
}

export default function DocumentsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [notification, setNotification] = useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);

  // TanStack Query for fetching document registry
  const { includeDemo } = useDemoFilter();

  const {
    data: documents = [],
    isLoading,
    isRefetching,
    refetch,
    error,
  } = useQuery<DocumentRead[]>({
    queryKey: ["documents", includeDemo],
    queryFn: () => getDocuments({ is_demo: includeDemo ? undefined : false }),
  });

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: uploadDocument,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      if (data.is_duplicate) {
        setNotification({
          type: "info",
          message: `Duplicate document recognized! Returning existing record (ID: ${data.document.id.slice(0, 8)}...). No duplicate file was created.`,
        });
      } else {
        setNotification({
          type: "success",
          message: `Successfully uploaded and registered: "${data.document.original_filename}"`,
        });
      }
    },
    onError: (err: Error) => {
      setNotification({
        type: "error",
        message: err.message || "Failed to upload document",
      });
    },
  });

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    setNotification(null);
    uploadMutation.mutate(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleDownload = async (docId: string, filename: string) => {
    try {
      const { download_url } = await getDownloadUrl(docId);
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const fullUrl = download_url.startsWith("http") ? download_url : `${API_BASE}${download_url}`;

      const link = document.createElement("a");
      link.href = fullUrl;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err: any) {
      alert(`Download failed: ${err.message}`);
    }
  };

  const copyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setNotification({
      type: "info",
      message: `SHA-256 hash copied to clipboard: ${hash.slice(0, 16)}...`,
    });
  };

  return (
    <AppShell activeNav="documents">
      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Documents Registry</h1>
            <p className="text-xs text-slate-400 mt-1">
              Securely upload commercial invoices, shipping bills, and receipts with cryptographic SHA-256 verification and path containment.
            </p>
          </div>

          <button
            onClick={() => refetch()}
            disabled={isRefetching}
            className="inline-flex items-center px-3 py-1.5 rounded-lg border border-[#1e293b] bg-[#0c1322] hover:bg-[#1e293b] text-xs font-medium text-slate-300 shadow-sm transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isRefetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {/* Notification Banner */}
        {notification && (
          <div
            className={`p-4 rounded-xl border flex items-start justify-between shadow-sm transition-all ${
              notification.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                : notification.type === "info"
                ? "bg-blue-500/10 border-blue-500/30 text-blue-300"
                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
            }`}
          >
            <div className="flex items-center space-x-2.5">
              {notification.type === "success" && <CheckCircle2 className="w-5 h-5 flex-shrink-0 text-emerald-400" />}
              {notification.type === "info" && <Info className="w-5 h-5 flex-shrink-0 text-blue-400" />}
              {notification.type === "error" && <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400" />}
              <span className="text-xs font-medium">{notification.message}</span>
            </div>
            <button
              onClick={() => setNotification(null)}
              className="text-xs underline hover:opacity-75 font-semibold ml-4 text-slate-300"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Upload Dropzone */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`relative border-2 border-dashed rounded-2xl p-8 text-center transition-all bg-[#0c1322] shadow-sm ${
            dragActive ? "border-blue-500 bg-blue-500/5 scale-[1.005]" : "border-[#1e293b] hover:border-slate-700"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.xlsx,.csv,.png,.jpg,.jpeg"
            onChange={(e) => handleFiles(e.target.files)}
            className="hidden"
            id="file-upload-input"
          />

          <div className="flex flex-col items-center justify-center space-y-3">
            <div className="w-14 h-14 rounded-full bg-blue-500/10 flex items-center justify-center text-blue-400 border border-blue-500/20 shadow-inner">
              <UploadCloud className="w-7 h-7" />
            </div>

            <div>
              <p className="text-sm font-semibold text-slate-200">
                Drag and drop your trade document here, or{" "}
                <label
                  htmlFor="file-upload-input"
                  className="text-blue-400 hover:text-blue-300 cursor-pointer underline font-bold"
                >
                  browse files
                </label>
              </p>
              <p className="text-xs text-slate-500 mt-1">
                Supported formats: <strong>PDF, XLSX, CSV, PNG, JPG</strong> (Max 15 MB)
              </p>
            </div>

            {uploadMutation.isPending && (
              <div className="inline-flex items-center space-x-2 text-xs font-medium text-blue-400 bg-blue-500/10 px-3 py-1.5 rounded-full border border-blue-500/20">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Hashing & storing securely...</span>
              </div>
            )}
          </div>
        </div>

        {/* Documents Registry Table */}
        <div className="bg-[#0c1322] rounded-2xl border border-[#1e293b] shadow-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-[#1e293b] flex items-center justify-between bg-[#080d1a]/50">
            <div className="flex items-center space-x-2">
              <h2 className="text-sm font-semibold text-white">Registered Documents</h2>
              <span className="text-xs bg-slate-800 text-slate-300 font-bold px-2 py-0.5 rounded-full">
                {documents.length}
              </span>
            </div>
            <span className="text-[11px] text-slate-500">Timestamps in UTC</span>
          </div>

          {isLoading ? (
            <div className="p-12 text-center text-slate-400 flex flex-col items-center justify-center space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
              <p className="text-xs">Loading document registry...</p>
            </div>
          ) : error ? (
            <div className="p-8 text-center text-rose-400 text-xs">
              Failed to load documents: {(error as Error).message}
            </div>
          ) : documents.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <FileText className="w-10 h-10 mx-auto text-slate-600 mb-2" />
              <p className="text-sm font-medium text-slate-300">No documents ingested yet</p>
              <p className="text-xs text-slate-500 mt-0.5">Upload a PDF, CSV, or spreadsheet above to begin.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300 divide-y divide-[#1e293b]">
                <thead className="bg-[#080d1a] text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  <tr>
                    <th scope="col" className="px-6 py-3.5">Filename</th>
                    <th scope="col" className="px-6 py-3.5">Category</th>
                    <th scope="col" className="px-6 py-3.5">Size</th>
                    <th scope="col" className="px-6 py-3.5">Status</th>
                    <th scope="col" className="px-6 py-3.5">SHA-256 Digest</th>
                    <th scope="col" className="px-6 py-3.5">Uploaded</th>
                    <th scope="col" className="px-6 py-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1e293b]/60 font-normal">
                  {documents.map((doc) => (
                    <tr key={doc.id} className="hover:bg-[#0f172a] transition-colors">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center space-x-3">
                          {getFileIcon(doc.media_type)}
                          <div>
                            <p className="font-semibold text-slate-100 text-xs">{doc.original_filename}</p>
                            <p className="text-[11px] text-slate-500">{doc.media_type}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap capitalize text-xs font-medium text-slate-300">
                        {doc.document_type.replace("_", " ")}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-400 font-mono">
                        {formatBytes(doc.size_bytes)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {getStatusBadge(doc.processing_status)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap font-mono text-xs text-slate-400">
                        <div className="flex items-center space-x-1.5">
                          <span>{doc.sha256.slice(0, 10)}...{doc.sha256.slice(-6)}</span>
                          <button
                            onClick={() => copyHash(doc.sha256)}
                            title="Copy full SHA-256 hash"
                            className="p-1 hover:text-white rounded transition-colors text-slate-500"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-400">
                        {formatDate(doc.upload_time)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <div className="flex items-center justify-end space-x-2">
                          <Link
                            href={`/documents/${doc.id}/review`}
                            className="inline-flex items-center px-2.5 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 text-xs font-medium transition-all"
                          >
                            <SlidersHorizontal className="w-3.5 h-3.5 mr-1" />
                            Review Fields
                          </Link>
                          <button
                            onClick={() => handleDownload(doc.id, doc.original_filename)}
                            className="inline-flex items-center px-2.5 py-1.5 rounded-lg border border-[#1e293b] bg-[#080d1a] hover:bg-[#1e293b] text-slate-300 text-xs font-medium shadow-sm transition-all"
                          >
                            <Download className="w-3.5 h-3.5 mr-1 text-slate-400" />
                            Download
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
