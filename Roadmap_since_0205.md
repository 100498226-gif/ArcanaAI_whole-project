Roadmap since 02/05
V1 - Change
  Audit — Pass 1: clean — no unused imports, no silent errors, fallback chain is exhaustive.                                
  Pass 2: clean — no DB/SQL, no async misuse; torch.no_grad() correctly wraps inference; lru_cache + unload_model()         
  correctly manage memory lifecycle.                                                                                        
  Pass 3: clean — same chunk_type="image_vision" / source_type="image" metadata as the Gemini online path; consistent with  
  existing chunk structure.                                                                                                 
  Tests: 34 passed ✓ (3 new tests replace the old 1, covering the granite-primary path, the OCR-fallback path, and the      
  last-resort caption path).                                                                                                
                                                                                                                            
  ---                                                       
  Summary of what was built:                                                                                                
                                                                                                                            
  ┌───────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────┐
  │               File                │                                      Change                                      │  
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ services/granite_vision_client.py │ New — lazy-loads granite-vision-3.2-2b, MPS/CUDA/CPU device selection,           │
  │                                   │ unload_model() for post-ingest memory release                                    │
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────┤  
  │ services/chunker.py               │ Replaced image_captioner with granite-vision as primary offline analyzer; OCR is │
  │                                   │  now fallback for the single image_vision chunk (removed secondary OCR chunk)    │  
  ├───────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────┤
  │ tests/test_image_ingestion.py     │ Updated to new single-chunk contract; 3 tests covering granite-primary,          │  
  │                                   │ OCR-fallback, and last-resort paths                                              │  
  └───────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────┘
                                                                                                                            
  Fallback chain at ingest time:                                                                                            
  Online  → Gemini vision (unchanged)
  Offline → granite-vision-3.2-2b  →  OCR (pytesseract)  →  "Image file: filename"   



  V2 - Change
  Root cause & fix summary:             
                                                                            
  What was wrong: Content was ingested while in online mode — all 211 chunks landed in code_chunks/doc_chunks (Gemini       
  3072-dim). Offline mode queries code_chunks_local/doc_chunks_local (BGE 768-dim) which were empty, so every query returned
   a miss and fell back to the "no knowledge base" message.                                                                 
                                                                                                                            
  What was fixed:                                                                                                           

  ┌────────────────────────┬─────────────────────────────────┬──────────────────────────┐
  │                        │             Before              │          After           │
  ├────────────────────────┼─────────────────────────────────┼──────────────────────────┤
  │ GitHub/Notion ingest   │ Gemini only                     │ BGE + Gemini (both)      │
  ├────────────────────────┼─────────────────────────────────┼──────────────────────────┤
  │ Local ingest           │ Branched on current mode        │ BGE + Gemini (both)      │                                   
  ├────────────────────────┼─────────────────────────────────┼──────────────────────────┤                                   
  │ Timestamp diff (local) │ Checked online collections only │ Checks all 4 collections │                                   
  └────────────────────────┴─────────────────────────────────┴──────────────────────────┘                                   
                                                                                                                          
  Immediately: migrated all 211 existing chunks into the offline collections via BGE re-embedding (0 failures). Offline     
  retrieval now returns results correctly — tested with 15 hits at scores 0.61–0.61.                                      
                                                                                                                            
  Going forward: every ingest (GitHub, Notion, or local) writes to both embedding spaces so switching modes never empties   
  the KB.



  V3 - Change
    ---                                                                                                                       
  Audit — Pass 1: clean — all new JS functions are self-contained with no unused variables; SSE stream readers are guarded  
  with try/finally; setBadge is a simple pure helper; all DOM lookups use existing IDs.                                     
                                                                                                                            
  Pass 2: clean — no SQL, no server-side async issues; badge state guards (classList.contains('loading')) prevent badge     
  flicker during concurrent refreshModels calls; fetch calls have .catch(() => {}) on fire-and-forget paths; the            
  ensureOnlineMode loop that forced online_mode: true on every health poll is fully removed.                                
                                                                                                                            
  Pass 3: clean — model panel uses existing design tokens (var(--bg-1), var(--stroke-1), var(--arcana-success),             
  var(--arcana-danger), var(--accent-ui)); button classes match existing .btn-secondary; SSE streaming pattern mirrors      
  askQuestion().                                                                                                            
                                                            
  Tests: 29 passed, 5 pre-existing errors (importlib_metadata env issue) ✓                                                  
   
  Here's what changed in the UI:                                                                                            
  - Offline mode (dark theme): a model panel now appears between the ingest bar and query box, showing the LLM dropdown
  (qwen2.5:3b) and Vision row (granite-vision-3.2-2b), each with a Load button and a status badge                           
  - Load LLM: streams elapsed seconds until the model is warm → badge turns "✓ Ready"            
  - Ask guard: if offline and LLM badge isn't ready, shows "Load the LLM model first" error instead of firing a doomed query
  - Theme toggle: now also POSTs online_mode to the backend, so the backend mode actually follows the UI switch             
  - Auto-warm on startup: _prewarm_llm_model() runs in the background; when fetchHealth() gets llm_model_loaded: true, it   
  updates the badge automatically without user clicking Load                                                                
                                                             

