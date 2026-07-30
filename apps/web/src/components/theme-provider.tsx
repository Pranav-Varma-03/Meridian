"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void } | null>(null);
const storageKey = "meridian-theme";

function applyTheme(theme: Theme) {
  const prefersDark = typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("system");
  useEffect(() => { const stored = window.localStorage.getItem(storageKey); const initial: Theme = stored === "light" || stored === "dark" || stored === "system" ? stored : "system"; setThemeState(initial); applyTheme(initial); }, []);
  const setTheme = (next: Theme) => { setThemeState(next); window.localStorage.setItem(storageKey, next); applyTheme(next); };
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}
export function useTheme() { const context = useContext(ThemeContext); if (!context) throw new Error("useTheme must be used inside ThemeProvider"); return context; }
