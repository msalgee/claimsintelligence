//
// Lightweight hook to fetch and cache section data from a `/claimsdemo/...`
// endpoint. Stores the result in the zustand `data` cache keyed by step number
// so re-expanding a "done" section doesn't refetch.

import { useEffect, useState } from 'react';
import { useClaimStore } from '../store/claimStore';

interface AsyncState<T> {
  loading: boolean;
  error: string | null;
  data: T | null;
}

export function useSectionData<T>(
  step: number,
  fetcher: (claimId: string) => Promise<T>,
  enabled: boolean,
  /** Optional: treat a successful response as still-processing and keep
   * polling. Use for endpoints that return a partial payload before all
   * downstream metadata (e.g. per-file process_id) is populated. */
  isPartial?: (payload: T) => boolean,
): AsyncState<T> {
  const claimId = useClaimStore((s) => s.claimId);
  const cached = useClaimStore((s) => s.data[step]) as T | undefined;
  const setData = useClaimStore((s) => s.setData);
  const [state, setState] = useState<AsyncState<T>>({
    loading: false,
    error: null,
    data: cached ?? null,
  });

  useEffect(() => {
    if (!enabled || !claimId) return;
    // If we have a cached payload but the caller says it's still partial
    // (e.g. documents without process_id yet), refetch instead of returning
    // the stale snapshot — otherwise downstream widgets that depend on the
    // missing fields can never recover.
    if (cached && !(isPartial && isPartial(cached))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setState({ loading: !cached, error: null, data: cached ?? null });

    const isProcessing = (p: unknown): boolean =>
      !!p &&
      typeof p === 'object' &&
      (p as { status?: string }).status === 'processing';

    const attempt = (delay: number) => {
      if (cancelled) return;
      fetcher(claimId)
        .then((payload) => {
          if (cancelled) return;
          const partial = isPartial && isPartial(payload);
          if (isProcessing(payload) || partial) {
            if (!isProcessing(payload)) {
              setData(step, payload);
              setState({ loading: false, error: null, data: payload });
            }
            // Backend returned 202, or the response is missing fields the
            // section needs — keep polling, capped at 8s.
            const next = Math.min(delay * 1.5, 8000);
            timer = setTimeout(() => attempt(next), next);
            return;
          }
          setData(step, payload);
          setState({ loading: false, error: null, data: payload });
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const message = err instanceof Error ? err.message : 'Request failed';
          setState({ loading: false, error: message, data: null });
        });
    };

    attempt(2000);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, claimId, step]);

  // Keep state.data in sync with cache when it appears (e.g. populated by
  // another section or after rehydrate).
  useEffect(() => {
    if (cached && !state.data) {
      setState({ loading: false, error: null, data: cached });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cached]);

  return state;
}
