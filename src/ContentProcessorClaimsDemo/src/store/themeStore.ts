//
// Tiny theme-mode store with localStorage persistence.
// Default mode is 'light' to match the demo's predominantly white aesthetic.

import { create } from 'zustand';

export type ThemeMode = 'light' | 'dark';

const STORAGE_KEY = 'claimsDemo.themeMode';

function loadMode(): ThemeMode {
  if (typeof window === 'undefined' || !window.localStorage) return 'light';
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'dark' || raw === 'light') return raw;
  } catch {
    /* ignore */
  }
  return 'light';
}

function saveMode(mode: ThemeMode): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

interface ThemeState {
  mode: ThemeMode;
  toggle: () => void;
  setMode: (mode: ThemeMode) => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  mode: loadMode(),
  toggle: () => {
    const next: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
    saveMode(next);
    set({ mode: next });
  },
  setMode: (mode) => {
    saveMode(mode);
    set({ mode });
  },
}));
