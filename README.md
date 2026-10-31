# Dutch Cloud Solutions website

Single-page static website for Dutch Cloud Solutions BV. Plain HTML, CSS and JavaScript: no build step, no framework, no third-party requests until a visitor presses play on the video.

> **Sharper go-to-market. Safer vendor choices.**
> Cloud go-to-market for ISVs. Vendor assessment for the enterprise.

## Structure

```
index.html                 The whole page (sections listed below)
assets/css/styles.css      Design tokens (light and dark) and all styles
assets/js/main.js          Motion and interactions (no dependencies)
assets/fonts/              Inter Variable and JetBrains Mono Variable (SIL OFL, self-hosted)
assets/img/                Logo files, favicon, touch icon, Open Graph image
assets/video/              Hero background loop (MP4) and poster frame (JPG)
web.config                 IIS / Azure App Service settings (MIME types, caching, hides .git and docs)
.htaccess                  Same rules for Apache hosts (ignored by IIS)
robots.txt, sitemap.xml    Search engine files
site.webmanifest           Browser icon metadata
docs/BRAND.md              Website brand rules (not served by the web server)
```

## Page sections

| Anchor | Section | What it carries |
| --- | --- | --- |
| `#top` | Hero | Video background, tagline, descriptor, Watch video CTA, proof line |
| `#practices` | Two practices | ISV Go-to-Market and Customer Success; Enterprise Vendor Selection and Assessment (equal cards) |
| `#approach` | Lifecycle | Assess, Design, Launch, Operate with an ISV lane and an enterprise lane (process image) |
| `#spectrum` | Method | Placement flow diagram (process image) and the interactive Sovereignty Spectrum, Tiers 0 to 4 |
| `#ai-activation` | AI activation | Index in place, serve any assistant via MCP (process image) |
| `#offers` | Offers | Tabs for ISVs and enterprises, durations, partner note |
| `#independence` | Selection integrity | The five independence rules for enterprise work |
| `#why-now` | Why now | Four dated facts with linked sources |
| `#about` | About | Founder background |
| `#contact` | Contact | Email and a form that opens the visitor's email app (nothing stored) |

## Preview locally

Any static server works. From the repository root:

```bash
python3 -m http.server 8080
# open http://localhost:8080
```

Opening `index.html` directly from disk also works, but a local server is closer to production.

## Common updates

**Set the YouTube video.** In `index.html`, find `data-youtube-id="YOUR_YOUTUBE_ID"` on the `<dialog id="video-modal">` element and replace the placeholder with the video ID (the part after `v=` in a YouTube URL). Until then the Watch video button opens a "coming soon" panel. Videos load from `youtube-nocookie.com` only after the visitor presses play.

**Replace the hero background video.** Overwrite `assets/video/hero-loop.mp4` and `assets/video/hero-poster.jpg`. Keep the clip muted, 8 to 15 seconds, seamlessly looping, H.264 MP4 and under about 5 MB. Dark footage works best; the overlay keeps white text readable. Example encode:

```bash
ffmpeg -i source.mov -t 12 -an -vf "scale=1920:-2" -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p -movflags +faststart assets/video/hero-loop.mp4
ffmpeg -ss 3 -i assets/video/hero-loop.mp4 -frames:v 1 -q:v 4 assets/video/hero-poster.jpg
```

**Edit an offer.** Offers are `<article class="offer-card">` blocks inside `#panel-isv` and `#panel-enterprise`. Each has a phase eyebrow (`01 / Assess` and so on), a title, one sentence and a duration.

**Update a "Why now" fact.** Each fact card has a figure, a heading, one or two sentences and a source link. Re-check every fact before publishing and update the as-of date in the section eyebrow and the note under the cards.

**Add a section.** Copy an existing `<section class="section">` block, give it an `id`, and add a link to the header nav (`.primary-nav ul`) and the footer nav. Add `class="reveal"` to elements that should fade in on scroll.

**Colors and type.** All colors come from the tokens at the top of `styles.css`, with separate light and dark values. Change a token, not an individual rule.

## Deployment

The hosting provider pulls this repository into the web root. Nothing needs building.

- `web.config` (IIS) and `.htaccess` (Apache) stop the server from serving `.git/`, `docs/` and Markdown files, set MIME types for `.woff2`, `.mp4` and `.svg`, and cache assets for 7 days while `index.html` stays fresh.
- After changing CSS or JS, browsers may hold the old file for up to 7 days. To force a refresh, add a version query in `index.html`, for example `styles.css?v=2`.
- Update the domain in `index.html` (canonical, Open Graph, JSON-LD), `robots.txt` and `sitemap.xml` if the site will not run on `https://dutchcloudsolutions.com/`.

## Open items

- [ ] YouTube video ID (`data-youtube-id`)
- [ ] Final hero footage (the current loop is a generated placeholder in brand colors: a polder grid at dusk with data pulses)
- [ ] KvK number and VAT ID in the footer (see the TODO comment)
- [ ] Confirm the production domain
- [ ] Optional: founder photo in the About section

## Content rules

The copy follows the Dutch Cloud Solutions brand guide (summary in `docs/BRAND.md`): US English, no em dashes, the tagline and descriptor verbatim, the two practices shown as equals, regulatory facts with an as-of date and a linked source, and no "DCS" abbreviation in visible text.
