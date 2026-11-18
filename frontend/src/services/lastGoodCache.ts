// Last successful response for each GET request, kept in memory and in IndexedDB
// so a page reload during an outage still has something to show. apiFetch serves
// these when the backend or a live provider fails, and records which data is
// being shown from the saved copy so the app can say so.
import { useSyncExternalStore } from "react";

interface Entry { savedAt: number; data: unknown }
export interface StaleSource { key: string; label: string; savedAt: number }

const DB_NAME = "floodguard-last-good";
const STORE = "responses";
const MAX_AGE_MS = 7 * 24 * 3600 * 1000;

const memory = new Map<string, Entry>();
let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDb(): Promise<IDBDatabase | null> {
  return dbPromise ??= new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
  const db = await openDb();
  if (!db) return undefined;
  return new Promise((resolve) => {
    try {
      const request = run(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

export function saveLastGood(key: string, data: unknown): void {
  const entry = { savedAt: Date.now(), data };
  memory.set(key, entry);
  clearStale(key);
  void withStore("readwrite", (store) => store.put(entry, key));
}

export async function readLastGood(key: string): Promise<Entry | null> {
  const entry = memory.get(key) ?? await withStore<Entry>("readonly", (store) => store.get(key));
  if (!entry || typeof entry.savedAt !== "number") return null;
  if (Date.now() - entry.savedAt > MAX_AGE_MS) {
    memory.delete(key);
    void withStore("readwrite", (store) => store.delete(key));
    return null;
  }
  memory.set(key, entry);
  return entry;
}

// --- Which data is currently shown from a saved copy -------------------------

let stale: StaleSource[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function markStale(key: string, label: string, savedAt: number): void {
  const existing = stale.find((item) => item.key === key);
  if (existing && existing.savedAt === savedAt) return;
  stale = [...stale.filter((item) => item.key !== key), { key, label, savedAt }];
  emit();
}

function clearStale(key: string): void {
  if (!stale.some((item) => item.key === key)) return;
  stale = stale.filter((item) => item.key !== key);
  emit();
}

export function useStaleSources(): StaleSource[] {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    () => stale,
  );
}
