"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("nexagent-theme", theme);
}

export function ThemeToggle() {
  // Render the light-mode icon on the server and the first client paint to keep
  // SSR markup consistent; sync the real theme from localStorage after mount.
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Sync the real theme from localStorage after mount to avoid a hydration mismatch.
    /* eslint-disable react-hooks/set-state-in-effect */
    setMounted(true);
    setTheme(window.localStorage.getItem("nexagent-theme") === "dark" ? "dark" : "light");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  useEffect(() => {
    if (mounted) applyTheme(theme);
  }, [theme, mounted]);

  return (
    <button
      type="button"
      onClick={() => setTheme((value) => (value === "dark" ? "light" : "dark"))}
      title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
      aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
      className="flex h-11 w-11 items-center justify-center rounded-2xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
    >
      {theme === "dark" ? <Sun size={18} className="text-amber-500" /> : <Moon size={18} />}
    </button>
  );
}