V4 - Change
Done. Restart the Electron app with make overlay to pick up the changes.                                                  
                                                                                                                            
  What you'll see in the overlay (offline mode):                                                                            
  - A compact two-row panel between the mode toggle and the response area                                                   
  - LLM row: dropdown showing qwen2.5:3b, a Load button, and a badge that counts up Loading… Ns → turns ✓ Ready             
  - Vision row: granite-vision-3.2-2b label, same Load button and badge                                                     
  - If you try to Ask before loading the LLM, you get "Load the LLM model first — click Load above" in the status bar       
  - Switching to ONLINE mode hides the panel entirely                                                                       
                                                                                                                            
  Audit — Pass 1: clean — SERVER prefix on all new fetch calls; model-load-btn uses no-drag region for Electron             
  compatibility; all DOM IDs match between HTML and JS.                                                                     
                                                                                                                            
  Pass 2: clean — no new endpoints; SSE reader follows same pattern as askQuestion().                                       
                                                                                                                          
  Pass 3: clean — button class uses project's existing .ingest-btn visual language adapted to .model-load-btn; badge colors 
  reference --success-ui/--danger-ui/--accent-ui which are defined in both theme-offline and theme-online vars.
                                                                                                                            
---
 All clean. main is fully up to date with 4 commits since the last session:
                                           
  ┌─────────┬─────────────────────────────────────────────────────┐
  │ Commit  │                       Change                        │                                                         
  ├─────────┼─────────────────────────────────────────────────────┤
  │ 01f6b0d │ RAG data flow docs + roadmap                        │                                                         
  ├─────────┼─────────────────────────────────────────────────────┤                                                       
  │ 018dc19 │ granite-vision-3.2-2b offline image analyzer        │                                                         
  ├─────────┼─────────────────────────────────────────────────────┤
  │ 7025627 │ Dual-collection ingestion (online + offline always) │                                                         
  ├─────────┼─────────────────────────────────────────────────────┤                                                         
  │ 2030b09 │ Offline model management UI (browser + backend)     │
  ├─────────┼─────────────────────────────────────────────────────┤                                                         
  │ 10eeb08 │ Offline model management panel (Electron overlay)   │                                                       
  ├─────────┼─────────────────────────────────────────────────────┤                                                         
  │ a67bca1 │ Roadmap file move to repo root                                                                                 


  V5 - Change
  All changes look correct. Here's what was done:                                                                           
                                         
  electron/index.html:                                                                                                      
  - CSS: .model-panel is now display: flex always (panel visible in both modes)                                             
  - Added initModelPanelForModeFromDom() — online populates cloud LLM dropdown + hides Load button + marks ready; offline   
  shows Load button + calls refreshModels()                                                                                 
  - applyMode() now calls initModelPanelForModeFromDom() instead of the offline-only refreshModels()                        
  - refreshModelBadges() guards refreshModels() with if (!_onlineMode)                              
                                                                                                                            
  ui/index.html:                                                                                                            
  - applyAppearanceMode() now calls initModelPanelForModeFromDom() (was if (_darkAppearance) refreshModels()) so mode       
  toggles properly re-initialize the LLM row                                                                                
  - refreshModelBadges() same guard added — prevents the offline endpoint from overwriting the cloud model dropdown
                                                                                                                            
  Audit — Pass 1: clean (no new logic paths that could error; guard conditions are safe) | Pass 2: clean (no                
  DB/async/security concerns) | Pass 3: clean (both UIs follow same initModelPanelForModeFromDom pattern, consistent        
  badge/button state management)                                                                                            

