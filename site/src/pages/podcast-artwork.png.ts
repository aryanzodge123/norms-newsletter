import type { APIContext } from 'astro';
import { renderPodcastArtwork } from '../lib/og';

// The 3000x3000 podcast/feed artwork (DESIGN.md section 10), referenced by the
// feed's itunes:image. Prerendered at build time from the same satori + resvg
// pipeline as the per-edition OG images, so it stays in the ledger style and
// needs no committed binary. Podcast directories require a PNG here, not SVG.

export async function GET(_context: APIContext): Promise<Response> {
  const png = await renderPodcastArtwork();
  return new Response(png, {
    headers: {
      'Content-Type': 'image/png',
      'Cache-Control': 'public, max-age=31536000, immutable',
    },
  });
}
