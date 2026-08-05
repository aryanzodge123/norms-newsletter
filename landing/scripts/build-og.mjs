// Generates the landing page's shared-link card and its home-screen icon.
//
// Run by hand (`npm run og`), not by `npm run build`. Both outputs are
// committed to public/, so a normal build and deploy needs nothing from here.
//
// The card is a port of site/public/og-default.svg: same geometry, same mug,
// same wordmark lockup, with only the tagline swapped for the landing page's
// own line. It is deliberately not a new design.
//
// Two things about the toolchain are load-bearing:
//
// 1. satori, resvg and the three @fontsource packages are resolved out of
//    site/node_modules rather than installed here. The card is the site's
//    brand asset. Giving landing/ its own copy of the pipeline is how the two
//    quietly drift apart.
// 2. The text goes through satori before resvg sees it. resvg cannot load
//    webfonts, so rasterizing an SVG that still contains <text> in IBM Plex
//    would silently substitute a system font. satori converts text to paths
//    first. This is why the card is not simply og-default.svg piped to resvg.

import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const HERE = dirname(fileURLToPath(import.meta.url))
const LANDING = join(HERE, '..')
const SITE = join(LANDING, '..', 'site')
const MODULES = join(SITE, 'node_modules')

if (!existsSync(MODULES)) {
  console.error(
    `Cannot find ${MODULES}.\n` +
      'This script borrows satori, resvg and the fonts from the site rather ' +
      'than installing its own copies. Run `npm install` in site/ first.',
  )
  process.exit(1)
}

const siteRequire = createRequire(join(SITE, 'package.json'))
const load = async (pkg) => import(pathToFileURL(siteRequire.resolve(pkg)).href)

// Both packages resolve to their CJS builds, which Node's interop wraps one
// level deeper than an ESM entry point would, so unwrap the double default.
const satoriMod = await load('satori')
const satori = satoriMod.default?.default ?? satoriMod.default
const resvgMod = await load('@resvg/resvg-js')
const { Resvg } = resvgMod.default ?? resvgMod

// Tokens. Simultaneously DESIGN.md section 3 and the default `morning` palette
// in src/index.css, which is why one static card suits a page whose colours
// move with the delivery dial.
const PAPER = '#F6F4EE'
const INK = '#23231F'
const MUTED = '#6B6A62'

const WIDTH = 1200
const HEIGHT = 630
const ICON = 180

function font(pkg, file) {
  return readFileSync(join(MODULES, pkg, 'files', file))
}

// The wordmark is IBM Plex Sans 500, tracked wide; the tagline is Plex Mono.
// satori takes woff, not woff2.
const fonts = [
  {
    name: 'IBM Plex Sans',
    data: font('@fontsource/ibm-plex-sans', 'ibm-plex-sans-latin-500-normal.woff'),
    weight: 500,
    style: 'normal',
  },
  {
    name: 'IBM Plex Mono',
    data: font('@fontsource/ibm-plex-mono', 'ibm-plex-mono-latin-500-normal.woff'),
    weight: 500,
    style: 'normal',
  },
]

// The canonical mug glyph, read from the favicon rather than redrawn so there
// is exactly one copy of the path data in the repo.
const mugSvg = readFileSync(join(LANDING, 'public', 'favicon.svg'), 'utf8')
const mugDataUri = `data:image/svg+xml;base64,${Buffer.from(mugSvg).toString('base64')}`

const el = (type, style, children) => ({ type, props: { style, children } })
const img = (style, src) => ({ type: 'img', props: { style, src } })

/** og-default.svg's lockup, positioned absolutely so the geometry matches it
 *  coordinate for coordinate rather than approximately. */
function card() {
  return el(
    'div',
    {
      position: 'relative',
      display: 'flex',
      width: WIDTH,
      height: HEIGHT,
      backgroundColor: PAPER,
    },
    [
      // Mug, at og-default.svg's 105,136 at 118 square.
      img({ position: 'absolute', left: 105, top: 136, width: 118, height: 118 }, mugDataUri),

      // Wordmark. og-default.svg sets a 230 baseline; `top` here is that
      // baseline less the ascent, so the two render identically.
      el(
        'div',
        {
          position: 'absolute',
          left: 227,
          top: 167,
          fontFamily: 'IBM Plex Sans',
          fontWeight: 500,
          fontSize: 64,
          letterSpacing: 12,
          color: INK,
        },
        "NORM'S NEWSLETTER",
      ),

      // The double rule, 4 over 2.
      el('div', { position: 'absolute', left: 120, top: 250, width: 960, height: 4, backgroundColor: INK }),
      el('div', { position: 'absolute', left: 120, top: 262, width: 960, height: 2, backgroundColor: INK }),

      // The tagline. og-default.svg carries the site's "A daily brief, in
      // plain English." here; this is the landing page's hero headline.
      el(
        'div',
        {
          position: 'absolute',
          left: 0,
          top: 306,
          width: WIDTH,
          display: 'flex',
          justifyContent: 'center',
          fontFamily: 'IBM Plex Mono',
          fontWeight: 500,
          fontSize: 26,
          color: MUTED,
        },
        'Read less. Miss nothing.',
      ),
    ],
  )
}

async function renderCard() {
  const svg = await satori(card(), { width: WIDTH, height: HEIGHT, fonts })
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: WIDTH } }).render().asPng()
  writeFileSync(join(LANDING, 'public', 'og.png'), png)
  return png.length
}

/** The home-screen icon: the mug on paper, inset so it is not flush to the
 *  corners once iOS rounds them. Pure paths and no text, so this one goes
 *  straight through resvg and never needs satori. */
function renderIcon() {
  const inset = 26
  const box = ICON - inset * 2
  const glyph = mugSvg
    .replace(/^[\s\S]*?<svg[^>]*>/, '')
    .replace(/<\/svg>\s*$/, '')
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON}" height="${ICON}" viewBox="0 0 ${ICON} ${ICON}">` +
    `<rect width="${ICON}" height="${ICON}" fill="${PAPER}"/>` +
    `<svg x="${inset}" y="${inset}" width="${box}" height="${box}" viewBox="0 0 128 128">${glyph}</svg>` +
    `</svg>`
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: ICON } }).render().asPng()
  writeFileSync(join(LANDING, 'public', 'apple-touch-icon.png'), png)
  return png.length
}

const cardBytes = await renderCard()
const iconBytes = renderIcon()
console.log(`public/og.png               ${WIDTH}x${HEIGHT}  ${cardBytes} bytes`)
console.log(`public/apple-touch-icon.png ${ICON}x${ICON}    ${iconBytes} bytes`)
