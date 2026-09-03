'use client'
import { useEffect, useRef, useCallback, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { RootState } from '@/store/store';
import { PresentationGenerationApi } from '../../services/api/presentation-generation';
import { addToHistory } from '@/store/slices/undoRedoSlice';
import type { PresentationData } from '@/store/slices/presentationGeneration';
import type { Slide } from '../../types/slide';
import type { AutoSaveSnapshot } from '../utils/autoSaveDiff';
import {
    createAutoSaveSnapshot,
    fingerprintValue,
    getAutoSaveChanges,
} from '../utils/autoSaveDiff';

interface UseAutoSaveOptions {
    debounceMs?: number;
    enabled?: boolean;
}

export const useAutoSave = ({
    debounceMs = 1000,
    enabled = true,
}: UseAutoSaveOptions = {}) => {
   
    const dispatch = useDispatch();
    const { presentationData, isStreaming, isLoading, isLayoutLoading } = useSelector(
        (state: RootState) => state.presentationGeneration
    );

    const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const acknowledgedDataRef = useRef<AutoSaveSnapshot | null>(null);
    const latestDataRef = useRef<PresentationData | null>(presentationData);
    const autoSavePausedRef = useRef(true);
    const wasAutoSavePausedRef = useRef(false);
    const pendingSaveRef = useRef(false);
    const saveLatestRef = useRef<() => Promise<void>>(async () => undefined);
    const isSavingRef = useRef(false);
    // Tracks whichever saveLatest() call is currently running, whether it was
    // started by the debounce timer, its own trailing-pending-change retry,
    // or an explicit flush() - see the comment on flushSave below for why a
    // single tracked promise is what makes flush() correct rather than a
    // guess.
    const activeSaveRef = useRef<Promise<void> | null>(null);
    const [isSaving, setIsSaving] = useState<boolean>(false);

    const autoSavePaused =
        !enabled || isStreaming || isLoading || isLayoutLoading;

    useEffect(() => {
        latestDataRef.current = presentationData;
        autoSavePausedRef.current = autoSavePaused;
    }, [presentationData, autoSavePaused]);

    const saveLatest = useCallback(async () => {
        const data = latestDataRef.current;
        if (!data || autoSavePausedRef.current) return;
        if (isSavingRef.current) {
            pendingSaveRef.current = true;
            return;
        }

        const acknowledged = acknowledgedDataRef.current;
        if (!acknowledged || acknowledged.presentationId !== data.id) {
            acknowledgedDataRef.current = createAutoSaveSnapshot(data);
            return;
        }

        const changes = getAutoSaveChanges(acknowledged, data);
        if (
            !changes.structuralChange &&
            !changes.metadataChanged &&
            changes.changedSlides.length === 0
        ) return;

        try {
            isSavingRef.current = true;
            setIsSaving(true);
            console.log('🔄 Auto-saving presentation data...');

            if (changes.structuralChange) {
                // Serialize once after the debounce window. The API accepts the
                // serialized body and avoids a second whole-deck stringify.
                await PresentationGenerationApi.updatePresentationContent(
                    JSON.stringify(data)
                );
                acknowledgedDataRef.current = createAutoSaveSnapshot(data);
            } else {
                let firstError: unknown = null;
                const nextAcknowledged: AutoSaveSnapshot = {
                    ...acknowledged,
                    slideFingerprints: { ...acknowledged.slideFingerprints },
                };

                if (changes.metadataChanged) {
                    try {
                        await PresentationGenerationApi.updatePresentationContent({
                            id: data.id,
                            title: data.title,
                            theme: data.theme,
                        });
                        nextAcknowledged.metadataFingerprint = fingerprintValue({
                            title: data.title,
                            theme: data.theme,
                        });
                        acknowledgedDataRef.current = nextAcknowledged;
                    } catch (error) {
                        firstError = error;
                    }
                }

                for (const slide of changes.changedSlides) {
                    try {
                        await PresentationGenerationApi.updatePresentationSlide(
                            slide as Slide
                        );
                        nextAcknowledged.slideFingerprints[slide.id] =
                            fingerprintValue(slide);
                        acknowledgedDataRef.current = nextAcknowledged;
                    } catch (error) {
                        firstError ??= error;
                    }
                }

                if (firstError) throw firstError;
                acknowledgedDataRef.current = createAutoSaveSnapshot(data);
            }

            console.log('✅ Auto-save successful');
        } catch (error) {
            console.error('❌ Auto-save failed:', error);
        } finally {
            isSavingRef.current = false;
            setIsSaving(false);

            if (pendingSaveRef.current && !autoSavePausedRef.current) {
                pendingSaveRef.current = false;
                saveTimeoutRef.current = setTimeout(() => {
                    void triggerSave();
                }, 250);
            }
        }
    }, []);

    useEffect(() => {
        saveLatestRef.current = saveLatest;
    }, [saveLatest]);

    // Every actual invocation of saveLatest - whether started by the debounce
    // timer, its own trailing-pending-change retry above, or an explicit
    // flush - goes through this single wrapper, so activeSaveRef always
    // reflects "the save that is genuinely running right now" regardless of
    // which of those three triggered it.
    const triggerSave = useCallback(() => {
        const promise = saveLatestRef.current().finally(() => {
            if (activeSaveRef.current === promise) {
                activeSaveRef.current = null;
            }
        });
        activeSaveRef.current = promise;
        return promise;
    }, []);

    /**
     * Forces any pending or in-flight save to complete immediately, bypassing
     * the debounce window. Exporting reads the presentation straight from the
     * database (see PdfMakerPage.tsx), not from the editor's live Redux
     * state, so an edit made just before clicking Export could otherwise ship
     * in the file the debounce hadn't saved yet - a silent stale-export bug.
     * The trailing triggerSave() call is what makes this correct rather than
     * a race: after cancelling the timer and waiting out anything already in
     * flight, it re-runs the same diff-and-save-if-needed logic saveLatest
     * always uses against the latest data, so it costs nothing when there is
     * genuinely nothing left to save (the diff check inside saveLatest no-ops
     * immediately) and still catches a change that arrived while the earlier
     * save was running.
     */
    const flushSave = useCallback(async () => {
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
            saveTimeoutRef.current = null;
        }
        pendingSaveRef.current = false;
        if (activeSaveRef.current) {
            await activeSaveRef.current;
        }
        await triggerSave();
    }, [triggerSave]);

    // Effect to trigger auto-save when presentation data changes
    useEffect(() => {
        if (!presentationData) return;

        if (autoSavePaused) {
            // Changes arriving while editing is paused are server-originated
            // hydration/streaming updates and are already persisted.
            wasAutoSavePausedRef.current = true;
            pendingSaveRef.current = false;
            if (!isSavingRef.current) {
                acknowledgedDataRef.current = createAutoSaveSnapshot(presentationData);
            }
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
                saveTimeoutRef.current = null;
            }
            return;
        }

        // History is updated immediately from immutable Redux snapshots. It is
        // independent from network debounce, so even the first edit can undo.
        dispatch(addToHistory({
            slides: presentationData.slides,
            actionType: "AUTO_SAVE"
        }));

        if (wasAutoSavePausedRef.current) {
            // The final streaming/loading payload can land in the same render
            // that flips editing back on. Treat that first active snapshot as
            // already persisted instead of issuing slide updates for it.
            wasAutoSavePausedRef.current = false;
            acknowledgedDataRef.current = createAutoSaveSnapshot(presentationData);
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
                saveTimeoutRef.current = null;
            }
            return;
        }

        if (
            !acknowledgedDataRef.current ||
            acknowledgedDataRef.current.presentationId !== presentationData.id
        ) {
            acknowledgedDataRef.current = createAutoSaveSnapshot(presentationData);
            return;
        }
        
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
        }
        saveTimeoutRef.current = setTimeout(() => {
            void triggerSave();
        }, debounceMs);

        // Cleanup timeout on unmount
        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
            }
        };
    }, [
        presentationData,
        autoSavePaused,
        debounceMs,
        dispatch,
        triggerSave,
    ]);

    return {
        isSaving,
        flushSave,
    };
};
