# Preferred Sources: reader opt-in and current Search eligibility

Researched 2026-11-07.

## Strengths and best use
Google's Preferred Sources feature gives an existing reader a direct way to favor a publication in supported Search experiences. The current documentation covers Top Stories and preferred badges in AI Mode and AI Overviews. A clear opt-in link is useful for a publication with returning readers. [Google documentation](https://developers.google.com/search/docs/appearance/preferred-sources)

## Current checks
The November 7 documentation goes beyond the dossier's older Top Stories-only explanation. Domain and subdomain sites can be eligible, while a subdirectory is not a separate preferred source. Confirm that the publication appears in Google's preference picker and check the documented eligibility for AI Search features. Reader selection and normal search discovery remain separate measurements. [Current eligibility and implementation](https://developers.google.com/search/docs/appearance/preferred-sources)

## Implement a simple reference link
Replace the example domain with the publication's real domain. Google's documentation also provides an optional localized JavaScript button and custom SDK paths.
```html
<a href="https://www.google.com/preferences/source?q=example.com">
  Add as a preferred source
</a>
```

Verify the destination on mobile and desktop, the publication selected, keyboard access, visible focus, and the return path. Measure button use and returning-reader behavior with an appropriate observation window. Keep sitemap, canonical, and indexing checks in the broader launch SEO workflow. [SEO fundamentals](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)

## Reusable prompt
```text
Check this publication against the current Preferred Sources documentation. Verify its eligible domain in the picker, implement the documented opt-in route, and test accessibility and return behavior. Separate observed button use from any unmeasured search-traffic effect.
```

## Project idea
Add a publisher opt-in test sheet covering domain eligibility, link behavior, device, locale, and reader-feedback observations.


## Original sources
- https://www.instagram.com/reel/DeyBx9-vl0k/