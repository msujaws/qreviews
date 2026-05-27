import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { MantineProvider } from "@mantine/core";

import { theme } from "./theme";

export type ColorScheme = "light" | "dark";

interface ColorSchemeContext {
  colorScheme: ColorScheme;
  setColorScheme: (scheme: ColorScheme) => void;
  toggle: () => void;
}

const Ctx = createContext<ColorSchemeContext | null>(null);
const STORAGE_KEY = "qreviews-color-scheme";

function readInitialScheme(): ColorScheme {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(readInitialScheme);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, colorScheme);
  }, [colorScheme]);

  const setColorScheme = (scheme: ColorScheme) => setColorSchemeState(scheme);
  const toggle = () =>
    setColorSchemeState((current) => (current === "dark" ? "light" : "dark"));

  const value = useMemo<ColorSchemeContext>(
    () => ({ colorScheme, setColorScheme, toggle }),
    [colorScheme],
  );

  return (
    <Ctx.Provider value={value}>
      <MantineProvider theme={theme} forceColorScheme={colorScheme}>
        {children}
      </MantineProvider>
    </Ctx.Provider>
  );
}

export function useColorScheme(): ColorSchemeContext {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useColorScheme must be used inside ThemeProvider");
  }
  return ctx;
}
