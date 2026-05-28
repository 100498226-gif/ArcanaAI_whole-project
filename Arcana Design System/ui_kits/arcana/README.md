# Arcana — UI Kit

A reference implementation of the Arcana interface, derived **entirely** from the 15 rendered pages of `uploads/ArcanaAI_Assets.pdf`. Every element here traces to a specific page/principle in the PDF, not to any external screenshots or pre-existing code.

## Files
- `index.html` — interactive app shell. Both modes, a real query experience, live mode toggle.
- `components/Brand.jsx` — logo + wordmark element.
- `components/Chrome.jsx` — sidebar + mode toggle + top bar.
- `components/QueryBar.jsx` — the signature query input with sparkle + Ask pill.
- `components/Response.jsx` — streaming response area with citations.
- `components/Controls.jsx` — slider, segmented, toggle primitives.
- `components/Hero.jsx` — marketing hero ("Un Sistema Construido para Cada Entorno").

## What's modeled

1. **Dual mode.** Flip the top-right toggle. The whole shell swaps from Cosmic Depths → Stellar Atmosphere. This is Arcana's signature: mode is load-bearing — it tells the user where their data is going.
2. **Breathing interface.** Idle state uses the Pulsing Synthesis animation from PDF p.12 (concentric green rings at 0.8s). Hover on any control brings up the Energetic Hover glow.
3. **13 × 30 px padding.** The "Ask" button and mode pill obey the non-negotiable padding called out on PDF p.10.
4. **No hard borders.** All container separation is handled by glow halos and faint hairline strokes, per PDF p.8 ("Cero Bordes Duros").

## What is intentionally NOT here

- No detailed file browser, ingest wizard, or admin surfaces. The PDF doesn't show these — we don't invent what isn't in the source of truth.
- No pre-existing codebase was referenced. The user's existing Electron overlay was rejected; this kit is a rebuild against the PDF only.
