/* Prerender the landing page, and write the files a machine reads.
 *
 * SPEC 15.2 and 15.3, proposed in PROPOSED-SPEC-DISCOVERY.md. Runs after
 * `vite build`, over the output in dist/.
 *
 * The contract this exists to satisfy: a client that runs no JavaScript
 * receives the whole page. Before this step, dist/index.html held 3,166 bytes
 * and an empty root div, so everything except Google saw a blank document.
 *
 * Deterministic. No model call. Rendering is not something an AI touches.
 */

import { readFileSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { build } from 'vite'
import react from '@vitejs/plugin-react'

const HERE = dirname(fileURLToPath(import.meta.url))
const LANDING = join(HERE, '..')
const DIST = join(LANDING, 'dist')
const TMP = join(LANDING, '.prerender')

/* The only place any generated file names the domain (proposed decision #58).
 * CLAUDE.md rule 6 does this for the site through astro.config, and section 13
 * is the reason it matters on a page that today has exactly one URL. */
const SITE_ORIGIN = 'https://norm.news'
const CONTACT = 'norm@norm.news'

/* React warns on useLayoutEffect during a server render. There are two of them
 * and both are measurement code that correctly does nothing here: the FLIP
 * reorder in TopicStudio (App.jsx:529) and the ResizeObserver in PressFloor
 * (App.jsx:1157). The filter is narrow on purpose, so a real error still
 * reaches the build log. */
const realError = console.error
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('useLayoutEffect does nothing on the server')) return
  realError(...args)
}

/* ------------------------------------------------------------------ render */

/* configFile: false, so the Tailwind plugin stays out of this pass. Nothing
 * here paints, and the SSR bundle has no use for a stylesheet. */
await build({
  root: LANDING,
  configFile: false,
  logLevel: 'warn',
  plugins: [react()],
  build: {
    ssr: join(LANDING, 'src/entry-server.jsx'),
    outDir: TMP,
    emptyOutDir: true,
    minify: false,
    rollupOptions: { output: { entryFileNames: 'entry-server.mjs' } },
  },
})

const mod = await import(pathToFileURL(join(TMP, 'entry-server.mjs')).href)
const { App, BENEFITS, NS_TOPICS, NS_LEN, STOPS, STAGES, NORM_POINTS } = mod

/* Static markup rather than renderToString. Nothing hydrates: the client entry
 * keeps createRoot().render(), which replaces these children outright, so
 * React's hydration bookkeeping attributes would be bytes nobody reads. */
const markup = renderToStaticMarkup(createElement(App))

/* Checked here, before anything in dist/ is touched, so a failed run cannot
 * leave a half-written index.html behind for a later deploy to pick up.
 *
 * The failure mode that matters is silent. An empty root looks exactly like a
 * working build until somebody runs curl against production weeks later, which
 * is how the page shipped in that state and nobody noticed. */
const FLOOR = 10000
if (markup.length < FLOOR) {
  fail(`Prerendered markup is ${markup.length} bytes, under the ${FLOOR} byte floor. The page would ship close to empty.`)
}

/* ------------------------------------------------------------------ inject */

const htmlPath = join(DIST, 'index.html')
let html = readFileSync(htmlPath, 'utf8')

const ROOT = '<div id="root"></div>'
if (!html.includes(ROOT)) {
  fail(`Could not find ${ROOT} in dist/index.html. Vite's output shape changed, and the page would have shipped empty.`)
}
html = html.replace(ROOT, `<div id="root">${markup}</div>`)

/* Title and description are read back out of the built HTML rather than
 * restated here. index.html owns the page's copy; this file owns its URLs. */
const title = (html.match(/<title>([\s\S]*?)<\/title>/) || [])[1]
const description = (html.match(/<meta\s+name="description"\s+content="([\s\S]*?)"/) || [])[1]
if (!title || !description) fail('index.html is missing a <title> or a meta description.')

const decode = (s) =>
  s.replace(/&middot;/g, '·').replace(/&rsquo;/g, '’').replace(/&amp;/g, '&').trim()
const TITLE = decode(title)
const DESCRIPTION = decode(description)

/* One @graph in the head. Structured data describes only what exists
 * (proposed decision #59): there is no offers block, no aggregateRating and no
 * review, because the app is not released and has no users. There is no
 * operatingSystem or softwareVersion for the same reason. */
