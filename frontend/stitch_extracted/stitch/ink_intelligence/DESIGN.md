# Design System Strategy: The Cinematic Editorial

## 1. Overview & Creative North Star
**Creative North Star: "The Digital Auteur"**
This design system moves away from the sterile, "SaaS-blue" dashboard aesthetic toward a cinematic, editorial experience. It treats the process of AI-assisted novel writing not as a data-entry task, but as a prestigious creative endeavor. 

The system breaks the "template" look through **Intentional Asymmetry**. Instead of a standard 12-column grid, we utilize weighted layouts where the "Reading Canvas" (Serif) holds the visual center of gravity, while "AI Agent" monitoring windows (Sans-Serif) float as orbiting satellites. We use high-contrast typography scales and overlapping elements to create a sense of depth and narrative flow.

## 2. Colors & Surface Philosophy
The palette is rooted in a deep, nocturnal base (`background: #0b1326`) to reduce eye strain during long-form writing sessions, punctuated by "Electric Indigo" (`primary: #c0c1ff`) and "Soft Gold" (`secondary: #e9c349`).

*   **The "No-Line" Rule:** 1px solid borders are strictly prohibited for sectioning. Structural boundaries must be defined solely through background color shifts. For example, a sidebar using `surface-container-high` should sit flush against the `background` without a stroke.
*   **Surface Hierarchy & Nesting:** Use the `surface-container` tiers to create organic depth. 
    *   *Lowest Tier:* `surface-container-lowest` for the main background.
    *   *Mid Tier:* `surface-container-low` for secondary navigation.
    *   *High Tier:* `surface-container-highest` for active modal overlays or focused agent windows.
*   **The "Glass & Gradient" Rule:** For AI action nodes or floating toolbars, use Glassmorphism. Apply `surface-bright` at 60% opacity with a `backdrop-blur` of 12px.
*   **Signature Textures:** Main CTAs (like "Generate Chapter") should never be flat. Use a linear gradient from `primary` (#c0c1ff) to `primary-container` (#8083ff) at a 135-degree angle to provide a "lit from within" professional polish.

## 3. Typography
The system employs a dual-typeface strategy to distinguish between "System" and "Story."

*   **UI/Metadata (Manrope - Sans Serif):** Used for the "machinery" of the app—labels, buttons, and AI agent status. `display-lg` (3.5rem) should be used sparingly for story titles to create an authoritative, book-cover feel.
*   **Editorial/Reading (Newsreader - Serif):** Used for all long-form text and story titles. The `body-lg` (1rem) is the workhorse here, optimized with a 1.6x line-height to ensure the AI-generated prose feels like a published novel.
*   **Hierarchy as Identity:** Use `label-sm` in `secondary` (Soft Gold) for AI-status indicators to create a "premium manuscript" feel, contrasting against the technical `headline-sm` headers.

## 4. Elevation & Depth
We eschew traditional drop shadows for **Tonal Layering**.

*   **The Layering Principle:** Place a `surface-container-lowest` card on a `surface-container-low` section to create a soft, natural lift. This mimics the way thick paper stock casts a subtle edge.
*   **Ambient Shadows:** For "Floating Agent Windows," use a shadow with a 40px blur at 6% opacity, tinted with `primary` (#c0c1ff). This creates a "glow" rather than a "shadow," suggesting the AI is an active, energetic presence.
*   **The "Ghost Border" Fallback:** If a container requires definition against a similar tone, use the `outline-variant` token at 15% opacity. This "Ghost Border" provides just enough contrast for accessibility without breaking the fluid, dark-mode aesthetic.

## 5. Components

### Cards (Story Management)
*   **Style:** No borders. Use `surface-container-low`. 
*   **Interaction:** On hover, transition the background to `surface-container-high` and increase the corner radius from `md` to `lg`. 
*   **Content:** Separate metadata (word count, genre) using vertical white space (`spacing-4`) instead of divider lines.

### Complex Forms (Story Setup)
*   **Input Fields:** Use `surface-container-highest` for the input track. Labels should be `label-md` in `on-surface-variant`.
*   **Focus State:** Instead of a thick border, use a subtle "outer glow" using a 2px `outline` at 20% opacity of the `primary` color.

### Monitoring Windows (AI Agents)
*   **Visuals:** Use the Glassmorphism rule (backdrop-blur). Use `tertiary` (#ffb783) for "Agent Thinking" states to distinguish them from user-driven actions.
*   **Graph Elements:** Interactive nodes should use `primary` for "User Nodes" and `secondary` for "AI Suggestions." Connect them with `outline-variant` paths at 30% opacity.

### Buttons
*   **Primary:** Gradient (`primary` to `primary-container`), white text (`on-primary`), `round-full`.
*   **Tertiary:** No background. Use `label-md` in `primary` with a subtle underline that expands on hover.

## 6. Do's and Don'ts

### Do
*   **Do** use `spacing-16` or `spacing-20` for generous margins around the Reading Canvas to evoke a sense of focus.
*   **Do** use `secondary_fixed` (Soft Gold) for "Milestones" or "Golden Path" story nodes to celebrate user progress.
*   **Do** ensure that any text in `newsreader` has a maximum line width of 650px for optimal readability.

### Don't
*   **Don't** use 100% white (#FFFFFF) for text. Always use `on-surface` (#dae2fd) to maintain the cinematic, low-eye-strain atmosphere.
*   **Don't** use sharp corners. This is a creative platform; use the `md` (0.375rem) and `xl` (0.75rem) roundedness to keep the UI feeling approachable and organic.
*   **Don't** use dividers. If two elements need separation, increase the `spacing` scale or shift the `surface-container` tier.