# Arcana Design System

> **"Un Sistema Construido para Cada Entorno"** — A system built for every environment.

Arcana is a local-first knowledge assistant that indexes your files, resources and other knowledge, and responds with traceable citations, extracting information from within documents without needing to open them. It acts as a "data customs office" for AI agents — with a dual-mode UI (online with any LLM / offline 100% air-gapped) that uses visual language to tell the user where their data is going.

This design system is a **direct translation of `uploads/ArcanaAI_Assets.pdf`** — the 16-page brand guide, which is the ONLY source of truth for this project. Everything here traces to a specific page:

| PDF page | Topic | Key tokens |
| --- | --- | --- |
| 1 | Logo lockup on dark | `assets/logo-wordmark-dark.png` |
| 2 | Brand evolution — Logotipo, Luz Estelar, Alineaciones, Interacciones Fluorescentes | principles |
| 3 | Design principles: Organic Shapes, Cosmic Spatial Depth, Math Precision, Energetic Feedback | principles |
| 4 | **Color system** — Cosmic Depths + Stellar Atmosphere + Teal + Fluorescent Green | hex values below |
| 5 | Visual blocks (dark / light) with nebula flame glow | hero examples |
| 6 | **Typography hierarchy** — Titles, paragraphs, mono `const cosmos = await arcana.explore();` | type scale |
| 7 | **Cosmic Spatial Depth** — Active Container, Atmospheric Blur, Void Core | 3-layer depth model |
| 8 | UI Structural — Metrics containers with organic glow, no hard borders | card recipe |
| 9 | Components — geometric spacing for organic visuals | spacing |
| 10 | Pill button — 40×30px with 13px padding, teal→fluorescent gradient | `--space-3`, `--space-6` |
| 11 | Micro-interactions grid: Reposo / Hover / Focus × Bright / Dark | states |
| 12 | Energetic feedback — Nebula Trail, Pulsing Synthesis, Hover States | animations |
| 13 | Ecosystem — Toggles, sliders, chips in cosmic + atmospheric contexts | forms |
| 14 | Component ecosystem — pill toggle, segmented control, slider | forms |
| 15 | Marketing hero — "Un Sistema Construido para Cada Entorno" | hero |

The PDF is image-only (23 MB). Original-resolution renders of every page live in `assets/brand/page_01.png` … `page_15.png` for reference — always cross-check a new component against the source page before shipping.

---

## Index

```
Arcana Design System/
├── README.md                  ← you are here
├── SKILL.md                   ← Agent Skills manifest (export this file)
├── colors_and_type.css        ← all tokens, type scale, primitive recipes
├── assets/
│   ├── logo-wordmark-dark.png     logo lockup on Cosmic Depths
│   ├── logo-wordmark-light.png    logo lockup on Stellar Atmosphere
│   ├── logo-mark-dark.png         A-mark only, dark
│   ├── logo-mark-light.png        A-mark only, light
│   ├── hero-cosmic.png            page-15 marketing eclipse composition
│   ├── hero-eclipse.png           page-14 aurora+clouds diagonal split
│   ├── nebula-green.png           raw texture (from page 3)
│   ├── nebula-flame.png           green flame glow (page 5/8)
│   ├── aurora-purple.png          purple aurora (page 13)
│   ├── pulse-green.png            radial sound-wave pulse (page 12)
│   ├── cosmic-eclipse.png         central black hole + glow (page 15)
│   └── brand/page_01.png … page_15.png   full-res PDF pages
├── preview/                   ← small specimen cards for the Design System tab
├── ui_kits/
│   └── arcana/                ← the single unified UI kit (both modes in one)
│       ├── README.md
│       ├── index.html         ← marketing + app shell, interactive
│       └── components/        ← modular JSX: Button, PillToggle, QueryBar, Hero, Card, Metric
└── uploads/                   ← original PDF + extracted pages (do not edit)
```

---

## Content Fundamentals

The PDF is **entirely in Spanish**, which tells us the primary brand voice is Spanish. Representative copy pulled from the PDF:

- **Hero (page 15):** _"Un Sistema Construido para Cada Entorno. El futuro está bellamente diseñado. Cohesivo, inteligente y refinado hasta el último píxel."_
- **Typography sample (page 6):** _"Todo gran descubrimiento comienza con una pregunta. Arcana te da las herramientas para encontrar respuestas."_
- **CTA (page 15):** _"EXPLORAR EL SISTEMA"_ — primary action, uppercase tracked.
- **Principle headings (page 3):** _Formas Orgánicas · Profundidad Espacial Cósmica · Precisión Matemática · Retroalimentación Energética._
- **Micro-copy (page 12):** _"La interfaz respira. Los acentos fluorescentes no son solo colores: son el estado activo de la interacción del usuario."_

### Voice rules
- **Poetic-technical.** The product is engineering-grade ("Precisión Matemática: 13px / 30px padding inegociable") but copy is intentionally elevated — cosmic, atmospheric, "the interface breathes."
- **Spanish first.** Default to Spanish; provide English in a secondary position if bilingual. Never translate *brand nouns* (Void, Dust, Nebula, Dawn, Horizon, Cloud, Mist) — they're proper names.
- **Pascal Case for principles**, UPPERCASE for CTAs ("EXPLORAR EL SISTEMA"), Sentence case for body.
- **No emoji**, ever. The visual language is cosmic photography + glow; emoji break the illusion.
- **No "I".** The assistant speaks in system voice; avoid first-person. The user is addressed as _tú_ ("Arcana te da las herramientas…").
- **Use the specific dimensional vocabulary:** Atmospheric Blur, Active Container, Void Core, Nebula Trail, Pulsing Synthesis, Energetic Hover. These are brand terms.
- **No hype adjectives** ("amazing", "revolutionary"). Instead: mathematical, organic, cosmic, refined.

---

## Visual Foundations

### Colors

Two parallel palettes + two universal accents.

**Cosmic Depths** (dark mode, deepest → lightest):
```
Void     #080C1A
Deep     #0E1428
Nebula   #141C35
Dust     #1E2A4A
```

**Stellar Atmosphere** (light mode, lightest → structure):
```
Dawn     #FFFFFF
Horizon  #FAFBFD
Cloud    #F5F7FA
Mist     #EEF2F7
```

**Accents** (appear in BOTH modes):
```
Teal                #00BFA5   — "Turquesa"           — primary accent, logo, links, light-mode buttons
Fluorescent Green   #00FF88   — "Verde Fluorescente" — hover/active only (PDF says #00FF00; we lower to #00FF88 to avoid neon clipping)
Aqua highlight      #7FFFDF   — inside the A-mark sparkle
```

**Signature gradient:** `linear-gradient(135deg, #00BFA5 0%, #00FF88 100%)` — used on active pill buttons ("Ask", "Launch Arcana"). Teal → Fluorescent Green is the brand's hero gradient.

### Typography

The PDF uses a bold geometric sans for display and a rounded sans for the wordmark. We substitute **Manrope** (display/body) and **Nunito** (wordmark) from Google Fonts. **JetBrains Mono** for code. All three are Google-hosted — no brand-font files were provided with the PDF.

> **⚠ Substitution flag** — If Arcana has a branded display typeface, send `.woff2` files and we'll swap them in.

Scale (page 6):
- Display `96px / 800` — massive hero statements
- H1 `64px / 800`
- H2 `44px / 700`
- H3 `30px / 700`
- H4 `22px / 600`
- Body `16px / 400`
- Caption `14px / 400`
- Eyebrow `12px / 500 uppercase tracked`

### Spacing

PDF page 10 is explicit: **13px vertical + 30px horizontal padding is non-negotiable** for pill components. Built around a 4-multiple scale with those two values preserved as brand-critical:
```
4 · 8 · 13◆ · 16 · 24 · 30◆ · 40 · 56 · 80 · 120
```

### Backgrounds

**Dark mode** — layered cosmic photography. Nebulae, distant stars, subtle radial glows. NEVER flat black. The background breathes via faint teal/green radial gradients at 8–15% opacity.

**Light mode** — clean off-white with a single soft radial glow. Not pure white (`Dawn #FFF` is reserved for foreground panels), body uses `Horizon #FAFBFD`.

**Grid lines.** Several pages (3, 7, 10) overlay a faint 30-unit grid in teal at ~6% opacity. Use sparingly — it's a reference visualization, not decoration.

### Borders & Shadows