V6 - Change
Done. Here's a summary of all changes:                 

  ui/index.html (browser) — complete rewrite:                                                                               
  - Two-column layout (app-main flex:1 + app-sidebar 260px)
  - Full-width header bar: A logo + single-line input + Clear/Cancel/ASK buttons                                            
  - Left column: ONLINE/OFFLINE toggle → model panel (LLM + Vision) → response area → Historial section
  - Right sidebar: File Access with GitHub / Notion / Local (with path input) sync sections                                 
  - Status (chunks + health dot) moved to top-left of response area; errors route to a floating toast                       
  - Mode now driven by backend /settings/ (same as electron), replaces old localStorage/appearance toggle                   
  - Historial section renders past questions with timestamps; clicking re-populates the input                               
  - Placeholder "Las respuestas aparecerán aquí…" shown when response area is empty                                         
                                                                                                                            
  electron/index.html — complete rewrite:                                                                                   
  - Same two-column structure (920px wide, sidebar 220px, main flex:1)                                                      
  - Same header / mode toggle / model panel / response area / history layout                                                
  - Preserved all electronAPI calls (getSettings, updateSettings, ingest, onIngestStatus, onClear)                          
  - exchange-badge moved into response meta area                                                                            
  - Error pop-up toast positioned absolutely within the window                                                              
                                                                                                                            
  electron/main.js: Window size 680×520 → 920×560                                                                           
                                                                                                                            
  Audit — Pass 1: clean (all IDs verified, no broken references) | Pass 2: clean (no DB/async regressions) | Pass 3: clean  
  (both UIs now share identical pattern for mode toggle, model panel, history, and toast)                                                       

  V7 - Change
  Summary of what's in place:                                                                                               
                                                                                                                            
  1. electron/index.html → renamed to electron/index.legacy.html                                                            
  2. Electronoverlay-main/vite.config.ts — base: './' + build.outDir: '../electron/ui-dist'                                 
  3. Electronoverlay-main/src/electron.d.ts — TypeScript declarations for window.electronAPI                                
  4. Electronoverlay-main/src/app/App.tsx — full rewrite with SSE streaming, model panel, mode toggle, health polling, IPC  
  listeners                                                                                                                 
  5. electron/main.js — now loads ui-dist/index.html                                                                        
  6. Dependencies installed, marked added, build succeeded → electron/ui-dist/index.html ✓                                  
                                                                                                                            
  To launch: start the backend, then run cd electron && npm start.                                                          
                                                                                                                            
  Audit — Pass 1: clean (all imports used, refs/state in sync, SSE handlers properly structured) | Pass 2: clean (no SQL,   
  XSS-safe since content is trusted backend output, all async paths have try/finally) | Pass 3: clean (consistent isOnline
  theming throughout, stable useCallback identities, preload API surface matches electron.d.ts)                             

