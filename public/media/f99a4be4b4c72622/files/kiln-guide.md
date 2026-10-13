# Agency Landing Page Redesign & Motion Implementation Guide

Researched 2026-10-12.

# Agency Landing Page Redesign & Motion Engineering Guide

## 1. What the Reel Claims & Demonstrates

In episode 7 of his "Review and redesign" series, creator Abdul Mutakabar Ayaz ([Instagram Reel Source](https://www.instagram.com/reel/DePYTBVi8DA/)) reviews and overhauls an ads agency landing page. His critique and Figma redesign focus on several key pillars:

* **Critique of AI Designs & Generic Messaging:** He highlights that typical AI-generated sites clutter hero sections without establishing a visual focal point, rely on vague headlines (e.g., "interest to your growth"), waste section space explaining the company name's origins, and fail to distinguish proof sections from promise sections.
* **Copywriting Structure:** Proposes rewriting hero value propositions into explicit outcomes ("Turn ads into paying customers") supported by immediate credential softening ("Averaging $18 CAC" instead of highlighting an unrepeatable single-case metric).
* **Single-Metaphor Branding:** Replaces disparate imagery with a unified concept visual: a 3D figure wrapped in yellow tape printed with "ADVERTISEMENT". This motif is repeated across stat cards and backgrounds to maintain identity coherence.
* **Card Stacks & Contrast Rhythm:** Organizes client case studies into overlapping, fanned card decks (e.g., showing business names like "Roberto AI", ad creative stacks, and metrics) and intersperses bright sections with high-contrast photographic "problem" bands.
* **Presentation:** The reel showcases static Figma artboards composited into a desktop monitor mockup with background music; the creator does not code or deploy the website on camera.

---

## 2. What Official Documentation Confirms Today

To translate this static Figma visual into a responsive web application, modern browser animation standards and React libraries must be applied:

* **Motion for React:** According to the [Motion React Documentation](https://motion.dev/docs/react), the modern package is installed via `npm install motion` and components are imported directly from `"motion/react"`. Motion provides declarative hooks (`useScroll`, `useTransform`, and `whileInView`) that leverage hardware acceleration (the Web Animations API and browser `ScrollTimeline`), keeping animations smooth at up to 120fps.
* **Scroll-Linked Interactions:** Motion supports binding transform properties directly to viewport progress using MotionValues, enabling the fanned-out card stack demonstrated in the design without manual event listeners.
* **Alternative Core Engines:** While GSAP provides robust timeline and plugin capabilities across vanilla JS environments as documented in the [GSAP Documentation](https://gsap.com/docs/v3/), Motion offers React-native lifecycle integrations, tree-shaking, and gesture handling.

*Verified official command:*
```bash
npm install motion
```

*(Note: Installing combined packages like `npm install motion gsap` from unverified guides is unnecessary if you exclusively leverage Motion's native React hooks).* 

---

## 3. What Remains Uncertain & Unverified

* **Conversion Metrics:** Claims that structural changes (e.g., headline phrasing, moving testimonials to section 5, or phrasing CAC as an average) boost conversions are rooted in design convention, not measured empirical A/B testing data provided in the reel.
* **Mockup Figures:** The case-study numbers shown in the reel (e.g., "Roberto AI", "290 sign-ups/month", "13.5% CTR") are design placeholders, not validated client campaign metrics.
* **Asset Generation Workflow:** The exact prompt, generative model, and editing tools used to build the yellow caution-tape figure were not disclosed; the reel only shows the final imported PNGs in Figma.

---

## 4. Engineering Limits, Gaps & Common Mistakes

* **Image Weight vs. Core Web Vitals:** Heavy 3D renders with alpha transparency can severely degrade Largest Contentful Paint (LCP). Large AI-generated assets should be converted to modern formats (AVIF/WebP) and sized responsively using `next/image`.
* **Accessibility Deficits:** Bright yellow accents (`#FFC400`) over white backgrounds fail WCAG 2.1 AA color contrast standards for text. Accent colors should be restricted to decorative badges, dark card containers, or buttons with high-contrast text.
* **Reduced Motion Non-Compliance:** Unchecked continuous rotations (like circular spinning badges) cause vestibular discomfort. Always wrap continuous CSS or Motion transforms in `@media (prefers-reduced-motion: reduce)` queries.
* **Z-Index Layering Bugs:** Overlapping rotated card stacks frequently cause mobile tap and hover clipping. Maintain defined stacking contexts using explicit Tailwind `z-index` assignments.

---

## 5. Reusable Claude Code Build Prompt

```text
Build a responsive single-page marketing site using Next.js (App Router), Tailwind CSS, and Motion (importing from 'motion/react').

Theme & Style:
- Color palette: Crisp white background, neutral near-black body text, and an amber/yellow accent (#FFC400) used sparingly on badges and stat cards.
- Typography: Serif display headlines with italic emphasis paired with clean sans-serif body text.

Key Components:
1. Hero: Headline 'Turn ads into paying customers.', subheadline, 'Book a call' button, and an SVG rotating circular badge ('OPEN TO WORK - FULL STACK -') wrapped with prefers-reduced-motion fallbacks.
2. Stat Cards: Horizontal responsive strip with oversized serif numerals ('$18 CAC', '13.5% CTR') against amber and dark backgrounds.
3. Case Studies: Section utilizing Motion's useScroll and useTransform to animate a fanned deck of cards (rotate and x offset) as the user scrolls into view.
4. Problem Band: High-contrast dark section breaking up the light layout.
5. Process & Testimonials: Clean 4-step sequence and grid testimonials section.

Implementation Requirements:
- Run zero external layout thrashing; keep all animations on hardware-accelerated transforms/opacity.
- Ensure all text passes WCAG AA contrast against backgrounds.
```

## Original sources
- https://www.instagram.com/reel/DePYTBVi8DA/