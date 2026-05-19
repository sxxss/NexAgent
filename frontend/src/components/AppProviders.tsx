"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 20_000,
            retry: 1,
          },
        },
      }),
  );

  useEffect(() => {
    const saved = localStorage.getItem("nexagent-theme");
    const theme = saved === "dark" ? "dark" : "light";
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
