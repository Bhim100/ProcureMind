"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
  Printer,
  X,
  ExternalLink,
  Filter,
} from "lucide-react";
import AppShell from "@/components/layout/AppShell";
import {
  getPayPalConfig,
  getPayments,
  getInvoices,
  approveInvoice,
  initiatePayment,
  captureOrder,
  simulatePaymentCapture,
  PaymentRead,
  InvoiceSummaryItem,
} from "@/lib/api";
import { useAuditorSession } from "@/lib/auditor-session";
import { useDemoFilter } from "@/lib/demo-filter-context";

export default function PaymentsPage() {
  const queryClient = useQueryClient();
  const { auditorKey, reviewer, openKeyModal } = useAuditorSession();

  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string>("");
  const [approvalNotes, setApprovalNotes] = useState<string>("Verified commercial invoice against shipping manifests");
  const [isApproving, setIsApproving] = useState<boolean>(false);
  const [approvalSuccess, setApprovalSuccess] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [checkoutNotice, setCheckoutNotice] = useState<{ type: "success" | "cancel" | "error"; message: string } | null>(null);

  // Filters for payments table
  const [paymentEnvFilter, setPaymentEnvFilter] = useState<string>("");
  const [demoOnlyFilter, setDemoOnlyFilter] = useState<boolean | undefined>(undefined);

  // Selected payment for Sandbox Receipt Modal
  const [receiptPayment, setReceiptPayment] = useState<PaymentRead | null>(null);

  const paypalContainerRef = useRef<HTMLDivElement>(null);
  const [isScriptLoaded, setIsScriptLoaded] = useState<boolean>(false);

  // 1. Fetch PayPal public config
  const { data: paypalConfig } = useQuery({
    queryKey: ["paypalConfig"],
    queryFn: getPayPalConfig,
  });

  const { includeDemo } = useDemoFilter();

  // 2. Fetch invoices from PostgreSQL
  const { data: invoiceData, isLoading: invoicesLoading, refetch: refetchInvoices } = useQuery({
    queryKey: ["invoices-list", includeDemo],
    queryFn: () => getInvoices({ limit: 50, is_demo: includeDemo ? undefined : false }),
  });

  const invoices = useMemo(() => invoiceData?.items || [], [invoiceData]);
  const activeInvoice: InvoiceSummaryItem | undefined =
    invoices.find((i: InvoiceSummaryItem) => i.id === selectedInvoiceId) || invoices[0];

  useEffect(() => {
    if (invoices.length > 0) {
      if (!selectedInvoiceId || !invoices.some((i) => i.id === selectedInvoiceId)) {
        setSelectedInvoiceId(invoices[0].id);
      }
    }
  }, [invoices, selectedInvoiceId]);

  // 3. Fetch list of payments with filters
  const { data: payments = [], isLoading: paymentsLoading, refetch: refetchPayments } = useQuery({
    queryKey: ["payments", paymentEnvFilter, demoOnlyFilter, includeDemo],
    queryFn: () =>
      getPayments({
        environment: paymentEnvFilter || undefined,
        is_demo: !includeDemo ? false : demoOnlyFilter,
        limit: 50,
      }),
    refetchInterval: 5000,
  });

  const isApproved = activeInvoice?.is_approved ?? false;
  const activeInvoiceId = activeInvoice?.id;

  // Handle Auditor Approval Action
  const handleApprove = async () => {
    if (!activeInvoice?.id) return;
    if (!auditorKey) {
      openKeyModal();
      return;
    }
    setIsApproving(true);
    setApprovalError(null);
    setApprovalSuccess(null);
    try {
      await approveInvoice(
        activeInvoice.id,
        reviewer || "Compliance Reviewer",
        approvalNotes,
        auditorKey
      );
      setApprovalSuccess("Invoice approved! PayPal Sandbox checkout is now unlocked.");
      refetchInvoices();
      queryClient.invalidateQueries({ queryKey: ["invoices-list"] });
    } catch (err: any) {
      setApprovalError(err.message || "Failed to approve invoice.");
    } finally {
      setIsApproving(false);
    }
  };

  const [isSimulating, setIsSimulating] = useState(false);

  // Handle Direct Sandbox Simulation
  const handleSimulatePayment = async () => {
    if (!activeInvoice?.id) return;
    setIsSimulating(true);
    setCheckoutNotice(null);
    try {
      const payment = await simulatePaymentCapture(activeInvoice.id);
      setReceiptPayment(payment);
      setCheckoutNotice({
        type: "success",
        message: `Simulated Sandbox capture successful! Captured ${payment.currency} ${payment.gross_amount} (Capture ID: ${payment.provider_capture_id || "SIM-CAP"}). Reconciliation engine executed!`,
      });
      refetchPayments();
      refetchInvoices();
      queryClient.invalidateQueries({ queryKey: ["reconciliationQueue"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    } catch (err: any) {
      const msg =
        err.message === "Failed to fetch"
          ? "Unable to connect to the backend server (http://localhost:8000). Please check that the backend is running."
          : err.message || "Failed to simulate payment capture.";
      setCheckoutNotice({
        type: "error",
        message: msg,
      });
    } finally {
      setIsSimulating(false);
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
    const paypal = typeof window !== "undefined" ? (window as any).paypal : undefined;
    if (!isScriptLoaded || !paypal || !paypalContainerRef.current || !isApproved || !activeInvoiceId) {
      return;
    }

    paypalContainerRef.current.innerHTML = "";

    try {
      paypal
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
              refetchInvoices();
              queryClient.invalidateQueries({ queryKey: ["reconciliation-queue"] });
              queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
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
  }, [isScriptLoaded, isApproved, activeInvoiceId, refetchInvoices, refetchPayments, queryClient]);

  return (
    <AppShell activeNav="payments">
      <div className="space-y-8">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">PayPal Sandbox Payments</h1>
            <p className="text-xs text-slate-400 mt-1">
              Simulated export payment capture, human approval gate, and immutable ledger receipts.
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 font-semibold uppercase tracking-wider">
              Sandbox Mode Only
            </span>
            <button
              onClick={() => {
                refetchPayments();
                refetchInvoices();
              }}
              className="inline-flex items-center px-3 py-1.5 rounded-lg border border-[#1e293b] bg-[#0c1322] hover:bg-[#1e293b] text-xs font-medium text-slate-300 transition-all"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              Refresh
            </button>
          </div>
        </div>

        {/* Environment Alert Banner */}
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-start space-x-3 shadow-lg">
          <Info className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-200/90 leading-relaxed">
            <span className="font-bold uppercase tracking-wider block text-amber-300 mb-0.5">
              PayPal Sandbox Simulation Environment
            </span>
            All transactions and payments on this page operate strictly in the PayPal Sandbox environment.
            No live payments, cards, or funds are debited. In compliance with strict financial controls,
            payments can only be initiated once an authorized human auditor decision is recorded in PostgreSQL.
          </div>
        </div>

        {/* Two-Column Grid: Checkout Box & Auditor Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left Column: Commercial Invoice Selection & Checkout */}
          <div className="lg:col-span-7 space-y-6">
            <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-6">
              <div className="flex items-center justify-between border-b border-[#1e293b] pb-4">
                <div className="flex items-center space-x-2">
                  <CreditCard className="w-5 h-5 text-blue-400" />
                  <h2 className="text-base font-semibold text-white">Overseas Buyer Checkout</h2>
                </div>
                <span className="bg-blue-500/10 text-blue-400 text-xs font-medium px-2.5 py-1 rounded-full border border-blue-500/20">
                  PayPal Orders v2 (Capture)
                </span>
              </div>

              {/* Invoice Selector */}
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                  Select Export Invoice
                </label>
                {invoicesLoading ? (
                  <div className="p-3 text-xs text-slate-500">Loading invoices...</div>
                ) : (
                  <select
                    value={activeInvoice?.id || ""}
                    onChange={(e) => setSelectedInvoiceId(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl bg-[#080d1a] border border-[#1e293b] text-white text-xs font-medium focus:outline-none focus:border-blue-500"
                  >
                    {invoices.map((inv: InvoiceSummaryItem) => (
                      <option key={inv.id} value={inv.id}>
                        {inv.invoice_number} — {inv.buyer_name} ({inv.currency} {inv.total_amount})
                        {inv.is_approved ? " [Approved]" : " [Pending Approval]"}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Invoice Summary Card */}
              {activeInvoice && (
                <div className="bg-[#0f172a] border border-[#1e293b] rounded-xl p-5 space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-400 font-medium">Commercial Invoice</span>
                    <span className="text-sm font-bold text-white font-mono">
                      {activeInvoice.invoice_number}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-400">Seller / Exporter</span>
                    <span className="text-xs font-medium text-slate-200">
                      {activeInvoice.seller_name}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-400">Buyer Entity</span>
                    <span className="text-xs font-medium text-slate-200">
                      {activeInvoice.buyer_name}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-slate-400">Remaining PostgreSQL Balance</span>
                    <span className="text-xs font-mono font-semibold text-amber-400">
                      {activeInvoice.currency} {activeInvoice.remaining_balance}
                    </span>
                  </div>
                  <div className="flex justify-between items-center pt-3 border-t border-[#1e293b]">
                    <span className="text-sm font-semibold text-slate-200">Total Payable</span>
                    <span className="text-lg font-bold text-blue-400 font-mono">
                      {activeInvoice.currency} {activeInvoice.total_amount}
                    </span>
                  </div>
                </div>
              )}

              {/* Auditor Status Pill */}
              <div className="flex items-center justify-between p-3.5 rounded-xl border border-[#1e293b] bg-[#080d1a]">
                <span className="text-xs text-slate-400 font-medium">Auditor Approval Gate:</span>
                {isApproved ? (
                  <span className="inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
                    Approved by Auditor
                  </span>
                ) : (
                  <span className="inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
                    <Lock className="w-3.5 h-3.5 mr-1" />
                    Locked: Pending Auditor Approval
                  </span>
                )}
              </div>

              {/* Checkout Status / Notice */}
              {checkoutNotice && (
                <div
                  className={`p-4 rounded-xl text-xs flex flex-col gap-2.5 ${
                    checkoutNotice.type === "success"
                      ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                      : checkoutNotice.type === "cancel"
                      ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                      : "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                  }`}
                >
                  <div className="flex items-start space-x-2.5">
                    {checkoutNotice.type === "success" && <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />}
                    {checkoutNotice.type === "cancel" && <Clock className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />}
                    {checkoutNotice.type === "error" && <XCircle className="w-4 h-4 text-rose-400 mt-0.5 flex-shrink-0" />}
                    <div className="leading-relaxed">{checkoutNotice.message}</div>
                  </div>
                  {checkoutNotice.type === "success" && (
                    <div className="pt-1">
                      <Link
                        href="/reconciliation"
                        className="inline-flex items-center px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-colors shadow-md"
                      >
                        <span>Open Reconciliation Queue</span>
                        <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                      </Link>
                    </div>
                  )}
                </div>
              )}

              {/* PayPal Sandbox Payment Options */}
              {isApproved ? (
                <div className="pt-2 space-y-4">
                  {/* Direct Instant Sandbox Payment (No phone or PayPal account required) */}
                  {Number(activeInvoice?.remaining_balance ?? 1) <= 0 ? (
                    <div className="p-4 rounded-xl bg-[#081220] border border-emerald-500/30 text-emerald-300 text-xs flex flex-col gap-3 shadow-lg">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-white flex items-center">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400 mr-2" />
                          Invoice is Fully Settled & Reconciled
                        </span>
                        <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 font-semibold">
                          Remaining Balance: {activeInvoice?.currency} 0.00
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Payment for invoice <strong className="text-slate-200">{activeInvoice?.invoice_number}</strong> has been completely captured and allocated in the ledger.
                      </p>
                      <div className="pt-1">
                        <Link
                          href="/reconciliation"
                          className="inline-flex items-center px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition-colors shadow-md"
                        >
                          <span>Open in Reconciliation Queue</span>
                          <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                        </Link>
                      </div>
                    </div>
                  ) : (
                    <div className="p-4 rounded-xl bg-gradient-to-br from-[#0c1a2e] to-[#081220] border border-emerald-500/30 space-y-3 shadow-lg">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-white flex items-center">
                          <CreditCard className="w-4 h-4 text-emerald-400 mr-1.5" />
                          Simulate PayPal Sandbox Payment
                        </span>
                        <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 font-semibold">
                          Instant · No Login Needed
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">
                        Bypasses PayPal SMS rate-limits. Executes an authoritative simulated PayPal Sandbox capture in PostgreSQL for {activeInvoice?.currency} {activeInvoice?.remaining_balance || activeInvoice?.total_amount} with standard merchant fee deductions, immediately triggering the reconciliation engine!
                      </p>
                      <button
                        onClick={handleSimulatePayment}
                        disabled={isSimulating}
                        className="w-full py-2.5 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center space-x-2 disabled:opacity-50 cursor-pointer"
                      >
                        {isSimulating ? (
                          <>
                            <RefreshCw className="w-4 h-4 animate-spin mr-1.5" />
                            <span>Simulating Sandbox Capture...</span>
                          </>
                        ) : (
                          <>
                            <span>⚡ Simulate Sandbox Payment ({activeInvoice?.currency} {activeInvoice?.remaining_balance || activeInvoice?.total_amount})</span>
                          </>
                        )}
                      </button>
                    </div>
                  )}

                  {/* Standard PayPal SDK Container */}
                  <div className="pt-2 border-t border-[#1e293b]">
                    <div className="text-[11px] font-medium text-slate-500 mb-2">
                      Or pay with official PayPal Sandbox popup:
                    </div>
                    <div ref={paypalContainerRef} className="min-h-[60px] flex items-center justify-center p-3 rounded-xl bg-[#080d1a] border border-[#1e293b]">
                      {!isScriptLoaded && (
                        <div className="flex items-center text-xs text-slate-500 space-x-2">
                          <span>PayPal SDK button activates when Client ID is set in .env</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-6 bg-[#080d1a] border border-dashed border-[#1e293b] rounded-xl text-center space-y-2">
                  <Lock className="w-8 h-8 text-slate-600 mx-auto" />
                  <div className="text-xs font-semibold text-slate-300">Payment Unlocking Required</div>
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
            <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl p-6 shadow-xl space-y-5">
              <div className="flex items-center space-x-2 border-b border-[#1e293b] pb-4">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <h3 className="text-base font-semibold text-white">Auditor Approval Controls</h3>
              </div>

              <div className="space-y-4 text-xs">
                <div>
                  <label className="block text-slate-400 font-medium mb-1">Auditor Session Identity</label>
                  <div className="p-2.5 rounded-lg bg-[#080d1a] border border-[#1e293b] text-slate-300 font-mono flex items-center justify-between">
                    <span>{reviewer || "Compliance Reviewer"}</span>
                    <button
                      onClick={openKeyModal}
                      className="text-blue-400 hover:text-blue-300 text-[11px] underline"
                    >
                      Change
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">
                    Auditor Key Status
                  </label>
                  <div className="p-2.5 rounded-lg bg-[#080d1a] border border-[#1e293b] flex items-center justify-between">
                    <span className="text-slate-300">
                      {auditorKey ? "•••••••••••• (Configured)" : "Not Configured"}
                    </span>
                    {!auditorKey && (
                      <button
                        onClick={openKeyModal}
                        className="text-amber-400 hover:text-amber-300 text-[11px] font-semibold underline"
                      >
                        Set Key
                      </button>
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">
                    Auditor Justification Notes <span className="text-rose-400">*</span>
                  </label>
                  <textarea
                    value={approvalNotes}
                    onChange={(e) => setApprovalNotes(e.target.value)}
                    rows={3}
                    className="w-full px-3 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-white focus:outline-none focus:border-blue-500"
                    placeholder="Enter verification notes for compliance log..."
                  />
                </div>

                {approvalSuccess && (
                  <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center space-x-2">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                    <span>{approvalSuccess}</span>
                  </div>
                )}

                {approvalError && (
                  <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center space-x-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <span>{approvalError}</span>
                  </div>
                )}

                <button
                  onClick={handleApprove}
                  disabled={isApproving || isApproved || !approvalNotes.trim()}
                  className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold text-xs transition-colors shadow-lg shadow-blue-500/20"
                >
                  {isApproving
                    ? "Submitting Approval..."
                    : isApproved
                    ? "Invoice Already Approved"
                    : "Authorize Invoice for Payment"}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Payments Ledger Section */}
        <div className="bg-[#0c1322] rounded-2xl border border-[#1e293b] shadow-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-[#1e293b] flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#080d1a]/50">
            <div>
              <h2 className="text-sm font-semibold text-white">Persisted Payments Ledger</h2>
              <p className="text-[11px] text-slate-500">
                Authoritative PostgreSQL payment records with PayPal capture details.
              </p>
            </div>

            {/* Filter controls */}
            <div className="flex items-center space-x-3 text-xs">
              <div className="flex items-center space-x-1.5 text-slate-400">
                <Filter className="w-3.5 h-3.5" />
                <span>Env:</span>
                <select
                  value={paymentEnvFilter}
                  onChange={(e) => setPaymentEnvFilter(e.target.value)}
                  className="px-2 py-1 rounded bg-[#080d1a] border border-[#1e293b] text-white text-xs"
                >
                  <option value="">All</option>
                  <option value="sandbox">Sandbox</option>
                  <option value="simulated">Simulated</option>
                  <option value="live">Live</option>
                </select>
              </div>

              <div className="flex items-center space-x-1.5 text-slate-400">
                <span>Demo:</span>
                <select
                  value={demoOnlyFilter === undefined ? "" : String(demoOnlyFilter)}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDemoOnlyFilter(v === "" ? undefined : v === "true");
                  }}
                  className="px-2 py-1 rounded bg-[#080d1a] border border-[#1e293b] text-white text-xs"
                >
                  <option value="">All</option>
                  <option value="true">Demo Only</option>
                  <option value="false">Non-Demo</option>
                </select>
              </div>
            </div>
          </div>

          {paymentsLoading ? (
            <div className="p-12 text-center text-slate-400 text-xs">Loading payment ledger...</div>
          ) : payments.length === 0 ? (
            <div className="p-12 text-center text-slate-400 text-xs">No payment captures found.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300 divide-y divide-[#1e293b]">
                <thead className="bg-[#080d1a] text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  <tr>
                    <th scope="col" className="px-6 py-3.5">Provider / Capture ID</th>
                    <th scope="col" className="px-6 py-3.5">Gross Amount</th>
                    <th scope="col" className="px-6 py-3.5">Fee</th>
                    <th scope="col" className="px-6 py-3.5">Net</th>
                    <th scope="col" className="px-6 py-3.5">Status</th>
                    <th scope="col" className="px-6 py-3.5">Environment</th>
                    <th scope="col" className="px-6 py-3.5">Payer Email</th>
                    <th scope="col" className="px-6 py-3.5 text-right">Receipt</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1e293b]/60 font-normal">
                  {payments.map((p) => (
                    <tr key={p.id} className="hover:bg-[#0f172a] transition-colors">
                      <td className="px-6 py-4 font-mono text-slate-200">
                        {p.provider_capture_id || p.provider_order_id || p.id.slice(0, 8)}
                      </td>
                      <td className="px-6 py-4 font-mono font-semibold text-white">
                        {p.currency} {p.gross_amount}
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-400">
                        {p.fee_amount ? `${p.currency} ${p.fee_amount}` : "—"}
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {p.net_amount ? `${p.currency} ${p.net_amount}` : "—"}
                      </td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          {p.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20 uppercase font-mono">
                          {p.environment}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-400">
                        {p.payer_email || "N/A"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => setReceiptPayment(p)}
                          className="inline-flex items-center px-2.5 py-1.5 rounded-lg border border-[#1e293b] bg-[#080d1a] hover:bg-[#1e293b] text-slate-300 text-xs font-medium transition-all"
                        >
                          <FileText className="w-3.5 h-3.5 mr-1 text-slate-400" />
                          View Receipt
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ProcureMind Sandbox Payment Receipt Modal */}
      {receiptPayment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0c1322] border border-[#1e293b] rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between border-b border-[#1e293b] pb-4">
              <div>
                <span className="text-[11px] font-bold tracking-wider uppercase text-blue-400">
                  ProcureMind Reconciliation Engine
                </span>
                <h3 className="text-lg font-bold text-white mt-0.5">
                  ProcureMind Sandbox Payment Receipt
                </h3>
              </div>
              <button
                onClick={() => setReceiptPayment(null)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Mandatory Disclaimers */}
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3.5 space-y-1 text-xs text-amber-200">
              <div className="font-bold uppercase tracking-wider text-amber-400">
                SIMULATED TRANSACTION — NO REAL FUNDS SETTLED
              </div>
              <div className="text-[11px] text-amber-300/90 leading-tight">
                NOT AN OFFICIAL PAYPAL SETTLEMENT RECEIPT. This record is generated for export audit simulation and reconciliation testing only.
              </div>
            </div>

            {/* Payment Details */}
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Payment ID</span>
                  <span className="font-mono text-slate-200 text-xs break-all">{receiptPayment.id}</span>
                </div>
                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Capture ID</span>
                  <span className="font-mono text-slate-200 text-xs break-all">
                    {receiptPayment.provider_capture_id || "N/A"}
                  </span>
                </div>
              </div>

              <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b] space-y-2">
                <div className="flex justify-between">
                  <span className="text-slate-400">Gross Captured Amount</span>
                  <span className="font-mono font-bold text-white text-sm">
                    {receiptPayment.currency} {receiptPayment.gross_amount}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">PayPal Processing Fee</span>
                  <span className="font-mono text-slate-300">
                    {receiptPayment.fee_amount ? `${receiptPayment.currency} ${receiptPayment.fee_amount}` : "0.00"}
                  </span>
                </div>
                <div className="flex justify-between pt-2 border-t border-[#1e293b]">
                  <span className="text-slate-300 font-semibold">Net Credited Amount</span>
                  <span className="font-mono font-bold text-emerald-400">
                    {receiptPayment.net_amount ? `${receiptPayment.currency} ${receiptPayment.net_amount}` : `${receiptPayment.currency} ${receiptPayment.gross_amount}`}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Buyer Email</span>
                  <span className="text-slate-200">{receiptPayment.payer_email || "N/A"}</span>
                </div>
                <div className="bg-[#080d1a] p-3 rounded-xl border border-[#1e293b]">
                  <span className="text-slate-500 block text-[10px] uppercase font-semibold">Status / Environment</span>
                  <span className="text-slate-200 font-mono">
                    {receiptPayment.status.toUpperCase()} ({receiptPayment.environment})
                  </span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end space-x-3 pt-2 border-t border-[#1e293b]">
              <button
                onClick={() => setReceiptPayment(null)}
                className="px-4 py-2 rounded-lg bg-[#080d1a] border border-[#1e293b] text-slate-300 hover:text-white text-xs font-medium"
              >
                Close
              </button>
              <button
                onClick={() => window.print()}
                className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20"
              >
                <Printer className="w-3.5 h-3.5" />
                <span>Print Sandbox Receipt</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
