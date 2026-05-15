//
// Single-page progressive-journey state. The journey is one route (/journey)
// with eight sections; this store tracks where the user is, which sections are
// "complete", and caches the per-section response data so re-expanding a done
// section doesn't refetch.

import { create } from 'zustand';
import type { AutoSubmitResponse } from '../api/apiClient';

const STORAGE_KEY = 'claimsDemo.claimState.v1';

interface PersistedState {
  claimId: string | null;
  intake: AutoSubmitResponse | null;
  currentStep: number;
  completed: number[];
  // Per-section payload cache. Persisted so collapsed "done" sections render
  // their summary line immediately after a reload, instead of showing blank
  // until the section's hook refetches.
  data?: Record<number, unknown>;
}

function loadPersisted(): PersistedState | null {
  if (typeof window === 'undefined' || !window.sessionStorage) return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedState;
    if (!parsed || typeof parsed.claimId !== 'string') return null;
    return parsed;
  } catch {
    return null;
  }
}

function savePersisted(state: PersistedState | null): void {
  if (typeof window === 'undefined' || !window.sessionStorage) return;
  try {
    if (state === null || state.claimId === null) {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* sessionStorage unavailable / quota — non-fatal */
  }
}

export interface ClaimState {
  claimId: string | null;
  // Set when the user uploaded real files via /claimsdemo/claims/auto-submit.
  // null when the journey was started from the built-in sample claim.
  intake: AutoSubmitResponse | null;
  currentStep: number; // 1..7 while working; 8 means all sections are complete
  completed: ReadonlySet<number>; // sections the user has confirmed via "Next"
  // Per-section data cache (raw payloads from /claimsdemo/...)
  data: Record<number, unknown>;

  setClaimId: (id: string) => void;
  setIntake: (intake: AutoSubmitResponse | null) => void;
  setData: (step: number, payload: unknown) => void;
  clearData: (steps: number[]) => void;
  markComplete: (step: number) => void;
  reopenFrom: (step: number) => void;
  goTo: (step: number) => void;
  reset: () => void;
}

const TOTAL_STEPS = 7;

const persisted = loadPersisted();

function snapshot(s: ClaimState): PersistedState {
  return {
    claimId: s.claimId,
    intake: s.intake,
    currentStep: s.currentStep,
    completed: Array.from(s.completed),
    data: s.data,
  };
}

export const useClaimStore = create<ClaimState>((set, get) => ({
  claimId: persisted?.claimId ?? null,
  intake: persisted?.intake ?? null,
  currentStep: persisted?.currentStep ?? 1,
  completed: new Set<number>(persisted?.completed ?? []),
  data: persisted?.data ?? {},

  setClaimId: (id) => {
    set({ claimId: id });
    savePersisted(snapshot(get()));
  },
  setIntake: (intake) => {
    set({ intake });
    savePersisted(snapshot(get()));
  },
  setData: (step, payload) => {
    set((state) => ({ data: { ...state.data, [step]: payload } }));
    savePersisted(snapshot(get()));
  },
  clearData: (steps) =>
    set((state) => {
      const nextData = { ...state.data };
      for (const step of steps) delete nextData[step];
      const updated = { ...state, data: nextData } as ClaimState;
      savePersisted(snapshot(updated));
      return { data: nextData };
    }),
  markComplete: (step) =>
    set((state) => {
      const next = new Set(state.completed);
      next.add(step);
      const nextStep = step >= TOTAL_STEPS ? TOTAL_STEPS + 1 : step + 1;
      const newCurrent = Math.max(state.currentStep, nextStep);
      const updated = {
        ...state,
        completed: next,
        currentStep: newCurrent,
      } as ClaimState;
      savePersisted(snapshot(updated));
      return { completed: next, currentStep: newCurrent };
    }),
  reopenFrom: (step) =>
    set((state) => {
      const next = new Set<number>();
      for (const completedStep of state.completed) {
        if (completedStep < step) next.add(completedStep);
      }
      const newCurrent = Math.min(state.currentStep, step);
      const updated = {
        ...state,
        completed: next,
        currentStep: newCurrent,
      } as ClaimState;
      savePersisted(snapshot(updated));
      return { completed: next, currentStep: newCurrent };
    }),
  goTo: (step) =>
    set((state) => {
      savePersisted(snapshot({ ...state, currentStep: step } as ClaimState));
      return { currentStep: step };
    }),
  reset: () => {
    savePersisted(null);
    set({
      claimId: null,
      intake: null,
      currentStep: 1,
      completed: new Set<number>(),
      data: {},
    });
  },
}));

export const TOTAL_JOURNEY_STEPS = TOTAL_STEPS;
