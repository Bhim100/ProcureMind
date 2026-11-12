"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface DemoFilterContextType {
  includeDemo: boolean;
  setIncludeDemo: (val: boolean) => void;
  toggleDemo: () => void;
}

const DemoFilterContext = createContext<DemoFilterContextType>({
  includeDemo: true,
  setIncludeDemo: () => {},
  toggleDemo: () => {},
});

export function DemoFilterProvider({ children }: { children: ReactNode }) {
  const [includeDemo, setIncludeDemoState] = useState<boolean>(true);

  // Hydrate from localStorage on client mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem("pm_include_demo");
      if (stored !== null) {
        setIncludeDemoState(stored === "true");
      }
    } catch {
      // Ignore localStorage errors (e.g. private browsing)
    }
  }, []);

  const setIncludeDemo = (val: boolean) => {
    setIncludeDemoState(val);
    try {
      localStorage.setItem("pm_include_demo", String(val));
    } catch {
      // Ignore
    }
  };

  const toggleDemo = () => {
    setIncludeDemoState((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("pm_include_demo", String(next));
      } catch {
        // Ignore
      }
      return next;
    });
  };

  return (
    <DemoFilterContext.Provider value={{ includeDemo, setIncludeDemo, toggleDemo }}>
      {children}
    </DemoFilterContext.Provider>
  );
}

export function useDemoFilter() {
  return useContext(DemoFilterContext);
}