**"Cero Bordes Duros"** (zero hard edges) — PDF page 8. Cards use either:
- 1px hairline of `rgba(255,255,255,0.08)` (dark) / `rgba(0,0,0,0.06)` (light), OR
- No border at all, separation via glow only.

Hard 1px gray borders are a **brand violation**.

Shadow system has two flavors:
1. **Cosmic glow** (primary): green/teal radial halos at 24–80px blur, no y-offset. These are structural — they define depth.
2. **Atmospheric drop** (light mode only): soft `0 16px 48px rgba(11,16,32,0.08)` — used under floating cards in Stellar Atmosphere.

### Corner radii

Pills (`999px`) dominate. Cards use `28px` by default — large enough that corners feel organic. **Never ship corners below 8px** (brand says: no hard edges).

### Hover / press states

- **Hover** — PDF page 11 is unambiguous: hover = **fluorescent green glow replaces the rest state**. Not a darker color, not an opacity shift. A small radial halo appears + borders shift to `rgba(0,255,136,0.6)`.
- **Focus** — "Estilo Nebulosa Orgánico" — a wider, softer glow using the purple-teal nebula palette.
- **Press** — subtle `scale(0.98)`; no color change.
- **Disabled** — opacity 0.35, no glow.

### Transparency & blur

Used on floating overlays (page 15 hero card, page 13 info panel). Recipe: `background: rgba(8,12,26,0.75); backdrop-filter: blur(18px);` (dark) or `rgba(255,255,255,0.75)` (light). **Never used on primary content** — only on transient, floating surfaces.

### Imagery

- **Color vibe:** cool. Blues, teals, greens, occasional violets. Never warm (no orange, no red) except the fluorescent green in-accent.
- **Style:** photographic cosmic imagery + generative nebulae. Grain & bloom are welcome.
- **No illustrations of people.** The brand personality is astronomical, not human.

### Animation

The PDF names three motion archetypes (page 12):

1. **Nebula Trail** — cursor movement leaves a soft teal smoke trail on dark backgrounds.
2. **Pulsing Synthesis** — concentric green rings radiate from an active element (0.8s ease-out).
3. **Energetic Hover** — glow fades in at 180ms ease-out; never instant, never bounce.

Easing is always decelerating (`cubic-bezier(0.16, 1, 0.3, 1)` is a good default). No bounces, no spring overshoots — the brand is refined, not playful.

---

## Iconography

The PDF does **not** show a proprietary icon set. Icons that appear in the illustrations are:
- 4-point sparkle (inside the A-mark) — brand-owned, use `assets/logo-mark-*.png` or recreate in SVG
- Generic Lucide-style line icons (sun/moon, crosshair, cursor on page 2)
- Arrow indicators, measurement callouts — engineering notation style

**Recommendation:** use **Lucide** from CDN (`https://unpkg.com/lucide-static@latest/icons/...`) — matches the PDF's 1.5px stroke weight and rounded line caps. Documented in the UI kit.

**No emoji. No icon font. No Unicode-symbol icons** — unlike my previous attempt at this system, the PDF makes clear the icons should be real SVG line art.

---

## Caveats & open questions

1. **Brand fonts are substitutions.** Manrope + Nunito are my closest Google matches. If Arcana licenses Gotham Rounded, Circular, Söhne etc., please send files.
2. **Logo is a pixel crop, not a vector.** The PDF embedded the logo only as a JPEG/PNG raster. A vector version (`.svg` or `.ai`) would let us use the logo at any size without halos.
3. **Fluorescent green dialed down.** PDF says `#00FF00` but that value clips on most sRGB monitors and blows out bloom in screenshots. I'm using `#00FF88` as the shipping value. Easy to revert in `colors_and_type.css` if you want the pure neon.
4. **No product screenshots in the PDF.** Pages 13–14 are conceptual mockups with placeholder copy. The UI kit in `ui_kits/arcana/` is my interpretation of what a real Arcana app would look like using only the visual vocabulary the PDF defines.

---

## What to read next

- `SKILL.md` — the Agent Skills manifest. Drop this file into Claude Code to use the system as a brand skill.
- `colors_and_type.css` — import this in any HTML artifact to get all tokens + type scale + primitive button/card recipes.
- `ui_kits/arcana/index.html` — the reference implementation. See it running before building anything new.
- `preview/*.html` — small specimen cards shown in the Design System tab above.
