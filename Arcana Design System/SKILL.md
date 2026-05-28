---
name: arcana-design
description: Use this skill when designing or building artifacts (slides, mocks, prototypes, landing pages, product UI, marketing) for Arcana — the local-first, dual-mode knowledge assistant. Loads the Arcana brand tokens, typography, color palette, and UI kit.
user-invocable: true
---

Arcana has a dual-mode brand: **Cosmic Depths** (dark) and **Stellar Atmosphere** (light). Both are primary. Mode is load-bearing — it tells the user whether their data is leaving the machine.

Read `README.md` for the full system, then `colors_and_type.css` for tokens, then `ui_kits/arcana/index.html` for the reference implementation. Every rule traces back to `uploads/ArcanaAI_Assets.pdf` (the only source of truth) — pages rendered in `assets/brand/page_*.png`.

**Must-follow rules:**
- Voice is Spanish-first, poetic-technical ("Cero Bordes Duros", "Profundidad Cósmica").
- Pill buttons use 13×30 px padding — non-negotiable.
- No hard edges (min radius 8 px), no emoji, no icon fonts — Lucide SVG only.
- Fluorescent green #00FF88 is reserved for hover/active and the signature gradient (teal → fluor).
- Hover = glow, never a darker shade. Pulsing Synthesis for active states.
- Manrope (display), Nunito (wordmark), JetBrains Mono (code) — all Google Fonts substitutions; flag for replacement if brand fonts arrive.

Copy assets out of this project into the working project before shipping. Never link cross-project.
