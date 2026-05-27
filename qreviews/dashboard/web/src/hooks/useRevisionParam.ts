import { useCallback, useEffect, useState } from "react";

const PARAM = "rev";

function parseRevisionParam(raw: string | null): number | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  const body = trimmed.startsWith("D") || trimmed.startsWith("d") ? trimmed.slice(1) : trimmed;
  if (!/^\d+$/.test(body)) return null;
  const n = Number(body);
  return Number.isFinite(n) ? n : null;
}

function readParam(): number | null {
  return parseRevisionParam(new URLSearchParams(window.location.search).get(PARAM));
}

function buildUrl(value: number | null): string {
  const params = new URLSearchParams(window.location.search);
  if (value !== null) {
    params.set(PARAM, `D${value}`);
  } else {
    params.delete(PARAM);
  }
  const qs = params.toString();
  return `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
}

export function useRevisionParam(): [number | null, (value: number | null) => void] {
  const [revision, setRevision] = useState<number | null>(() => readParam());

  useEffect(() => {
    const onPopState = () => setRevision(readParam());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const setRevisionAndUrl = useCallback((value: number | null) => {
    window.history.pushState(null, "", buildUrl(value));
    setRevision(value);
  }, []);

  return [revision, setRevisionAndUrl];
}
