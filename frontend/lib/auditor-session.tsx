"use client";

import React, { createContext, useContext, useState, ReactNode } from "react";

interface AuditorContextType {
  auditorKey: string;
  setAuditorKey: (key: string) => void;
  reviewerLabel: string;
  reviewer: string;
  setReviewerLabel: (label: string) => void;
  hasKey: boolean;
  clearKey: () => void;
  clearSession: () => void;
  isKeyModalOpen: boolean;
  openKeyModal: () => void;
  closeKeyModal: () => void;
}

const AuditorContext = createContext<AuditorContextType>({
  auditorKey: "",
  setAuditorKey: () => {},
  reviewerLabel: "auditor@procuremind.io",
  reviewer: "auditor@procuremind.io",
  setReviewerLabel: () => {},
  hasKey: false,
  clearKey: () => {},
  clearSession: () => {},
  isKeyModalOpen: false,
  openKeyModal: () => {},
  closeKeyModal: () => {},
});

export function AuditorProvider({ children }: { children: ReactNode }) {
  // Stored strictly in React memory state during the active browser session.
  // Never written to localStorage, cookies, or public environment variables.
  const [auditorKey, setAuditorKeyState] = useState<string>("");
  const [reviewerLabel, setReviewerLabel] = useState<string>("auditor@procuremind.io");
  const [isKeyModalOpen, setIsKeyModalOpen] = useState<boolean>(false);

  const setAuditorKey = (key: string) => {
    setAuditorKeyState(key.trim());
  };

  const clearKey = () => {
    setAuditorKeyState("");
  };

  const openKeyModal = () => setIsKeyModalOpen(true);
  const closeKeyModal = () => setIsKeyModalOpen(false);

  return (
    <AuditorContext.Provider
      value={{
        auditorKey,
        setAuditorKey,
        reviewerLabel,
        reviewer: reviewerLabel,
        setReviewerLabel,
        hasKey: auditorKey.length > 0,
        clearKey,
        clearSession: clearKey,
        isKeyModalOpen,
        openKeyModal,
        closeKeyModal,
      }}
    >
      {children}
    </AuditorContext.Provider>
  );
}

export function useAuditor() {
  return useContext(AuditorContext);
}

export const useAuditorSession = useAuditor;
