// Build-time Open Graph image rendering (DESIGN.md section 10). Runs only
// during `astro build`: satori turns a plain element tree into SVG, then resvg
// rasterizes it to a 1200x630 PNG. No client JavaScript is involved. Fonts are
// read from the self-hosted @fontsource packages already in node_modules, so
// the render is deterministic and needs no network.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';

// Design tokens (DESIGN.md section 3), mirrored here because satori styles are
// inline JS, not CSS. Keep in sync with src/styles/tokens.css.
const PAPER = '#F6F4EE';
const INK = '#23231F';
const MUTED = '#6B6A62';
const OXIDE = '#3F6A50';

const WIDTH = 1200;
const HEIGHT = 630;

function fontFile(pkg: string, file: string): Buffer {
  // Resolve from the project root. `astro build` runs with cwd set to site/,
  // and import.meta.url points into dist/ once this module is bundled, so
  // process.cwd() is the reliable anchor to the real node_modules.
  return readFileSync(join(process.cwd(), 'node_modules', pkg, 'files', file));
}

// Newsreader carries the wordmark and headline (the human voice); IBM Plex Mono
// carries the date line (machine metadata). satori accepts woff, not woff2.
let fontsCache: Array<{
  name: string;
  data: Buffer;
  weight: 400 | 500 | 600;
  style: 'normal';
}> | null = null;

function fonts() {
  if (!fontsCache) {
    fontsCache = [
      {
        name: 'Newsreader',
        data: fontFile('@fontsource/newsreader', 'newsreader-latin-600-normal.woff'),
        weight: 600,
        style: 'normal',
      },
      {
        name: 'Newsreader',
        data: fontFile('@fontsource/newsreader', 'newsreader-latin-400-normal.woff'),
        weight: 400,
        style: 'normal',
      },
      {
        name: 'IBM Plex Mono',
        data: fontFile('@fontsource/ibm-plex-mono', 'ibm-plex-mono-latin-500-normal.woff'),
        weight: 500,
        style: 'normal',
      },
    ];
  }
  return fontsCache;
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** "July 19, 2026" for the OG date line. Local to avoid importing astro:content. */
function formatDateLong(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** A plain element tree (satori accepts this without JSX or React). */
type El = {
  type: string;
  props: { style: Record<string, unknown>; children?: El[] | string };
};

function el(type: string, style: Record<string, unknown>, children?: El[] | string): El {
  return { type, props: { style, children } };
}

/** The OG layout: paper field, wordmark, double rule, date, headline. */
function layout(date: string, headline: string): El {
  const rule = (height: number) =>
    el('div', {
      width: '100%',
      height,
      backgroundColor: INK,
    });

  return el(
    'div',
    {
      width: WIDTH,
      height: HEIGHT,
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: PAPER,
      padding: '84px 96px',
      fontFamily: 'Newsreader',
    },
    [
      el(
        'div',
        {
          fontSize: 44,
          fontWeight: 600,
          letterSpacing: '0.01em',
          color: INK,
        },
        "Norm's Newsletter",
      ),
      el(
        'div',
        {
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          marginTop: 22,
          marginBottom: 40,
        },
        [rule(4), rule(2)],
      ),
      el(
        'div',
        {
          fontFamily: 'IBM Plex Mono',
          fontSize: 26,
          fontWeight: 500,
          letterSpacing: '0.04em',
          color: OXIDE,
          textTransform: 'uppercase',
        },
        formatDateLong(date),
      ),
      el(
        'div',
        {
          display: 'flex',
          flex: 1,
          alignItems: 'flex-start',
          marginTop: 28,
          fontSize: 62,
          fontWeight: 600,
          lineHeight: 1.12,
          color: INK,
          // Keep long headlines inside the frame.
          maxHeight: 300,
          overflow: 'hidden',
        },
        headline,
      ),
      el(
        'div',
        {
          fontFamily: 'IBM Plex Mono',
          fontSize: 22,
          color: MUTED,
          letterSpacing: '0.02em',
        },
        'A daily brief, in plain English.',
      ),
    ],
  );
}

/** Render one edition's OG image to a PNG buffer. `headline` is the
 *  headline_of_the_day for normal/quiet editions, or the notice/label for
 *  fallback editions. */
export async function renderOgPng(date: string, headline: string): Promise<Buffer> {
  const svg = await satori(layout(date, headline) as unknown as never, {
    width: WIDTH,
    height: HEIGHT,
    fonts: fonts(),
  });
  const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: WIDTH } });
  return Buffer.from(resvg.render().asPng());
}

/** The square podcast/feed artwork (DESIGN.md section 10): a ledger card,
 *  wordmark on paper with a double rule. One fixed 3000x3000 PNG, rendered at
 *  build time from the same satori pipeline so it never drifts from the site. */
const ARTWORK_SIZE = 3000;

function artworkLayout(): El {
  const rule = (height: number) =>
    el('div', { width: 1360, height, backgroundColor: INK });
  return el(
    'div',
    {
      width: ARTWORK_SIZE,
      height: ARTWORK_SIZE,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: PAPER,
      fontFamily: 'Newsreader',
    },
    [
      el('div', { fontSize: 220, fontWeight: 600, letterSpacing: '0.01em', color: INK }, "Norm's"),
      el('div', { fontSize: 220, fontWeight: 600, letterSpacing: '0.01em', color: INK, marginBottom: 60 }, 'Newsletter'),
      el('div', { display: 'flex', flexDirection: 'column', gap: 18 }, [rule(16), rule(8)]),
      el(
        'div',
        {
          fontFamily: 'IBM Plex Mono',
          fontSize: 84,
          fontWeight: 500,
          letterSpacing: '0.04em',
          color: OXIDE,
          textTransform: 'uppercase',
          marginTop: 70,
        },
        'The daily brief',
      ),
    ],
  );
}

export async function renderPodcastArtwork(): Promise<Buffer> {
  const svg = await satori(artworkLayout() as unknown as never, {
    width: ARTWORK_SIZE,
    height: ARTWORK_SIZE,
    fonts: fonts(),
  });
  const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: ARTWORK_SIZE } });
  return Buffer.from(resvg.render().asPng());
}
