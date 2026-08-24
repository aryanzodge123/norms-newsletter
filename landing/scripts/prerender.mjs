/* Prerender the landing pages, and write the files a machine reads.
 *
 * SPEC 15.2 and 15.3, proposed in PROPOSED-SPEC-DISCOVERY.md. Runs after
 * `vite build`, over the output in dist/.
 *
 * The contract this exists to satisfy: a client that runs no JavaScript
 * receives the whole page. Before this step, dist/index.html held 3,166 bytes
 * and an empty root div, so everything except Google saw a blank document.
 *
 * There are two pages now, / and /faq, and each is a separate static document
 * rather than a route. The loop below is the only thing that knows that; the
 * contract and the reasoning are unchanged, and adding a third page is adding
 * a third entry to PAGES.
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
 * is the reason it matters on a page that today has exactly two URLs. */
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
const { App, FaqPage, FAQ_ITEMS, BENEFITS, NS_TOPICS, NS_LEN, STOPS, STAGES, NORM_POINTS } = mod

const decode = (s) =>
  s.replace(/&middot;/g, '·').replace(/&rsquo;/g, '’').replace(/&amp;/g, '&').trim()

/* </ inside a script block ends it, whatever the surrounding quotes say. */
const embed = (data) => JSON.stringify(data, null, 2).replace(/</g, '\\u003c')

/* Render one component into one built HTML file.
 *
 * The floor is per page rather than global. The front page is an order of
 * magnitude longer than /faq, so one number would be either useless there or
 * impossible here. Both are checked before anything in dist/ is touched, so a
 * failed run cannot leave a half-written file behind for a later deploy.
 *
 * The failure mode that matters is silent. An empty root looks exactly like a
 * working build until somebody runs curl against production weeks later, which
 * is how the page shipped in that state and nobody noticed. */
function render({ name, component, file, floor, graph }) {
  const markup = renderToStaticMarkup(createElement(component))
  if (markup.length < floor) {
    fail(`${name}: markup is ${markup.length} bytes, under the ${floor} byte floor. The page would ship close to empty.`)
  }

  const htmlPath = join(DIST, file)
  let html = readFileSync(htmlPath, 'utf8')

  const ROOT = '<div id="root"></div>'
  if (!html.includes(ROOT)) {
    fail(`${name}: could not find ${ROOT} in dist/${file}. Vite's output shape changed, and the page would have shipped empty.`)
  }
  html = html.replace(ROOT, `<div id="root">${markup}</div>`)

  /* Title and description are read back out of the built HTML rather than
   * restated here. Each page's own .html owns its copy; this file owns URLs. */
  const title = (html.match(/<title>([\s\S]*?)<\/title>/) || [])[1]
  const description = (html.match(/<meta\s+name="description"\s+content="([\s\S]*?)"/) || [])[1]
  if (!title || !description) fail(`${name}: ${file} is missing a <title> or a meta description.`)

  html = html.replace(
    '</head>',
    `    <script type="application/ld+json">\n${embed({
      '@context': 'https://schema.org',
      '@graph': graph({ TITLE: decode(title), DESCRIPTION: decode(description) }),
    })}\n    </script>\n  </head>`,
  )

  writeFileSync(htmlPath, html)
  return { markup: markup.length, html: html.length }
}

/* One @graph per page. Structured data describes only what exists (proposed
 * decision #59): there is no offers block, no aggregateRating and no review,
 * because the app is not released and has no users. There is no
 * operatingSystem or softwareVersion for the same reason.
 *
 * The Organization and WebSite nodes are declared on the front page and
 * referenced by @id from /faq, which is what @id is for: one description of
 * the publisher, pointed at from everywhere. */
const ORG = `${SITE_ORIGIN}/#organization`
const SITE = `${SITE_ORIGIN}/#website`

