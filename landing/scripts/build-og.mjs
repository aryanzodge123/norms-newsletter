// Generates the landing page's home-screen icon.
//
// Run by hand (`npm run icon`), not by `npm run build`. The output is committed
// to public/, so a normal build and deploy needs nothing from here.
//
// **This script no longer produces public/og.png.** The shared-link card is now
// a supplied image (the mug and the Norm wordmark on #ddd9cc) rather than a
// generated one, so there is nothing left for a generator to track. It used to
// render a port of site/public/og-default.svg here, and the consequence was a
// trap: `npm run og` would silently overwrite the real card with a stale
// regeneration of the old design. The card builder, the satori dependency and
// the font loading it needed were removed rather than left standing. If a
// generated card is ever wanted again, it is in this file's git history.
//
// One thing about the toolchain is still load-bearing: resvg is resolved out of
// site/node_modules rather than installed here, because the mug is the site's
// brand asset. Giving landing/ its own copy of the pipeline is how the two
// quietly drift apart.

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
      'This script borrows resvg from the site rather than installing its own ' +
      'copy. Run `npm install` in site/ first.',
  )
  process.exit(1)
}

const siteRequire = createRequire(join(SITE, 'package.json'))
const load = async (pkg) => import(pathToFileURL(siteRequire.resolve(pkg)).href)

// The package resolves to its CJS build, which Node's interop wraps one level
// deeper than an ESM entry point would, so unwrap the double default.
const resvgMod = await load('@resvg/resvg-js')
const { Resvg } = resvgMod.default ?? resvgMod

// Simultaneously DESIGN.md section 3 and the default `morning` palette in
// src/index.css.
const PAPER = '#F6F4EE'

const ICON = 180

// The canonical mug glyph, read from the favicon rather than redrawn so there
// is exactly one copy of the path data in the repo.
const mugSvg = readFileSync(join(LANDING, 'public', 'favicon.svg'), 'utf8')

/** The home-screen icon: the mug on paper, inset so it is not flush to the
 *  corners once iOS rounds them. Pure paths and no text, so this one goes
 *  straight through resvg and never needs satori. */
function renderIcon() {
  const inset = 26
  const box = ICON - inset * 2
  const glyph = mugSvg.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '')
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${ICON}" height="${ICON}" viewBox="0 0 ${ICON} ${ICON}">` +
    `<rect width="${ICON}" height="${ICON}" fill="${PAPER}"/>` +
    `<svg x="${inset}" y="${inset}" width="${box}" height="${box}" viewBox="0 0 128 128">${glyph}</svg>` +
    `</svg>`
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: ICON } }).render().asPng()
  writeFileSync(join(LANDING, 'public', 'apple-touch-icon.png'), png)
  return png.length
}

const iconBytes = renderIcon()
console.log(`public/apple-touch-icon.png ${ICON}x${ICON}    ${iconBytes} bytes`)
console.log('public/og.png               not generated, it is a supplied image')