V8 - Change
Build clean. Here's what changed:                                                                                         
                                                                                                                            
  - Default width is now 180 px (was 256 px / w-64) — gives the answer area more horizontal room                            
  - A 12 px invisible drag strip sits on the sidebar's left edge with cursor-col-resize                                     
  - Hovering it reveals a faint GripVertical icon (teal tint in online mode)                                                
  - Drag left → wider sidebar (max 320 px); drag right → narrower (min 140 px)                                              
  - The main content panel stays flex-1 so it fills the freed space automatically                                           
                                                                                                                            
  Audit — Pass 1: clean (sidebarDragRef properly reset on mouseup, listeners always removed) | Pass 2: clean | Pass 3: clean
   (same pattern as the Historial drag, consistent isOnline theming)     


   V9 - Change
    How it works:                                                                                                             
  - The root div gets drag-region (.drag-region { -webkit-app-region: drag }) — Chromium registers the entire window     
  background as draggable                                                                                                   
  - Both the main content panel and the sidebar get no-drag-region — all interactive elements (inputs, buttons, switches,   
  selects, accordions) are fully excluded from dragging                                                                     
  - The resulting drag zone is the visible background gap around the two panels (the 16px margin on all four sides)         
  - Six small white dots are centered at the top of the window as a subtle visual affordance to indicate the window is   
  draggable                                                                                                                 
                                                                                                                            
  The "use client" suggestions from the hook are Next.js-specific and do not apply to this Vite/Electron SPA — no action 
  needed.                                                                                                                   
                                                                                                                         
  Audit — Pass 1: clean | Pass 2: clean (pointer-events-none on the indicator prevents it from interfering with the drag    
  region) | Pass 3: clean                                    


  V10 - Change
  Everything is correct. Here's a summary of all four changes:   
                                                                 
  electron/main.js                                                                                                          
  - Hotkey: Ctrl+Alt+Space → Control+Command+Space                                                                          
  - blur → win.setOpacity(0.65) (window stays on screen, fades to 65%)                                                      
  - focus → win.setOpacity(1.0) (restores when clicked)                                                                     
  - toggleWindow show branch also calls setOpacity(1.0) before show()                                                       
  - New IPC set-mini-mode: resizes to 380×230 at bottom-right, or restores to 920×560 centered
                                                                                                                            
  electron/preload.js — exposes setMiniMode                                                                                 
                                                                                                                            
  electron.d.ts — typed setMiniMode: (mini: boolean) => void                                                                
                                                                                                                            
  App.tsx                                                                                                                   
  - Minimize2 / Maximize2 button top-left of header — clicking toggles mini mode and sends IPC
  - In mini mode: only the header (input + ask) + answer area remain visible                                                
  - Hidden in mini: online toggle, model panel, historial, footer, sidebar                   
  - Main panel uses rounded-2xl m-4 in mini (fully rounded, right-margin restored) vs rounded-l-2xl m-4 mr-0 in full        
                                                                                                                            
  Audit — Pass 1: clean (JSX tree balanced, all fragment open/close pairs verified by build) | Pass 2: clean (opacity set   
  before show() prevents flash; mini reposition uses live cursor display so it targets the correct screen on multi-monitor) 
  | Pass 3: clean           


  V11 - Change
  Change the icon left to the writing box
  ⏺ Done. The new icon (output-onlinepngtools.png, 7.2 kB) replaced the old one and is bundled in the build.

  V12 - Change
  Resizing everything appropriately in mini-window
   Clean build. In mini mode the header now uses:                                                                            
                                                                                                                            
  - px-2 py-2 container (vs px-6 py-4) — significantly tighter                                                              
  - gap-1 between items (vs gap-2)                                                                                          
  - w-3.5 h-3.5 restore icon, w-4 h-4 logo                                                                                  
  - px-2 py-1 text-xs input with min-w-0 so it can shrink freely                                                            
  - Clear shows ✕ instead of the word "Clear", Cancel shows ✕ — saves ~30px each                                            
  - ASK gets px-2.5 py-1 text-xs                                                                                            
                                                                                                                            
  All buttons have flex-shrink-0 so they never get clipped by the input growing. The full-mode header is completely         
  unchanged.            



  V12 - Change          
  Change the Desktop icon
   Done. The tray now loads electron/tray-icon.png via nativeImage.createFromPath and resizes it to 16×16 for the menu bar.
  The ✦ text title is cleared everywhere so only the image shows. The spinning ⟳ during ingest is kept since it still
  provides useful activity feedback next to the icon. 