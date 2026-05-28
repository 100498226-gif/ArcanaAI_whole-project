import { useState, useEffect, useRef, useCallback } from 'react';
import { Sparkles, HardDrive, ChevronDown, Check, Clock, GripHorizontal, GripVertical, Minimize2, Maximize2 } from 'lucide-react';
import * as Switch from '@radix-ui/react-switch';
import * as Select from '@radix-ui/react-select';
import { marked } from 'marked';
import mermaid from 'mermaid';
import arcanaLogo from '../imports/output-onlinepngtools.png';
import backgroundPattern from '../imports/image-3.png';

const SERVER = window.electronAPI?.serverUrl ?? 'http://localhost:8000';

interface Message {
  id: number;
  question: string;
  answer: string;
  timestamp: Date;
}

interface LlmModel {
  name: string;
  size_gb: number;
}

const FALLBACK_MODELS: LlmModel[] = [
  { name: 'qwen2.5:3b',  size_gb: 2.0 },
  { name: 'llama3.2:3b', size_gb: 2.0 },
  { name: 'mistral:7b',  size_gb: 4.1 },
  { name: 'phi3:mini',   size_gb: 2.2 },
];

interface Badge {
  text: string;
  state: '' | 'ready' | 'loading' | 'error';
}

function BadgePill({ state, text }: Badge) {
  const cls =
    state === 'ready'   ? 'bg-green-50 text-green-700 border-green-200' :
    state === 'loading' ? 'bg-teal-50 text-teal-600 border-teal-200 animate-pulse' :
    state === 'error'   ? 'bg-red-50 text-red-600 border-red-200' :
                          'bg-gray-100 text-gray-400 border-gray-200';
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border whitespace-nowrap min-w-[60px] text-center ${cls}`}>
      {text}
    </span>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const [isOnline, setIsOnline] = useState(true);
  const [chunks, setChunks] = useState(0);
  const [healthOk, setHealthOk] = useState(false);
  const [currentAnswer, setCurrentAnswer] = useState('');
  const [history, setHistory] = useState<Message[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [currentQuestion, setCurrentQuestion] = useState('');

  // Model panel
  const [llmPanelMode, setLlmPanelMode] = useState<'online' | 'offline'>('online');
  const [llmModels, setLlmModels] = useState<LlmModel[]>(FALLBACK_MODELS);
  const [selectedLlm, setSelectedLlm] = useState('gemini-2.5-flash-lite');
  const [llmBadge, setLlmBadge] = useState<Badge>({ text: '✓ Ready', state: 'ready' });
  const [visionBadge, setVisionBadge] = useState<Badge>({ text: '—', state: '' });
  const [llmLoading, setLlmLoading] = useState(false);
  const [visionLoading, setVisionLoading] = useState(false);
  const [offlineUseContext, setOfflineUseContext] = useState(true);
  const [goOnlineDialog, setGoOnlineDialog] = useState(false);

  const [historialHeight, setHistorialHeight] = useState(96);
  const [sidebarWidth, setSidebarWidth] = useState(180);
  const [isMini, setIsMini] = useState(false);
  const [renderedAnswer, setRenderedAnswer] = useState('');

  const controllerRef = useRef<AbortController | null>(null);
  const convHistoryRef = useRef<Array<{ role: string; content: string }>>([]);
  const isOnlineRef = useRef(true);
  const pendingQuestionRef = useRef('');
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);
  const sidebarDragRef = useRef<{ startX: number; startW: number } | null>(null);

  // ── Mode management ─────────────────────────────────────────────────────────
  const applyMode = useCallback((online: boolean) => {
    isOnlineRef.current = online;
    setIsOnline(online);
    if (online) {
      setLlmPanelMode('online');
      setSelectedLlm('gemini-2.5-flash-lite');
      setLlmBadge({ text: '✓ Ready', state: 'ready' });
    } else {
      setLlmPanelMode('offline');
      refreshModels();
    }
  }, []);

  // ── Refresh offline models ───────────────────────────────────────────────────
  const refreshModels = useCallback(async () => {
    try {
      const d = await fetch(`${SERVER}/offline/models`).then(r => r.json());
      if (d.llm_models?.length > 0) {
        setLlmModels(d.llm_models);
        const current = d.llm_models.find((m: LlmModel) => m.name === d.current_model);
        setSelectedLlm(d.current_model ?? d.llm_models[0].name);
        setLlmBadge(current?.loaded
          ? { text: '✓ Ready', state: 'ready' }
          : { text: '—', state: '' });
      }
      // if empty list, keep existing fallback models already in state
      if (d.vision_model?.loaded) setVisionBadge({ text: '✓ Ready', state: 'ready' });
      else if (!d.vision_model?.available) setVisionBadge({ text: 'Not found', state: 'error' });
      else setVisionBadge({ text: '—', state: '' });
    } catch {
      // Ollama unreachable — keep FALLBACK_MODELS already in state; don't clear
    }
  }, []);

  // ── Health ───────────────────────────────────────────────────────────────────
  const fetchHealth = useCallback(async () => {
    try {
      const d = await fetch(`${SERVER}/health/`).then(r => r.json());
      setHealthOk(d.status === 'ok');
      setChunks(d.total_chunks ?? 0);
      if (d.online_mode !== undefined && d.online_mode !== isOnlineRef.current) {
        applyMode(d.online_mode);
      }
      if (!isOnlineRef.current) {
        if (d.llm_model_loaded) setLlmBadge({ text: '✓ Ready', state: 'ready' });
        if (d.vision_model_loaded) setVisionBadge({ text: '✓ Ready', state: 'ready' });
      }
    } catch {
      setHealthOk(false);
    }
  }, [applyMode]);

  // ── Settings ─────────────────────────────────────────────────────────────────
  const loadSettings = useCallback(async () => {
    try {
      const s = await window.electronAPI!.getSettings();
      applyMode(s.online_mode ?? true);
      setOfflineUseContext(s.offline_use_context !== false);
    } catch {
      applyMode(true);
    }
  }, [applyMode]);

  // ── Toggle KB context (offline only) ─────────────────────────────────────────
  const toggleKbContext = useCallback(async () => {
    const next = !offlineUseContext;
    setOfflineUseContext(next);
    try {
      await window.electronAPI!.updateSettings({ offline_use_context: next });
    } catch {}
  }, [offlineUseContext]);

  // ── Toggle mode ───────────────────────────────────────────────────────────────
  const toggleMode = useCallback(async () => {
    const newOnline = !isOnlineRef.current;
    try {
      const s = await window.electronAPI!.updateSettings({ online_mode: newOnline });
      applyMode(s.online_mode ?? newOnline);
    } catch {
      applyMode(newOnline);
    }
  }, [applyMode]);

  // ── Load LLM model ────────────────────────────────────────────────────────────
  const loadLlmModel = useCallback(async () => {
    if (!selectedLlm || llmLoading) return;
    setLlmLoading(true);
    setLlmBadge({ text: 'Loading… 0s', state: 'loading' });
    try {
      const resp = await fetch(`${SERVER}/offline/load-model`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selectedLlm }),
      });
      const reader = resp.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop()!;
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === 'pull')      setLlmBadge({ text: ev.status, state: 'loading' });
            else if (ev.type === 'loading') setLlmBadge({ text: `Loading… ${ev.elapsed}s`, state: 'loading' });
            else if (ev.type === 'ready') { setLlmBadge({ text: '✓ Ready', state: 'ready' }); return; }
            else if (ev.type === 'error') { setLlmBadge({ text: 'Failed', state: 'error' }); return; }
          } catch {}
        }
      }
      setLlmBadge({ text: '✓ Ready', state: 'ready' });
    } catch {
      setLlmBadge({ text: 'Failed', state: 'error' });
    } finally {
      setLlmLoading(false);
    }
  }, [selectedLlm, llmLoading]);

  // ── Load Vision model ─────────────────────────────────────────────────────────
  const loadVisionModel = useCallback(async () => {
    if (visionLoading) return;
    setVisionLoading(true);
    setVisionBadge({ text: 'Loading… 0s', state: 'loading' });
    try {
      const resp = await fetch(`${SERVER}/offline/load-vision-model`, { method: 'POST' });
      const reader = resp.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop()!;
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === 'loading') setVisionBadge({ text: `Loading… ${ev.elapsed}s`, state: 'loading' });
            else if (ev.type === 'ready') { setVisionBadge({ text: '✓ Ready', state: 'ready' }); return; }
            else if (ev.type === 'error') { setVisionBadge({ text: 'Failed', state: 'error' }); return; }
          } catch {}
        }
      }
      setVisionBadge({ text: '✓ Ready', state: 'ready' });
    } catch {
      setVisionBadge({ text: 'Failed', state: 'error' });
    } finally {
      setVisionLoading(false);
    }
  }, [visionLoading]);

  // ── Ask question ──────────────────────────────────────────────────────────────
  const handleAsk = useCallback(async () => {
    const q = query.trim();
    if (!q || isLoading) return;

    if (!isOnlineRef.current && llmBadge.state !== 'ready') {
      setStatusMsg('Load the LLM model first');
      return;
    }

    if (controllerRef.current) controllerRef.current.abort();
    controllerRef.current = new AbortController();

    setIsLoading(true);
    setCurrentAnswer('');
    setCurrentQuestion(q);
    setSelectedHistoryId(null);
    setStatusMsg('Thinking…');
    setQuery('');

    let fullAnswer = '';

    try {
      const resp = await fetch(`${SERVER}/query/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q,
          history: convHistoryRef.current.slice(-10),
        }),
        signal: controllerRef.current.signal,
      });

      if (!resp.ok) { setStatusMsg(`Error: HTTP ${resp.status}`); return; }

      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = '', lastEvent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop()!;

        for (const line of lines) {
          if (line.startsWith('event:')) {
            lastEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            try {
              const payload = JSON.parse(line.slice(5).trim());
              if (lastEvent === 'chunk' && payload.text) {
                fullAnswer += payload.text;
                setCurrentAnswer(fullAnswer);
                setStatusMsg('Streaming…');
              } else if (lastEvent === 'error' && payload.message) {
                setStatusMsg(`Error: ${payload.message}`);
              } else if (lastEvent === 'needs_online') {
                pendingQuestionRef.current = payload.question || q;
                setGoOnlineDialog(true);
                return;
              } else if (lastEvent === 'done') {
                const src = payload.chunks_used > 0
                  ? `${payload.chunks_used} sources`
                  : 'general knowledge';
                setStatusMsg(`Done · ${src}`);
                if (fullAnswer) {
                  const newMsg: Message = {
                    id: Date.now(),
                    question: q,
                    answer: fullAnswer,
                    timestamp: new Date(),
                  };
                  setHistory(prev => [...prev, newMsg]);
                  convHistoryRef.current.push({ role: 'user', content: q });
                  convHistoryRef.current.push({ role: 'assistant', content: fullAnswer });
                  if (convHistoryRef.current.length > 10)
                    convHistoryRef.current = convHistoryRef.current.slice(-10);
                }
              }
            } catch {}
          }
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') setStatusMsg(`Error: ${e?.message}`);
      else setStatusMsg('');
    } finally {
      setIsLoading(false);
      controllerRef.current = null;
    }
  }, [query, isLoading, llmBadge.state]);

  // ── Go-online dialog handlers ─────────────────────────────────────────────────
  const handleGoOnlineYes = useCallback(async () => {
    setGoOnlineDialog(false);
    const pq = pendingQuestionRef.current;
    pendingQuestionRef.current = '';
    if (!pq) return;
    try {
      const s = await window.electronAPI!.updateSettings({ online_mode: true });
      applyMode(s.online_mode ?? true);
    } catch { applyMode(true); }
    // Re-ask as online — set query and fire after state settles
    setQuery(pq);
    setIsLoading(false);
    // Use setTimeout so applyMode's state flush completes first
    setTimeout(() => {
      isOnlineRef.current = true;
      setCurrentAnswer('');
      setStatusMsg('');
    }, 0);
  }, [applyMode]);

  const handleGoOnlineNo = useCallback(() => {
    setGoOnlineDialog(false);
    const pq = pendingQuestionRef.current;
    pendingQuestionRef.current = '';
    const msg = 'The answer to your question could not be found. We are happy you remained private here with us.';
    setCurrentAnswer(msg);
    setStatusMsg('Done — no results');
    if (pq) {
      const newMsg = { id: Date.now(), question: pq, answer: msg, timestamp: new Date() };
      setHistory(prev => [...prev, newMsg]);
      convHistoryRef.current.push({ role: 'user', content: pq });
      convHistoryRef.current.push({ role: 'assistant', content: msg });
      if (convHistoryRef.current.length > 10) convHistoryRef.current = convHistoryRef.current.slice(-10);
    }
  }, []);

  // ── Cancel ────────────────────────────────────────────────────────────────────
  const handleCancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setIsLoading(false);
    setStatusMsg('');
  }, []);

  // ── Clear ─────────────────────────────────────────────────────────────────────
  const handleClear = useCallback(() => {
    handleCancel();
    setQuery('');
    setCurrentAnswer('');
    setStatusMsg('');
    setHistory([]);
    setSelectedHistoryId(null);
    convHistoryRef.current = [];
  }, [handleCancel]);

  // ── History click ─────────────────────────────────────────────────────────────
  const handleHistoryClick = useCallback((message: Message) => {
    setSelectedHistoryId(message.id);
    setCurrentAnswer(message.answer);
  }, []);

  // ── Ingest ────────────────────────────────────────────────────────────────────
  const triggerIngest = useCallback((source: string) => {
    window.electronAPI?.ingest(source);
  }, []);

  // ── Mini mode toggle ──────────────────────────────────────────────────────────
  const toggleMini = useCallback(() => {
    const next = !isMini;
    setIsMini(next);
    window.electronAPI?.setMiniMode(next);
  }, [isMini]);

  // ── Historial drag-to-resize ──────────────────────────────────────────────────
  const onDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startH: historialHeight };

    const onMove = (me: MouseEvent) => {
      if (!dragRef.current) return;
      const delta = dragRef.current.startY - me.clientY;
      setHistorialHeight(Math.max(56, Math.min(320, dragRef.current.startH + delta)));
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [historialHeight]);

  // ── Sidebar drag-to-resize ────────────────────────────────────────────────────
  const onSidebarDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    sidebarDragRef.current = { startX: e.clientX, startW: sidebarWidth };
    const onMove = (me: MouseEvent) => {
      if (!sidebarDragRef.current) return;
      const delta = sidebarDragRef.current.startX - me.clientX; // drag left = wider
      setSidebarWidth(Math.max(140, Math.min(320, sidebarDragRef.current.startW + delta)));
    };
    const onUp = () => {
      sidebarDragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [sidebarWidth]);

  // ── Key handler ───────────────────────────────────────────────────────────────
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAsk(); }
  }, [handleAsk]);

  // ── Mermaid init ──────────────────────────────────────────────────────────────
  useEffect(() => {
    mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
  }, []);

  // ── Render answer: mermaid blocks → SVG, rest → marked HTML ──────────────────
  useEffect(() => {
    if (!currentAnswer) { setRenderedAnswer(''); return; }
    let cancelled = false;
    (async () => {
      const parts = currentAnswer.split(/(```mermaid[\s\S]*?```)/g);
      const htmlParts = await Promise.all(parts.map(async (part, i) => {
        const mm = part.match(/^```mermaid\n?([\s\S]*?)```$/);
        if (mm) {
          try {
            const { svg } = await mermaid.render(`mermaid-${Date.now()}-${i}`, mm[1].trim());
            return `<div class="mermaid-diagram">${svg}</div>`;
          } catch {
            return `<pre class="mermaid-error">${mm[1]}</pre>`;
          }
        }
        return marked.parse(part) as string;
      }));
      if (!cancelled) setRenderedAnswer(htmlParts.join(''));
    })();
    return () => { cancelled = true; };
  }, [currentAnswer]);

  // ── Mount ─────────────────────────────────────────────────────────────────────
  useEffect(() => {
    loadSettings().then(() => fetchHealth());
    window.electronAPI?.onClear(() => handleClear());
    window.electronAPI?.onIngestStatus(({ source, state, data }) => {
      if (state === 'done') {
        const info = data?.embedded != null ? `${data.embedded} new chunks` : 'done';
        setStatusMsg(`${source} — ${info}`);
        setTimeout(() => fetchHealth(), 2000);
      } else if (state === 'error') {
        setStatusMsg(`${source} failed`);
      }
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sidebar file lists (static placeholders) ──────────────────────────────────

  // ── Model warning (offline + not loaded) ─────────────────────────────────────
  const showModelWarning = !isOnline && llmBadge.state !== 'ready';

  return (
    <div className="drag-region size-full flex bg-white relative overflow-hidden">
      {/* Background Image */}
      <div
        className="absolute inset-0 opacity-85"
        style={{
          backgroundImage: `url(${backgroundPattern})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
        }}
      />

      {/* Drag indicator — visible in the top gap between window edge and panels */}
      <div className="absolute top-1.5 left-1/2 -translate-x-1/2 z-50 flex gap-0.5 pointer-events-none">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="w-1 h-1 rounded-full bg-white/50" />
        ))}
      </div>

      {/* Main Content */}
      <div className={`no-drag-region flex-1 flex flex-col relative z-10 backdrop-blur-sm overflow-hidden transition-colors ${
        isMini ? 'm-4 rounded-2xl' : 'm-4 mr-0 rounded-l-2xl'
      } ${isOnline ? 'bg-white/60' : 'bg-gray-800/70'}`}>

        {/* Header */}
        <div className={`border-b transition-colors ${
          isMini ? 'px-2 py-2' : 'px-6 py-4'
        } ${isOnline ? 'border-gray-200 bg-white/40' : 'border-gray-600 bg-gray-700/60'}`}>
          <div className={`flex items-center ${isMini ? 'gap-1' : 'gap-2'}`}>
            <button
              onClick={toggleMini}
              title={isMini ? 'Restore full view' : 'Mini mode'}
              className={`p-1 rounded transition-colors flex-shrink-0 ${
                isOnline ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-100' : 'text-gray-500 hover:text-gray-300 hover:bg-gray-600'
              }`}
            >
              {isMini ? <Maximize2 className="w-3.5 h-3.5" /> : <Minimize2 className="w-4 h-4" />}
            </button>
            <img src={arcanaLogo} alt="Arcana" className={isMini ? 'w-4 h-4 flex-shrink-0' : 'w-6 h-6 flex-shrink-0'} />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Pregunta a Arcana..."
              className={`flex-1 min-w-0 border rounded focus:outline-none transition-colors ${
                isMini ? 'px-2 py-1 text-xs' : 'px-3 py-2 text-sm'
              } ${
                isOnline
                  ? 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-400 focus:border-teal-500'
                  : 'border-gray-600 bg-gray-700 text-gray-200 placeholder:text-gray-500 focus:border-gray-500'
              }`}
            />
            {(currentAnswer || history.length > 0) && (
              <button
                onClick={handleClear}
                className={`flex-shrink-0 transition-colors ${
                  isMini ? 'px-1.5 py-1 text-xs' : 'px-4 py-2 text-sm'
                } ${isOnline ? 'text-gray-600 hover:text-gray-800' : 'text-gray-400 hover:text-gray-200'}`}
              >
                {isMini ? '✕' : 'Clear'}
              </button>
            )}
            {isLoading ? (
              <button
                onClick={handleCancel}
                className={`flex-shrink-0 rounded border transition-colors ${
                  isMini ? 'px-2 py-1 text-xs' : 'px-4 py-2 text-sm'
                } ${
                  isOnline
                    ? 'text-red-600 border-red-200 bg-red-50 hover:bg-red-100'
                    : 'text-red-400 border-red-800 bg-red-900/40 hover:bg-red-900/60'
                }`}
              >
                {isMini ? '✕' : 'Cancel'}
              </button>
            ) : (
              <button
                onClick={handleAsk}
                disabled={!query.trim()}
                className={`flex-shrink-0 text-white rounded font-medium transition-colors disabled:opacity-40 disabled:cursor-default ${
                  isMini ? 'px-2.5 py-1 text-xs' : 'px-6 py-2'
                } ${isOnline ? 'bg-teal-500 hover:bg-teal-600' : 'bg-gray-600 hover:bg-gray-500'}`}
              >
                ASK
              </button>
            )}
          </div>
        </div>

        {!isMini && (<>
        {/* Online Toggle */}
        <div className={`px-6 py-3 border-b transition-colors ${
          isOnline ? 'border-gray-200 bg-white/40' : 'border-gray-600 bg-gray-700/60'
        }`}>
          <div className="flex items-center gap-2">
            <Switch.Root
              checked={isOnline}
              onCheckedChange={toggleMode}
              className="w-11 h-6 bg-gray-400 rounded-full relative data-[state=checked]:bg-teal-500 transition-colors outline-none cursor-pointer"
            >
              <Switch.Thumb className="block w-5 h-5 bg-white rounded-full transition-transform translate-x-0.5 will-change-transform data-[state=checked]:translate-x-[22px]" />
            </Switch.Root>
            <span className={`text-sm font-medium uppercase transition-colors ${
              isOnline ? 'text-teal-600' : 'text-gray-300'
            }`}>
              {isOnline ? 'ONLINE' : 'OFFLINE'}
            </span>
            {!isOnline && (
              <button
                onClick={toggleKbContext}
                title="Include knowledge base context in offline queries"
                className="ml-auto flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-gray-400 hover:text-gray-300 transition-colors"
              >
                <span className={`relative w-7 h-4 rounded-full transition-colors ${offlineUseContext ? 'bg-teal-500' : 'bg-gray-600'}`}>
                  <span className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-all ${offlineUseContext ? 'left-3.5' : 'left-0.5'}`} />
                </span>
                Context {offlineUseContext ? 'ON' : 'OFF'}
              </button>
            )}
          </div>
        </div>

        {/* Model Panel */}
        <div className={`px-6 py-3 border-b flex flex-col gap-2 transition-colors ${
          isOnline ? 'border-gray-200 bg-white/40' : 'border-gray-600 bg-gray-700/60'
        }`}>
          {/* LLM row */}
          <div className="flex items-center gap-2">
            <span className={`text-xs font-bold uppercase w-12 flex-shrink-0 ${isOnline ? 'text-gray-400' : 'text-gray-500'}`}>LLM</span>
            <Select.Root value={selectedLlm} onValueChange={setSelectedLlm}>
              <Select.Trigger
                aria-label="Select LLM model"
                className={`flex-1 flex items-center justify-between gap-2 text-xs rounded-full px-3 py-1 border outline-none transition-colors ${
                  isOnline
                    ? 'bg-white border-gray-200 text-gray-700 focus:border-teal-400'
                    : 'bg-gray-700 border-gray-600 text-gray-200 focus:border-gray-400'
                }`}
              >
                <Select.Value placeholder={llmPanelMode === 'offline' ? 'No models available' : 'Select model'} />
                <Select.Icon>
                  <ChevronDown className="w-3 h-3 opacity-60" />
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Content
                  position="popper"
                  side="bottom"
                  sideOffset={4}
                  className={`z-50 overflow-hidden rounded-xl border shadow-lg min-w-[var(--radix-select-trigger-width)] ${
                    isOnline
                      ? 'bg-white border-gray-200 text-gray-700'
                      : 'bg-gray-700 border-gray-600 text-gray-200'
                  }`}
                >
                  <Select.Viewport className="p-1">
                    {llmPanelMode === 'online'
                      ? ([
                          ['gemini-2.5-flash-lite', 'Gemini-2.5-Flash-Lite'],
                          ['claude-opus-4.7',       'Claude Opus 4.7'],
                          ['openai-gpt-5.5',        'OpenAI GPT-5.5'],
                        ] as const).map(([v, l]) => (
                          <Select.Item
                            key={v}
                            value={v}
                            className={`relative text-xs pl-7 pr-3 py-1.5 rounded-lg cursor-pointer outline-none ${
                              isOnline
                                ? 'data-[highlighted]:bg-teal-50 data-[state=checked]:font-medium'
                                : 'data-[highlighted]:bg-gray-600 data-[state=checked]:font-medium'
                            }`}
                          >
                            <Select.ItemText>{l}</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 top-1/2 -translate-y-1/2">
                              <Check className="w-3 h-3" />
                            </Select.ItemIndicator>
                          </Select.Item>
                        ))
                      : llmModels.map(m => (
                          <Select.Item
                            key={m.name}
                            value={m.name}
                            className="relative text-xs pl-7 pr-3 py-1.5 rounded-lg cursor-pointer outline-none data-[highlighted]:bg-gray-600 data-[state=checked]:font-medium"
                          >
                            <Select.ItemText>{m.name} ({m.size_gb} GB)</Select.ItemText>
                            <Select.ItemIndicator className="absolute left-2 top-1/2 -translate-y-1/2">
                              <Check className="w-3 h-3" />
                            </Select.ItemIndicator>
                          </Select.Item>
                        ))
                    }
                  </Select.Viewport>
                </Select.Content>
              </Select.Portal>
            </Select.Root>
            {llmPanelMode === 'offline' && (
              <button
                onClick={loadLlmModel}
                disabled={llmLoading}
                className="text-xs px-3 py-1 rounded-full border bg-gray-100 border-gray-300 text-gray-600 hover:border-teal-400 transition-colors disabled:opacity-50 flex-shrink-0"
              >
                Load
              </button>
            )}
            <BadgePill {...llmBadge} />
          </div>
          {/* Vision row */}
          <div className="flex items-center gap-2">
            <span className={`text-xs font-bold uppercase w-12 flex-shrink-0 ${isOnline ? 'text-gray-400' : 'text-gray-500'}`}>Vision</span>
            <span className={`flex-1 text-xs font-mono ${isOnline ? 'text-gray-500' : 'text-gray-400'}`}>
              granite-vision-3.2-2b
            </span>
            <button
              onClick={loadVisionModel}
              disabled={visionLoading}
              className="text-xs px-3 py-1 rounded-full border bg-gray-100 border-gray-300 text-gray-600 hover:border-teal-400 transition-colors disabled:opacity-50 flex-shrink-0"
            >
              Load
            </button>
            <BadgePill {...visionBadge} />
          </div>
        </div>
        </>)}

        {/* Chat Area */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Current Answer */}
          <div className={`flex-1 px-6 py-4 overflow-auto transition-colors ${
            isOnline ? 'bg-white/40' : 'bg-gray-700/60'
          }`}>
            <div className="mb-2">
              <div className={`inline-flex items-center gap-2 px-3 py-1 border rounded-full transition-colors ${
                isOnline ? 'bg-teal-50 border-teal-200' : 'bg-gray-600/60 border-gray-500'
              }`}>
                <div className={`w-2 h-2 rounded-full ${isLoading ? 'animate-pulse' : ''} ${
                  isOnline ? 'bg-teal-500' : 'bg-gray-400'
                }`} />
                <span className={`text-xs font-medium transition-colors ${
                  isOnline ? 'text-teal-700' : 'text-gray-300'
                }`}>
                  {statusMsg || 'Respuesta Actual'}
                </span>
              </div>
            </div>
            {currentAnswer ? (
              isOnline ? (
                <div
                  className="prose prose-sm max-w-none text-gray-800 [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:rounded [&_pre]:bg-gray-100 [&_pre]:p-3 [&_pre]:rounded [&_blockquote]:border-l-2 [&_blockquote]:border-teal-400 [&_blockquote]:pl-3"
                  dangerouslySetInnerHTML={{ __html: renderedAnswer }}
                />
              ) : (
                <pre className="font-mono text-sm leading-relaxed text-gray-200 whitespace-pre-wrap break-words">
                  {currentQuestion ? `>>> ${currentQuestion}\n\n` : ''}{currentAnswer}
                </pre>
              )
            ) : (
              <div className="h-full flex items-center justify-center">
                <p className={`text-sm transition-colors ${
                  isOnline ? 'text-gray-400' : 'text-gray-500'
                }`}>Las respuestas aparecerán aquí...</p>
              </div>
            )}
          </div>

          {!isMini && (<>
          {/* Historial Drag Divider */}
          <div
            onMouseDown={onDividerMouseDown}
            className={`relative h-7 flex-shrink-0 cursor-row-resize select-none transition-colors group ${
              isOnline
                ? 'bg-gradient-to-b from-white via-gray-100 to-gray-50 hover:via-teal-50'
                : 'bg-gradient-to-b from-gray-700 via-gray-600 to-gray-700 hover:via-gray-500'
            }`}
          >
            <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 flex items-center justify-center">
              <div className={`flex items-center gap-2 px-4 py-1 border rounded-full shadow-sm transition-colors ${
                isOnline
                  ? 'bg-white border-gray-200 group-hover:border-teal-300'
                  : 'bg-gray-700 border-gray-500 group-hover:border-gray-400'
              }`}>
                <Clock className={`w-3 h-3 ${isOnline ? 'text-gray-400' : 'text-gray-400'}`} />
                <span className={`text-xs font-medium uppercase tracking-wider transition-colors ${
                  isOnline ? 'text-gray-500' : 'text-gray-300'
                }`}>Historial</span>
                <GripHorizontal className={`w-3 h-3 opacity-40 group-hover:opacity-80 transition-opacity ${
                  isOnline ? 'text-gray-400' : 'text-gray-400'
                }`} />
              </div>
            </div>
          </div>

          {/* History List */}
          <div
            style={{ height: historialHeight }}
            className={`flex-shrink-0 px-6 py-3 overflow-auto border-t transition-colors ${
              isOnline ? 'bg-white/30 border-gray-200' : 'bg-gray-800/60 border-gray-600'
            }`}
          >
            <div className="space-y-2">
              {history.length === 0 ? (
                <p className={`text-sm text-center py-8 transition-colors ${
                  isOnline ? 'text-gray-400' : 'text-gray-500'
                }`}>No hay interacciones previas</p>
              ) : (
                history.map(message => (
                  <div
                    key={message.id}
                    onClick={() => handleHistoryClick(message)}
                    className={`p-3 border rounded-lg cursor-pointer transition-all ${
                      isOnline
                        ? `bg-white hover:shadow-md hover:border-teal-300 ${
                            selectedHistoryId === message.id ? 'border-teal-500 shadow-md' : 'border-gray-200'
                          }`
                        : `bg-gray-700/60 hover:bg-gray-700 hover:border-gray-500 ${
                            selectedHistoryId === message.id ? 'border-gray-400' : 'border-gray-600'
                          }`
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Sparkles className={`w-3 h-3 flex-shrink-0 ${
                            isOnline ? 'text-teal-500' : 'text-gray-400'
                          }`} />
                          <p className={`text-xs font-medium truncate ${
                            isOnline ? 'text-gray-900' : 'text-gray-200'
                          }`}>{message.question}</p>
                        </div>
                        <p className={`text-xs truncate pl-5 ${
                          isOnline ? 'text-gray-500' : 'text-gray-400'
                        }`}>{message.answer.replace(/#+\s/g, '').replace(/\*\*/g, '').slice(0, 120)}</p>
                      </div>
                      <span className={`text-xs whitespace-nowrap flex-shrink-0 ${
                        isOnline ? 'text-gray-400' : 'text-gray-500'
                      }`}>
                        {message.timestamp.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
          </>)}
        </div>

        {!isMini && (
        <>{/* Footer */}
        <div className={`border-t transition-colors ${
          isOnline ? 'border-gray-200 bg-white/40' : 'border-gray-600 bg-gray-700/60'
        }`}>
          {/* Offline model warning */}
          {showModelWarning && (
            <div className="px-6 py-2 bg-red-900/40 border-b border-red-800/60">
              <p className="text-xs text-red-300">
                ⚠️ Load model first — the model may be loading. Try again in a moment.
              </p>
            </div>
          )}

          <div className="px-6 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`flex items-center gap-2 px-2 py-1 rounded-full transition-colors ${
                isOnline ? 'bg-teal-50' : 'bg-gray-600/60'
              }`}>
                <div className={`w-1.5 h-1.5 rounded-full ${
                  healthOk
                    ? (isOnline ? 'bg-teal-500' : 'bg-gray-400')
                    : 'bg-red-500'
                }`} />
                <span className={`text-xs font-medium transition-colors ${
                  isOnline ? 'text-teal-700' : 'text-gray-300'
                }`}>
                  {isOnline ? 'online' : 'offline'}
                </span>
              </div>
              <span className={`text-xs transition-colors ${
                isOnline ? 'text-gray-500' : 'text-gray-400'
              }`}>{chunks} chunks</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => triggerIngest('local')}
                title="Sync Local Files"
                className={`p-2 rounded transition-colors ${
                  isOnline ? 'hover:bg-gray-100' : 'hover:bg-gray-600'
                }`}
              >
                <HardDrive className={`w-4 h-4 ${isOnline ? 'text-gray-600' : 'text-gray-400'}`} />
              </button>
            </div>
          </div>
        </div>
        </>)}
      </div>

      {!isMini && (
      <div
        style={{ width: sidebarWidth }}
        className={`no-drag-region flex-shrink-0 border-l backdrop-blur-sm relative z-10 m-4 ml-0 rounded-r-2xl overflow-hidden transition-colors ${
          isOnline ? 'border-gray-200 bg-white/60' : 'border-gray-600 bg-gray-800/70'
        }`}
      >
        {/* Horizontal drag handle on left edge */}
        <div
          onMouseDown={onSidebarDividerMouseDown}
          className={`absolute left-0 top-0 bottom-0 w-3 cursor-col-resize select-none flex items-center justify-center z-20 group transition-colors ${
            isOnline ? 'hover:bg-teal-50/70' : 'hover:bg-gray-700/60'
          }`}
        >
          <GripVertical className={`w-3 h-8 opacity-0 group-hover:opacity-50 transition-opacity ${
            isOnline ? 'text-gray-400' : 'text-gray-500'
          }`} />
        </div>
        <div className="p-4 pl-5">
          <h3 className={`text-sm font-semibold mb-3 transition-colors ${
            isOnline ? 'text-gray-700' : 'text-gray-300'
          }`}>File Access</h3>
          <div className={`rounded border transition-colors ${
            isOnline ? 'bg-white border-gray-200' : 'bg-gray-700/60 border-gray-600'
          }`}>
            <div className="flex items-center gap-2 px-3 py-2">
              <HardDrive className={`w-4 h-4 ${isOnline ? 'text-gray-600' : 'text-gray-400'}`} />
              <span className={`text-sm font-medium ${isOnline ? 'text-gray-700' : 'text-gray-300'}`}>Local files</span>
            </div>
            <div className="px-3 pb-2">
              <p className={`text-xs ${isOnline ? 'text-gray-400' : 'text-gray-500'}`}>
                Use the sync button (↓) to ingest a folder of .md / .txt files.
              </p>
            </div>
          </div>
        </div>
      </div>
      )}

      {/* Go-online dialog */}
      {goOnlineDialog && (
        <div className="fixed inset-0 bg-black/55 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-gray-800 border border-gray-600 rounded-2xl px-8 py-7 max-w-sm w-[90%] shadow-2xl text-center">
            <p className="text-sm font-medium text-gray-100 mb-6 leading-snug">
              No results found in the knowledge base.<br />
              Do you want to go online?
            </p>
            <div className="flex gap-3 justify-center">
              <button
                onClick={handleGoOnlineYes}
                className="px-6 py-2 bg-teal-500 text-white rounded-full font-bold text-sm hover:bg-teal-400 transition-colors"
              >
                Yes
              </button>
              <button
                onClick={handleGoOnlineNo}
                className="px-6 py-2 bg-gray-700 border border-gray-500 text-gray-200 rounded-full text-sm hover:border-gray-400 transition-colors"
              >
                No
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