const PAGES = [
  {
    name: 'index',
    component: App,
    file: 'index.html',
    floor: 10000,
    graph: ({ TITLE, DESCRIPTION }) => [
      {
        '@type': 'Organization',
        '@id': ORG,
        name: "Norm's Newsletter",
        url: `${SITE_ORIGIN}/`,
        email: CONTACT,
        foundingDate: '2025',
        logo: { '@type': 'ImageObject', url: `${SITE_ORIGIN}/apple-touch-icon.png` },
      },
      {
        '@type': 'WebSite',
        '@id': SITE,
        url: `${SITE_ORIGIN}/`,
        name: "Norm's Newsletter",
        description: DESCRIPTION,
        inLanguage: 'en',
        publisher: { '@id': ORG },
      },
      {
        '@type': 'WebPage',
        '@id': `${SITE_ORIGIN}/#webpage`,
        url: `${SITE_ORIGIN}/`,
        name: TITLE,
        description: DESCRIPTION,
        inLanguage: 'en',
        isPartOf: { '@id': SITE },
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
        publisher: { '@id': ORG },
        featureList: BENEFITS.map(([benefit]) => benefit.replace(/\.$/, '')),
      },
    ],
  },
  {
    name: 'faq',
    component: FaqPage,
    file: 'faq.html',
    /* The ten answers alone are about 4,500 characters, so this catches an
     * empty root without tripping on ordinary copy edits. */
    floor: 6000,
    graph: ({ TITLE, DESCRIPTION }) => [
      {
        '@type': 'FAQPage',
        '@id': `${SITE_ORIGIN}/faq#webpage`,
        url: `${SITE_ORIGIN}/faq`,
        name: TITLE,
        description: DESCRIPTION,
        inLanguage: 'en',
        isPartOf: { '@id': SITE },
        publisher: { '@id': ORG },
        /* Composed from the same strings the page renders, so the markup
         * cannot claim an answer the page does not give. */
        mainEntity: FAQ_ITEMS.map(({ q, a }) => ({
          '@type': 'Question',
          name: q,
          acceptedAnswer: { '@type': 'Answer', text: a },
        })),
      },
      {
        '@type': 'BreadcrumbList',
        '@id': `${SITE_ORIGIN}/faq#breadcrumb`,
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: "Norm's Newsletter", item: `${SITE_ORIGIN}/` },
          { '@type': 'ListItem', position: 2, name: 'Frequently asked questions', item: `${SITE_ORIGIN}/faq` },
        ],
      },
    ],
  },
]

const rendered = PAGES.map((page) => ({ name: page.name, ...render(page) }))

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

/* /faq is monthly against the front page's weekly. The front page changes as
 * the product does; the answers change when somebody asks something new. */
const SITEMAP = [
  { loc: `${SITE_ORIGIN}/`, changefreq: 'weekly' },
  { loc: `${SITE_ORIGIN}/faq`, changefreq: 'monthly' },
]

writeFileSync(
  join(DIST, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${SITEMAP.map(
  ({ loc, changefreq }) => `  <url>
    <loc>${loc}</loc>
    <lastmod>${today}</lastmod>
    <changefreq>${changefreq}</changefreq>
  </url>`,
).join('\n')}
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

> ${decode((readFileSync(join(DIST, 'index.html'), 'utf8').match(/<meta\s+name="description"\s+content="([\s\S]*?)"/) || [])[1])}

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

## Common questions

The full set, in the order /faq gives them.

${FAQ_ITEMS.map(({ q, a }) => `### ${q}\n\n${a}`).join('\n\n')}

## Links

- [Norm's Newsletter](${SITE_ORIGIN}/): this page. Product overview and the waiting list signup.
- [Frequently asked questions](${SITE_ORIGIN}/faq): the questions above, on their own page.
- Contact: ${CONTACT}

Generated from the page's own copy at build time, ${today}.
`,
)

/* ------------------------------------------------------------------ assert */

rmSync(TMP, { recursive: true, force: true })

console.log(
  `prerender: ${rendered
    .map((r) => `${r.name} ${r.markup.toLocaleString()} bytes of markup into ${r.html.toLocaleString()} bytes of HTML`)
    .join(', ')}. robots.txt, sitemap.xml and llms.txt written.`,
)

function fail(message) {
  realError(`prerender: ${message}`)
  rmSync(TMP, { recursive: true, force: true })
  process.exit(1)
}