const jsonld = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'Organization',
      '@id': `${SITE_ORIGIN}/#organization`,
      name: "Norm's Newsletter",
      url: `${SITE_ORIGIN}/`,
      email: CONTACT,
      foundingDate: '2025',
      logo: { '@type': 'ImageObject', url: `${SITE_ORIGIN}/apple-touch-icon.png` },
    },
    {
      '@type': 'WebSite',
      '@id': `${SITE_ORIGIN}/#website`,
      url: `${SITE_ORIGIN}/`,
      name: "Norm's Newsletter",
      description: DESCRIPTION,
      inLanguage: 'en',
      publisher: { '@id': `${SITE_ORIGIN}/#organization` },
    },
    {
      '@type': 'WebPage',
      '@id': `${SITE_ORIGIN}/#webpage`,
      url: `${SITE_ORIGIN}/`,
      name: TITLE,
      description: DESCRIPTION,
      inLanguage: 'en',
      isPartOf: { '@id': `${SITE_ORIGIN}/#website` },
      about: { '@id': `${SITE_ORIGIN}/#app` },
      primaryImageOfPage: { '@type': 'ImageObject', url: `${SITE_ORIGIN}/og.png` },
    },
    {
      '@type': 'SoftwareApplication',
      '@id': `${SITE_ORIGIN}/#app`,
      name: "Norm's Newsletter",
      applicationCategory: 'NewsApplication',
      description: DESCRIPTION,
      url: `${SITE_ORIGIN}/`,
      publisher: { '@id': `${SITE_ORIGIN}/#organization` },
      featureList: BENEFITS.map(([benefit]) => benefit.replace(/\.$/, '')),
    },
  ],
}

/* </ inside a script block ends it, whatever the surrounding quotes say. */
const jsonText = JSON.stringify(jsonld, null, 2).replace(/</g, '\\u003c')
html = html.replace(
  '</head>',
  `    <script type="application/ld+json">\n${jsonText}\n    </script>\n  </head>`,
)

writeFileSync(htmlPath, html)

/* ---------------------------------------------------------------- generate */

const today = new Date().toISOString().slice(0, 10)

writeFileSync(
  join(DIST, 'robots.txt'),
  `# Cloudflare can merge a managed block into whatever file it finds here, in
# which case the served robots.txt is this file plus that one. It did until
# 2026-08-24, blocking the major AI crawlers by account default. That is a
# dashboard setting rather than anything in this repo, so if Disallow lines
# appear below, they came from there and are removed there.
# See PROPOSED-SPEC-DISCOVERY.md section 15.4.

User-agent: *
Allow: /

Sitemap: ${SITE_ORIGIN}/sitemap.xml
`,
)

writeFileSync(
  join(DIST, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${SITE_ORIGIN}/</loc>
    <lastmod>${today}</lastmod>
    <changefreq>weekly</changefreq>
  </url>
</urlset>
`,
)

/* llms.txt is composed from the page's own copy constants rather than written
 * beside them. A hand-maintained summary of a page that changes is a summary
 * that stops being true, and nothing in the build would catch it.
 *
 * NS_TOPICS carries a `meta` field ("3 today") that is demo data on a mock
 * screen. Only the names are used, so this file states nothing it cannot
 * stand behind. */
const bullet = (head, body) => `- **${head.replace(/\.$/, '')}.** ${body}`

writeFileSync(
  join(DIST, 'llms.txt'),
  `# Norm's Newsletter

> ${DESCRIPTION}

Norm's Newsletter is a news product, not a feed. A reader picks the sections
they care about and how long they want to read. Norm collects from a fixed list
of sources around the clock, clusters the duplicate coverage, scores what is
left, writes each story from its sources, and delivers one edition at the time
the reader chose. The edition ends. There is no infinite scroll and no
algorithmic timeline.

Status: not yet released. The site collects a waiting list.

## What it does

${BENEFITS.map(([b, why]) => bullet(b, why)).join('\n')}

## How an edition is made

${STAGES.map(([n, label, note]) => bullet(`${n} ${label}`, note)).join('\n')}

## Sections a reader can choose

${NS_TOPICS.map((t) => t.name).join(', ')}.

## How long an edition runs

${NS_LEN.map((l) => bullet(`${l.label}, about ${l.stories} stories`, l.note)).join('\n')}

## When it arrives

${STOPS.map(([time, tod, note]) => bullet(`${time}, ${tod}`, note)).join('\n')}

## Asking Norm about the news

${NORM_POINTS.map(([head, body]) => bullet(head, body)).join('\n')}

## Links

- [Norm's Newsletter](${SITE_ORIGIN}/): this page. Product overview and the waiting list signup.
- Contact: ${CONTACT}

Generated from the page's own copy at build time, ${today}.
`,
)

/* ------------------------------------------------------------------ assert */

rmSync(TMP, { recursive: true, force: true })

console.log(
  `prerender: ${markup.length.toLocaleString()} bytes of markup, ` +
    `dist/index.html now ${html.length.toLocaleString()} bytes. ` +
    `robots.txt, sitemap.xml and llms.txt written.`,
)

function fail(message) {
  realError(`prerender: ${message}`)
  rmSync(TMP, { recursive: true, force: true })
  process.exit(1)
}
