/** Global extraction state — survives page navigation within the app. */
"use client";

import { createContext, useContext, useCallback, useRef, useSyncExternalStore } from "react";
import { extractTopics } from "./api";

interface ExtractionState {
  /** doc IDs currently being extracted (single-doc) */
  extractingIds: Set<string>;
  /** course ID if batch extract-all is running */
  extractAllCourseId: string | null;
  /** progress text shown during batch extraction */
  progress: string | null;
  /** error from last extraction */
  error: string | null;
}

interface ExtractionActions {
  extractOne: (courseId: string, docId: string, onDone: () => void) => void;
  extractAll: (courseId: string, docs: { id: string; title: string }[], onDone: () => void) => void;
  isExtracting: (docId: string) => boolean;
  isExtractingAll: (courseId: string) => boolean;
}

type Store = ExtractionState & ExtractionActions;

// Module-level store — survives component unmount/remount
let state: ExtractionState = {
  extractingIds: new Set(),
  extractAllCourseId: null,
  progress: null,
  error: null,
};

const listeners = new Set<() => void>();

function getSnapshot(): ExtractionState {
  return state;
}

function emit(partial: Partial<ExtractionState>) {
  state = { ...state, ...partial };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function doExtractOne(courseId: string, docId: string, onDone: () => void) {
  const next = new Set(state.extractingIds);
  next.add(docId);
  emit({ extractingIds: next, error: null });
  try {
    await extractTopics(courseId, docId);
  } catch (err) {
    emit({ error: err instanceof Error ? err.message : "Extraction failed" });
  } finally {
    const updated = new Set(state.extractingIds);
    updated.delete(docId);
    emit({ extractingIds: updated });
    onDone();
  }
}

async function doExtractAll(
  courseId: string,
  docs: { id: string; title: string }[],
  onDone: () => void,
) {
  emit({ extractAllCourseId: courseId, error: null, progress: null });
  let completed = 0;

  emit({ progress: `Extracting 0/${docs.length}...` });

  const promises = docs.map(async (doc) => {
    try {
      await extractTopics(courseId, doc.id);
    } catch (err) {
      emit({ error: err instanceof Error ? err.message : `Extraction failed: ${doc.title}` });
    } finally {
      completed++;
      emit({ progress: `Extracting ${completed}/${docs.length}...` });
    }
  });

  await Promise.all(promises);

  emit({ extractAllCourseId: null, progress: null });
  onDone();
}

const ExtractionContext = createContext<Store | null>(null);

export function ExtractionProvider({ children }: { children: React.ReactNode }) {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const extractOne = useCallback((courseId: string, docId: string, onDone: () => void) => {
    doExtractOne(courseId, docId, onDone);
  }, []);

  const extractAll = useCallback(
    (courseId: string, docs: { id: string; title: string }[], onDone: () => void) => {
      doExtractAll(courseId, docs, onDone);
    },
    [],
  );

  const isExtracting = useCallback(
    (docId: string) => snap.extractingIds.has(docId),
    [snap.extractingIds],
  );

  const isExtractingAll = useCallback(
    (courseId: string) => snap.extractAllCourseId === courseId,
    [snap.extractAllCourseId],
  );

  const value: Store = {
    ...snap,
    extractOne,
    extractAll,
    isExtracting,
    isExtractingAll,
  };

  return (
    <ExtractionContext.Provider value={value}>{children}</ExtractionContext.Provider>
  );
}

export function useExtraction() {
  const ctx = useContext(ExtractionContext);
  if (!ctx) throw new Error("useExtraction must be used within ExtractionProvider");
  return ctx;
}
