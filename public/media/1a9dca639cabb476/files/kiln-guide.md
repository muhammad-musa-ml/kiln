# Launch SEO: discovery, indexing and shared-preview checklist

Researched 2026-11-02.

## A launch checklist with separate outcomes
The reel usefully frames SEO as concrete checks: discoverable pages, search-console setup and good shared previews. Submission, crawling, indexing, ranking and conversion are different outcomes. This guide checked current primary documentation on November 2, 2026; no domain verification or search submission was performed.

## 1. Check what the page returns
For each important public URL, confirm a successful response, useful visible content, a descriptive title, internal links and the intended canonical URL. Check that a production page is not accidentally blocked or marked `noindex`. Do not remove a deliberate privacy restriction just to pass a checklist. Google's [starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide) is the baseline, and its [JavaScript SEO documentation](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics) explains crawling and rendering for script-driven pages.

For a simple response check in Windows PowerShell, replace the example with a public site you control:

```powershell
(Invoke-WebRequest -Uri 'https://example.com/' -Method Get).StatusCode
```

That verifies one response status, not indexability or rendered content. Inspect the visible page and search-console evidence as well. An authenticated localhost page is not the URL to submit to public search engines.

## 2. Sitemap and Google Search Console
List canonical public URLs in a sitemap, including only pages intended for discovery. Verify the correct property in [Google Search Console](https://search.google.com/search-console/about) and submit the sitemap there. Use URL inspection on representative pages and read the reported reason if a page is excluded. Google's [sitemap overview](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview) says sitemaps help discovery; they do not guarantee crawling or indexing.

## 3. Bing and IndexNow
Use [Bing Webmaster Tools](https://www.bing.com/webmasters/about) for the relevant site property. [IndexNow documentation](https://www.indexnow.org/documentation) describes a site-hosted verification key and notifications to participating engines when a URL changes. A successful API response acknowledges receipt; it does not promise immediate indexing. IndexNow is not a Google submission mechanism. Do not paste arbitrary third-party URLs into a submission script or treat a reel as proof that every engine participates.

## 4. Shared previews
The [Open Graph protocol](https://ogp.me/) defines the basic title, type, image and URL fields. A minimal illustrative HTML fragment is:

```html
<meta property="og:title" content="A useful product page">
<meta property="og:type" content="website">
<meta property="og:url" content="https://example.com/product">
<meta property="og:image" content="https://example.com/preview.jpg">
```

Replace all examples with real absolute public URLs. Check that the image loads without a login and that the preview describes the actual destination. Preview metadata does not itself prove ranking quality.

## Reusable prompt
```text
Audit these public URLs using a checklist of response status, visible
content, title, canonical, robots/noindex intent, sitemap membership,
internal links and shared-preview image. Separate direct observations
from checks requiring owner access. Give each issue a reproducible check
and a proposed fix. Never claim submission means indexing or ranking.
```

## Project idea
Create a launch-discovery ledger from the attached blank CSV: URL, intended visibility, status, canonical, sitemap, preview and owner-only follow-up. Start with five key pages. Keep Google, Bing, IndexNow receipt and later search appearance in separate columns so progress remains meaningful.


## Original sources
- https://www.instagram.com/reel/DfP381BOVyh/