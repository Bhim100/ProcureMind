"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CreditCard,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Lock,
  ArrowRight,
  RefreshCw,
  Info,
  Clock,
  XCircle,
} from "lucide-react";
import {
  getPayPalConfig,
  getPayments,
  approveInvoice,
  initiatePayment,
  captureOrder,
  investigateTransaction,
  InvestigationResponse,
  PaymentRead,
  InvoiceDetailResponse,
} from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

declare global {
  interface Window {
    paypal?: any;
  }
}

export default function PaymentsPage() {
  const queryClient = useQueryClient();
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string>("");
  const [auditorKey, setAuditorKey] = useState<string>("");
  const [reviewerLabel, setReviewerLabel] = useState<string>("auditor@procuremind.io");
  const [approvalNotes, setApprovalNotes] = useState<string>("Verified commercial invoice details");
  const [isApproving, setIsApproving] = useState<boolean>(false);
  const [approvalSuccess, setApprovalSuccess] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [checkoutNotice, setCheckoutNotice] = useState<{ type: "success" | "cancel" | "error"; message: string } | null>(null);

  const paypalContainerRef = useRef<HTMLDivElement>(null);
  const [isScriptLoaded, setIsScriptLoaded] = useState<boolean>(false);
  const [investigationReference, setInvestigationReference] = useState("EXP-DEMO-004");
  const [investigationQuestion, setInvestigationQuestion] = useState(
    "Explain the payment discrepancy and what evidence is still missing."
  );
  const [investigationResult, setInvestigationResult] = useState<InvestigationResponse | null>(null);
  const [investigationError, setInvestigationError] = useState<string | null>(null);
  const [isInvestigating, setIsInvestigating] = useState(false);

  // Fetch PayPal public config
  const { data: paypalConfig } = useQuery({
    queryKey: ["paypalConfig"],
    queryFn: getPayPalConfig,
  });

  // Fetch all transactions to discover invoices
  const { data: transactions, isLoading: txLoading, refetch: refetchTx } = useQuery({
    queryKey: ["transactions"],
    queryFn: async () => {
      // In local dev, query transaction EXP-DEMO-001 or EXP-2026-001
      const res = await fetch(`${API_BASE}/api/v1/transactions/EXP-DEMO-001`).catch(() => null);
      if (!res || !res.ok) {
        // Fallback to demo query or empty list
        return [];
      }
      return [await res.json()];
    },
  });

  // Fetch list of payments
  const { data: payments, isLoading: paymentsLoading, refetch: refetchPayments } = useQuery({
    queryKey: ["payments"],
    queryFn: () => getPayments(),
    refetchInterval: 5000,
  });

  // Collect invoices across transactions or mock demo list
  const invoices: InvoiceDetailResponse[] = [];
  if (transactions && transactions.length > 0) {
    for (const tx of transactions) {
      if (tx.invoices) {
        for (const inv of tx.invoices) {
          invoices.push({
            id: inv.id,
            invoice_number: inv.invoice_number,
            export_transaction_id: tx.id,
            seller_name: inv.seller_name,
            buyer_name: inv.buyer_name,
            issue_date: inv.issue_date,
            currency: inv.currency,
            total_amount: inv.total_amount,
            is_approved: true, // will check detail
            remaining_balance: inv.total_amount,
          });
        }
      }
    }
  }

  // Active selected invoice
  const activeInvoice = invoices.find((i) => i.id === selectedInvoiceId) || invoices[0];

  // Fetch selected invoice detail for live approval status
  const { data: invoiceDetail, refetch: refetchInvoiceDetail } = useQuery({
    queryKey: ["invoiceDetail", activeInvoice?.id],
    queryFn: async () => {
      if (!activeInvoice?.id) return null;
      const res = await fetch(`${API_BASE}/api/v1/invoices/${activeInvoice.id}`);
      if (!res.ok) return null;
      return (await res.json()) as InvoiceDetailResponse;
    },
    enabled: !!activeInvoice?.id,
  });

  const isApproved = invoiceDetail?.is_approved ?? false;
  const activeInvoiceId = activeInvoice?.id;

  const runInvestigation = async () => {
    setIsInvestigating(true);
    setInvestigationError(null);
    setInvestigationResult(null);
    try {
      setInvestigationResult(
        await investigateTransaction(investigationReference.trim(), investigationQuestion.trim())
      );
    } catch (err: unknown) {
      setInvestigationError(err instanceof Error ? err.message : "Investigation request failed.");
    } finally {
      setIsInvestigating(false);
    }
  };

  // Handle Auditor Approval Action
  const handleApprove = async () => {
    if (!activeInvoice?.id) return;
    setIsApproving(true);
    setApprovalError(null);
    setApprovalSuccess(null);
    try {
      await approveInvoice(activeInvoice.id, reviewerLabel, approvalNotes, auditorKey);
      setApprovalSuccess("Invoice successfully approved! PayPal checkout is now unlocked.");
      refetchInvoiceDetail();
      queryClient.invalidateQueries({ queryKey: ["invoiceDetail"] });
    } catch (err: any) {
      setApprovalError(err.message || "Failed to approve invoice.");
    } finally {
      setIsApproving(false);
    }
  };

  // Dynamically load PayPal JavaScript SDK when client_id and invoice currency are available
  useEffect(() => {
    if (!paypalConfig?.client_id || !activeInvoice?.currency) return;

    setIsScriptLoaded(false);
    const existingScript = document.getElementById("paypal-sdk-script");
    if (existingScript) {
      existingScript.remove();
    }

    const script = document.createElement("script");
    script.id = "paypal-sdk-script";
    script.src = `https://www.sandbox.paypal.com/sdk/js?client-id=${paypalConfig.client_id}&currency=${activeInvoice.currency}&intent=capture`;
    script.async = true;
    script.onload = () => {
      setIsScriptLoaded(true);
    };
    document.body.appendChild(script);

    return () => {
      const s = document.getElementById("paypal-sdk-script");
      if (s) s.remove();
    };
  }, [paypalConfig?.client_id, activeInvoice?.currency]);

  // Render PayPal Buttons inside container when approved and script loaded
  useEffect(() => {
    if (!isScriptLoaded || !window.paypal || !paypalContainerRef.current || !isApproved || !activeInvoiceId) {
      return;
    }

    paypalContainerRef.current.innerHTML = "";

    try {
      window.paypal
        .Buttons({
          style: {
            layout: "vertical",
            color: "blue",
            shape: "rect",
            label: "pay",
          },
          createOrder: async () => {
            setCheckoutNotice(null);
            const res = await initiatePayment(activeInvoiceId);
            return res.order_id;
          },
          onApprove: async (data: any) => {
            try {
              const payment = await captureOrder(data.orderID);
              setCheckoutNotice({
                type: "success",
                message: `Payment captured successfully! Capture ID: ${payment.provider_capture_id || "N/A"} (${payment.currency} ${payment.gross_amount}). Reconciliation engine triggered.`,
              });
              refetchPayments();
              refetchInvoiceDetail();
            } catch (err: any) {
              setCheckoutNotice({
                type: "error",
                message: err.message || "Failed to finalize PayPal capture.",
              });
            }
          },
          onCancel: () => {
            setCheckoutNotice({
              type: "cancel",
              message: "Checkout canceled by buyer in PayPal Sandbox popup.",
            });
          },
          onError: (err: any) => {
            setCheckoutNotice({
              type: "error",
              message: `PayPal error occurred: ${err.message || String(err)}`,
            });
          },
        })
        .render(paypalContainerRef.current);
    } catch (e) {
      console.error("Failed to render PayPal Buttons:", e);
    }
  }, [isScriptLoaded, isApproved, activeInvoiceId, refetchInvoiceDetail, refetchPayments]);

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
                <span className="bg-amber-100 text-amber-900 border border-amber-300 text-xs font-semibold px-2 py-0.5 rounded-full">
                  Phase 5: PayPal Sandbox
                </span>
              </div>
              <p className="text-xs text-slate-500">Overseas Buyer Export Checkout & Settlement</p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <Link
              href="/"
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-100 transition-all"
            >
              System Health
            </Link>
            <Link
              href="/documents"
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-100 transition-all"
            >
              Documents
            </Link>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Environment Alert Banner */}
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start space-x-3 shadow-sm">
          <Info className="w-5 h-5 text-amber-700 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-900 leading-relaxed">
            <span className="font-bold uppercase tracking-wider block mb-0.5">
              PayPal Sandbox Simulation Environment
            </span>
            All transactions and payments on this page operate strictly in the PayPal Sandbox environment.
            No live payments, cards, or funds are debited. In compliance with strict financial controls,
            payments can only be initiated once an authorized human auditor decision is recorded.
          </div>
        </div>

        {/* Two-Column Grid: Checkout Box & Auditor Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left Column: Commercial Invoice & Checkout */}
          <div className="lg:col-span-7 space-y-6">
            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-6">
              <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                <div className="flex items-center space-x-2">
                  <CreditCard className="w-5 h-5 text-blue-600" />
                  <h2 className="text-base font-semibold">Overseas Buyer Checkout</h2>
                </div>
                <span className="bg-blue-50 text-blue-700 text-xs font-medium px-2.5 py-1 rounded-full border border-blue-200">
                  Orders v2 API (Capture)
                </span>
              </div>

              {/* Invoice Summary Card */}
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-5 space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-500 font-medium">Commercial Invoice</span>
                  <span className="text-sm font-bold text-slate-900">
                    {activeInvoice?.invoice_number || "INV-2026-001"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-500">Seller / Exporter</span>
                  <span className="text-xs font-medium text-slate-700">
                    {activeInvoice?.seller_name || "Apex Global Exports Ltd"}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-500">Buyer Entity</span>
                  <span className="text-xs font-medium text-slate-700">
                    {activeInvoice?.buyer_name || "Nexus Retail International"}
                  </span>
                </div>
                <div className="flex justify-between items-center pt-2 border-t border-slate-200">
                  <span className="text-sm font-semibold text-slate-900">Total Payable</span>
                  <span className="text-lg font-bold text-blue-700">
                    {activeInvoice ? `${activeInvoice.currency} ${activeInvoice.total_amount}` : "USD 1,000.00"}
                  </span>
                </div>
              </div>

              {/* Auditor Status Pill */}
              <div className="flex items-center justify-between p-3 rounded-lg border bg-white">
                <span className="text-xs text-slate-600 font-medium">Auditor Approval Gate:</span>
                {isApproved ? (
                  <span className="inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                    <CheckCircle2 className="w-3.5 h-3.5 mr-1 text-emerald-600" />
                    Approved by Auditor
                  </span>
                ) : (
                  <span className="inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                    <Lock className="w-3.5 h-3.5 mr-1 text-amber-600" />
                    Locked: Pending Auditor Approval
                  </span>
                )}
              </div>

              {/* Checkout Status / Notice */}
              {checkoutNotice && (
                <div
                  className={`p-4 rounded-lg text-xs flex items-start space-x-2 ${
                    checkoutNotice.type === "success"
                      ? "bg-emerald-50 text-emerald-900 border border-emerald-200"
                      : checkoutNotice.type === "cancel"
                      ? "bg-amber-50 text-amber-900 border border-amber-200"
                      : "bg-rose-50 text-rose-900 border border-rose-200"
                  }`}
                >
                  {checkoutNotice.type === "success" && <CheckCircle2 className="w-4 h-4 text-emerald-600 mt-0.5" />}
                  {checkoutNotice.type === "cancel" && <Clock className="w-4 h-4 text-amber-600 mt-0.5" />}
                  {checkoutNotice.type === "error" && <XCircle className="w-4 h-4 text-rose-600 mt-0.5" />}
                  <div>{checkoutNotice.message}</div>
                </div>
              )}

              {/* PayPal Sandbox Button Mount Point */}
              {isApproved ? (
                <div className="pt-2">
                  <div className="text-xs font-medium text-slate-600 mb-2">
                    Pay securely via PayPal Sandbox:
                  </div>
                  <div ref={paypalContainerRef} className="min-h-[120px] flex items-center justify-center">
                    {!isScriptLoaded && (
                      <div className="flex items-center text-xs text-slate-400 space-x-2">
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        <span>Initializing PayPal Sandbox SDK...</span>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="p-6 bg-slate-50 border border-dashed border-slate-300 rounded-lg text-center space-y-2">
                  <Lock className="w-8 h-8 text-slate-400 mx-auto" />
                  <div className="text-xs font-semibold text-slate-700">Payment Unlocking Required</div>
                  <p className="text-xs text-slate-500 max-w-sm mx-auto">
                    In compliance with financial audit rules, you cannot pay this invoice until an authorized auditor
                    has validated the export documents and approved the invoice.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Auditor Approval Panel */}
          <div className="lg:col-span-5 space-y-6">
            <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
              <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                <div className="flex items-center space-x-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-600" />
                  <h2 className="text-base font-semibold">Auditor Review Panel</h2>
                </div>
                <span className="text-xs text-slate-500">Security Gate</span>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                Auditors can approve commercial export invoices using their configured <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-800">X-Auditor-Key</code>.
                Approvals are logged permanently in the <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-800">human_decisions</code> audit table.
              </p>

              {/* Approval Form */}
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Auditor Authorization Secret (X-Auditor-Key)
                  </label>
                  <input
                    type="password"
                    value={auditorKey}
                    onChange={(e) => setAuditorKey(e.target.value)}
                    placeholder="Enter AUDITOR_API_KEY..."
                    className="w-full text-xs px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Reviewer Identifier (Email / ID)
                  </label>
                  <input
                    type="text"
                    value={reviewerLabel}
                    onChange={(e) => setReviewerLabel(e.target.value)}
                    className="w-full text-xs px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 mb-1">
                    Auditor Notes & Justification
                  </label>
                  <textarea
                    rows={2}
                    value={approvalNotes}
                    onChange={(e) => setApprovalNotes(e.target.value)}
                    className="w-full text-xs px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                {approvalSuccess && (
                  <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-xs flex items-center space-x-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                    <span>{approvalSuccess}</span>
                  </div>
                )}

                {approvalError && (
                  <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-xs flex items-center space-x-2">
                    <AlertTriangle className="w-4 h-4 text-rose-600 flex-shrink-0" />
                    <span>{approvalError}</span>
                  </div>
                )}

                <button
                  onClick={handleApprove}
                  disabled={isApproving || !auditorKey}
                  className="w-full py-2 px-4 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white font-semibold text-xs rounded-lg transition-all shadow-sm flex items-center justify-center space-x-2"
                >
                  {isApproving ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Recording Human Decision...</span>
                    </>
                  ) : (
                    <>
                      <ShieldCheck className="w-3.5 h-3.5" />
                      <span>Approve Invoice for Payment</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Grounded AI Investigation */}
        <section className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-5" aria-labelledby="investigation-title">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <div>
              <h2 id="investigation-title" className="text-base font-semibold">AI Transaction Investigation</h2>
              <p className="text-xs text-slate-500 mt-1">Explanations use persisted transaction and reconciliation records. Every result still requires human review.</p>
            </div>
            <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-violet-50 text-violet-800 border border-violet-200">Grounded · Read only</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="text-xs font-medium text-slate-600">
              Transaction reference or UUID
              <input value={investigationReference} onChange={(e) => setInvestigationReference(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
            </label>
            <label className="text-xs font-medium text-slate-600 md:col-span-2">
              Question
              <textarea value={investigationQuestion} onChange={(e) => setInvestigationQuestion(e.target.value)} rows={2} maxLength={1000} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            {["Summarize this transaction and its reconciliation status.", "Explain the payment discrepancy and what evidence is still missing.", "Explain the payment fees and net proceeds recorded."].map((prompt) => (
              <button key={prompt} type="button" onClick={() => setInvestigationQuestion(prompt)} className="rounded-full border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">{prompt}</button>
            ))}
            <button type="button" onClick={runInvestigation} disabled={isInvestigating || !investigationReference.trim() || investigationQuestion.trim().length < 3} className="ml-auto rounded-lg bg-violet-700 px-4 py-2 text-xs font-semibold text-white disabled:bg-slate-300">
              {isInvestigating ? "Investigating…" : "Investigate"}
            </button>
          </div>
          {investigationError && <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{investigationError}</p>}
          {investigationResult && <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <strong className="text-sm">{investigationResult.transaction_reference}</strong>
              <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${investigationResult.status === "success" ? "bg-emerald-100 text-emerald-800" : investigationResult.status === "refusal" ? "bg-amber-100 text-amber-900" : "bg-rose-100 text-rose-800"}`}>{investigationResult.status}</span>
              <span className="text-xs text-slate-500">Provider: {investigationResult.provider}</span>
              <span className="text-xs font-semibold text-amber-800">Human review required</span>
            </div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{investigationResult.explanation}</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {([
                ["Invoice", investigationResult.authoritative_facts.invoice_total],
                ["Payment gross", investigationResult.authoritative_facts.payment_gross],
                ["Fee", investigationResult.authoritative_facts.fee_amount],
                ["Net", investigationResult.authoritative_facts.net_amount],
                ["Difference", investigationResult.authoritative_facts.unexplained_difference],
              ] as const).map(([label, amount]) => <div key={label} className="rounded border border-slate-200 bg-white p-2"><div className="text-[10px] uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold">{amount ? `${amount.currency} ${amount.amount}` : "Not recorded"}</div></div>)}
            </div>
            {!investigationResult.authoritative_facts.currencies_match && <p className="text-xs font-medium text-amber-800">{investigationResult.authoritative_facts.currency_mismatch_warning}</p>}
            {investigationResult.missing_information.length > 0 && <div className="text-xs"><strong>Missing information</strong><ul className="list-disc pl-5">{investigationResult.missing_information.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
            {investigationResult.suggested_next_action && <p className="text-xs"><strong>Suggested human action:</strong> {investigationResult.suggested_next_action}</p>}
            {investigationResult.draft_clarification_message && <label className="block text-xs font-medium">Draft clarification (copy and review before sending)<textarea readOnly value={investigationResult.draft_clarification_message} rows={4} className="mt-1 w-full rounded border border-slate-300 bg-white p-2 font-normal" /></label>}
            {investigationResult.warnings.length > 0 && <ul className="list-disc pl-5 text-xs text-amber-800">{investigationResult.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>}
            <p className="text-[11px] text-slate-500">Cited persisted records: {investigationResult.cited_record_ids.length ? investigationResult.cited_record_ids.join(", ") : "None returned"}</p>
          </div>}
        </section>

        {/* Payment Ingestion & Audit Table */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <div className="flex items-center space-x-2">
              <FileText className="w-5 h-5 text-blue-600" />
              <h2 className="text-base font-semibold">Payment Proceeds & Ingestion Audit Log</h2>
            </div>
            <button
              onClick={() => refetchPayments()}
              className="inline-flex items-center text-xs text-slate-500 hover:text-slate-800 space-x-1"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Refresh Log</span>
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-xs">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="py-2.5 px-3 text-left font-semibold">Provider Order / Capture ID</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Invoice Ref</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Gross Amount</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Fee (Documented)</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Net Proceeds</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Status</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Environment</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Event Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {payments && payments.length > 0 ? (
                  payments.map((p) => (
                    <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                      <td className="py-2.5 px-3 font-mono font-medium">
                        {p.provider_capture_id || p.provider_refund_id || p.provider_order_id || p.id}
                        {p.provider_refund_id && (
                          <span className="ml-1.5 text-[10px] bg-rose-100 text-rose-800 px-1.5 py-0.5 rounded">
                            Refund
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">{p.invoice_reference || "N/A"}</td>
                      <td className="py-2.5 px-3 font-semibold text-slate-900">
                        {p.currency} {p.gross_amount}
                      </td>
                      <td className="py-2.5 px-3">
                        {p.fee_amount !== null && p.fee_amount !== undefined ? (
                          `${p.currency} ${p.fee_amount}`
                        ) : (
                          <span className="text-slate-400 italic">Unavailable / pending settlement</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 font-medium text-emerald-700">
                        {p.net_amount !== null && p.net_amount !== undefined ? (
                          `${p.currency} ${p.net_amount}`
                        ) : (
                          <span className="text-slate-400 italic">Unavailable / pending settlement</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            p.status === "completed"
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : p.status === "refunded"
                              ? "bg-rose-50 text-rose-700 border border-rose-200"
                              : p.status === "pending"
                              ? "bg-amber-50 text-amber-700 border border-amber-200"
                              : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {p.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="bg-amber-50 text-amber-800 text-[10px] font-semibold px-2 py-0.5 rounded border border-amber-200">
                          {p.environment}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-slate-500">
                        {p.event_time ? new Date(p.event_time).toLocaleString() : "Pending"}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-slate-400">
                      No payment records found. Initiate a Sandbox payment above.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}

