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
  ArrowLeft,
  Info,
} from "lucide-react";
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
  if (mediaType.includes("pdf")) return <FileText className="w-5 h-5 text-red-500" />;
  if (mediaType.includes("spreadsheet") || mediaType.includes("csv"))
    return <FileSpreadsheet className="w-5 h-5 text-emerald-500" />;
  if (mediaType.includes("image")) return <FileImage className="w-5 h-5 text-blue-500" />;
  return <FileCheck className="w-5 h-5 text-slate-500" />;
}

function getStatusBadge(status: string) {
  switch (status) {
    case "uploaded":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
          Uploaded
        </span>
      );
    case "parsed":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 border border-indigo-200">
          Parsed
        </span>
      );
    case "extracted":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 border border-green-200">
          Extracted
        </span>
      );
    case "needs_review":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200">
          Needs Review
        </span>
      );
    case "approved":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 border border-emerald-200">
          Approved
        </span>
      );
    case "rejected":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800 border border-rose-200">
          Rejected
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 border border-slate-200">
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
  const {
    data: documents = [],
    isLoading,
    isRefetching,
    refetch,
    error,
  } = useQuery<DocumentRead[]>({
    queryKey: ["documents"],
    queryFn: getDocuments,
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
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-16">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Link
              href="/"
              className="inline-flex items-center text-sm font-medium text-slate-500 hover:text-slate-800 transition-colors"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              Back
            </Link>
            <span className="text-slate-300">|</span>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-lg bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">
                ProcureMind
              </span>
              <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-blue-50 text-blue-700 border border-blue-200">
                Phase 2 Registry
              </span>
            </div>
          </div>

          <button
            onClick={() => refetch()}
            disabled={isRefetching}
            className="inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 shadow-sm transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${isRefetching ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-8">
        {/* Page Header */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Document Ingestion & Storage Registry
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Securely upload commercial invoices, shipping bills, and bank statements with cryptographic SHA-256 verification and path containment.
          </p>
        </div>

        {/* Notification Banner */}
        {notification && (
          <div
            className={`p-4 rounded-xl border flex items-start justify-between shadow-sm transition-all ${
              notification.type === "success"
                ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                : notification.type === "info"
                ? "bg-blue-50 border-blue-200 text-blue-800"
                : "bg-rose-50 border-rose-200 text-rose-800"
            }`}
          >
            <div className="flex items-center space-x-2.5">
              {notification.type === "success" && <CheckCircle2 className="w-5 h-5 flex-shrink-0 text-emerald-600" />}
              {notification.type === "info" && <Info className="w-5 h-5 flex-shrink-0 text-blue-600" />}
              {notification.type === "error" && <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-600" />}
              <span className="text-sm font-medium">{notification.message}</span>
            </div>
            <button
              onClick={() => setNotification(null)}
              className="text-xs underline hover:opacity-75 font-semibold ml-4"
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
          className={`relative border-2 border-dashed rounded-2xl p-8 text-center transition-all bg-white shadow-sm ${
            dragActive
              ? "border-blue-500 bg-blue-50/50 scale-[1.005]"
              : "border-slate-300 hover:border-slate-400"
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
            <div className="w-14 h-14 rounded-full bg-blue-50 flex items-center justify-center text-blue-600 border border-blue-100 shadow-inner">
              <UploadCloud className="w-7 h-7" />
            </div>

            <div>
              <p className="text-base font-semibold text-slate-800">
                Drag and drop your trade document here, or{" "}
                <label
                  htmlFor="file-upload-input"
                  className="text-blue-600 hover:text-blue-700 cursor-pointer underline font-bold"
                >
                  browse files
                </label>
              </p>
              <p className="text-xs text-slate-500 mt-1">
                Supported formats: <strong>PDF, XLSX, CSV, PNG, JPG</strong> (Max 15 MB)
              </p>
            </div>

            {uploadMutation.isPending && (
              <div className="inline-flex items-center space-x-2 text-sm font-medium text-blue-600 bg-blue-50 px-3 py-1 rounded-full">
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>Hashing & storing securely...</span>
              </div>
            )}
          </div>
        </div>

        {/* Documents Registry Table */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <h2 className="text-base font-semibold text-slate-900">Registered Documents</h2>
              <span className="text-xs bg-slate-100 text-slate-600 font-bold px-2 py-0.5 rounded-full">
                {documents.length}
              </span>
            </div>
            <span className="text-xs text-slate-400">Timestamps in UTC</span>
          </div>

          {isLoading ? (
            <div className="p-12 text-center text-slate-400 flex flex-col items-center justify-center space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin text-blue-600" />
              <p className="text-sm">Loading document registry...</p>
            </div>
          ) : error ? (
            <div className="p-8 text-center text-rose-600 text-sm">
              Failed to load documents: {(error as Error).message}
            </div>
          ) : documents.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <FileText className="w-10 h-10 mx-auto text-slate-300 mb-2" />
              <p className="text-sm font-medium text-slate-600">No documents ingested yet</p>
              <p className="text-xs text-slate-400 mt-0.5">Upload a PDF, CSV, or spreadsheet above to begin.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-600 divide-y divide-slate-200">
                <thead className="bg-slate-50 text-xs font-semibold text-slate-700 uppercase tracking-wider">
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
                <tbody className="divide-y divide-slate-100 font-normal">
                  {documents.map((doc) => (
                    <tr key={doc.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center space-x-3">
                          {getFileIcon(doc.media_type)}
                          <div>
                            <p className="font-semibold text-slate-800 text-sm">{doc.original_filename}</p>
                            <p className="text-xs text-slate-400">{doc.media_type}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap capitalize text-xs font-medium text-slate-700">
                        {doc.document_type.replace("_", " ")}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-500 font-mono">
                        {formatBytes(doc.size_bytes)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {getStatusBadge(doc.processing_status)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap font-mono text-xs text-slate-500">
                        <div className="flex items-center space-x-1.5">
                          <span>{doc.sha256.slice(0, 10)}...{doc.sha256.slice(-6)}</span>
                          <button
                            onClick={() => copyHash(doc.sha256)}
                            title="Copy full SHA-256 hash"
                            className="p-1 hover:text-slate-800 rounded transition-colors"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-500">
                        {formatDate(doc.upload_time)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <button
                          onClick={() => handleDownload(doc.id, doc.original_filename)}
                          className="inline-flex items-center px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-sm transition-all"
                        >
                          <Download className="w-3.5 h-3.5 mr-1 text-slate-500" />
                          Download
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

