export {};
declare global {
  interface Window {
    electronAPI?: {
      serverUrl: string;
      hide: () => void;
      clearAndHide: () => void;
      ingest: (source: string) => void;
      onClear: (cb: () => void) => void;
      onIngestStatus: (cb: (data: { source: string; state: string; data?: any }) => void) => void;
      setMiniMode: (mini: boolean) => void;
      getSettings: () => Promise<{ online_mode: boolean; offline_model?: string; offline_use_context?: boolean }>;
      updateSettings: (patch: { online_mode?: boolean; offline_model?: string; offline_use_context?: boolean }) => Promise<{ online_mode: boolean; offline_model?: string; offline_use_context?: boolean }>;
    };
  }
}
