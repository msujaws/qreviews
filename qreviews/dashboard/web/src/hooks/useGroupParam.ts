import { useCallback, useEffect, useState } from "react";

const PARAM = "group";

function readParam(): string | null {
  return new URLSearchParams(window.location.search).get(PARAM);
}

function buildUrl(value: string | null): string {
  const params = new URLSearchParams(window.location.search);
  if (value) {
    params.set(PARAM, value);
  } else {
    params.delete(PARAM);
  }
  const qs = params.toString();
  return `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
}

export function useGroupParam(): [string | null, (value: string | null) => void] {
  const [group, setGroup] = useState<string | null>(() => readParam());

  useEffect(() => {
    const onPopState = () => setGroup(readParam());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const setGroupAndUrl = useCallback((value: string | null) => {
    window.history.pushState(null, "", buildUrl(value));
    setGroup(value);
  }, []);

  return [group, setGroupAndUrl];
}
