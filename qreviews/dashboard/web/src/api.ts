import type {
  Group,
  Histograms,
  RevisionDetail,
  Summary,
  TimeseriesPoint,
} from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`${path} → ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

const qs = (group: string | null) =>
  group ? `?group=${encodeURIComponent(group)}` : "";

export const api = {
  groups: () => get<Group[]>("/api/groups"),
  summary: (group: string | null) => get<Summary>(`/api/summary${qs(group)}`),
  histograms: (group: string | null) => get<Histograms>(`/api/histograms${qs(group)}`),
  timeseries: (group: string | null, days = 30) => {
    const sep = group ? "&" : "?";
    return get<TimeseriesPoint[]>(`/api/timeseries${qs(group)}${sep}days=${days}`);
  },
  revisions: (group: string | null, limit = 100) => {
    const sep = group ? "&" : "?";
    return get<RevisionDetail[]>(`/api/revisions${qs(group)}${sep}limit=${limit}`);
  },
  revision: (id: number) => get<RevisionDetail>(`/api/revision/${id}`),
};
