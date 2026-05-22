import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

const REFETCH_MS = 30_000;

export function useDashboardData(group: string | null) {
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: api.groups,
  });

  const summary = useQuery({
    queryKey: ["summary", group],
    queryFn: () => api.summary(group),
    refetchInterval: REFETCH_MS,
  });

  const histograms = useQuery({
    queryKey: ["histograms", group],
    queryFn: () => api.histograms(group),
    refetchInterval: REFETCH_MS,
  });

  const timeseries = useQuery({
    queryKey: ["timeseries", group],
    queryFn: () => api.timeseries(group),
    refetchInterval: REFETCH_MS,
  });

  const revisions = useQuery({
    queryKey: ["revisions", group],
    queryFn: () => api.revisions(group),
    refetchInterval: REFETCH_MS,
  });

  return { groups, summary, histograms, timeseries, revisions };
}

export function useRevisionDetail(revisionId: number | null) {
  return useQuery({
    queryKey: ["revision", revisionId],
    queryFn: () => api.revision(revisionId as number),
    enabled: revisionId !== null,
  });
}
