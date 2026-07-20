import type { APIContext } from 'astro';
import { allEditions } from '../lib/editions';
import { href, editionPath } from '../lib/urls';

// RSS 2.0 + iTunes podcast feed (DESIGN.md section 7). Every self URL derives
// from context.site (SPEC 6.6); nothing is hardcoded. Per-episode audio
// enclosures appear once audio ships (M6); until then `audio` is null and no
// enclosure is emitted.

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// RFC 822 date at ~6:00 am ET (10:00 UTC) for the edition's date.
function rfc822(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d, 10, 0, 0));
  const dow = DOW[dt.getUTCDay()];
  const mon = MON[dt.getUTCMonth()];
  const dd = String(dt.getUTCDate()).padStart(2, '0');
  return `${dow}, ${dd} ${mon} ${dt.getUTCFullYear()} 10:00:00 GMT`;
}

export async function GET(context: APIContext): Promise<Response> {
  const site = context.site;
  if (!site) throw new Error('Astro.site is undefined');
  const abs = (p: string) => new URL(href(p), site).href;

  const editions = await allEditions();

  const items = editions
    .map((e) => {
      const d = e.data;
      const link = abs(editionPath(d.date));
      const pub = rfc822(d.date);

      let title: string;
      let description: string;
      let audio: { url: string; duration_seconds: number; size_bytes: number } | null = null;

      if (d.edition_type === 'fallback') {
        title = 'Abbreviated edition';
        description = d.notice;
      } else {
        title = d.headline_of_the_day;
        description = d.key_points.map((p) => `- ${p.text}`).join('\n');
        audio = d.audio;
      }

      // Enclosure length is the real byte size from edition.json audio.size_bytes
      // (a required field). The audio URL is the R2-hosted file set by the
      // pipeline, the one self URL that does not derive from astro.config.
      const enclosure = audio
        ? `\n      <enclosure url="${esc(audio.url)}" length="${audio.size_bytes}" type="audio/mpeg" />` +
          `\n      <itunes:duration>${audio.duration_seconds}</itunes:duration>`
        : '';

      return `    <item>
      <title>${esc(title)}</title>
      <link>${esc(link)}</link>
      <guid isPermaLink="true">${esc(link)}</guid>
      <pubDate>${pub}</pubDate>
      <description>${esc(description)}</description>${enclosure}
    </item>`;
    })
    .join('\n');

  const homeLink = abs('/');
  const feedLink = abs('/feed.xml');
  // Podcast directories reject SVG artwork, so the feed points at the 3000x3000
  // PNG in public/ (DESIGN.md section 10). URL derives from astro.config.
  const artwork = abs('/podcast-artwork.png');
  const desc =
    "A daily brief on technology, AI, business, finance, politics, and the world. Written in plain English. Compiled automatically every morning.";

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Norm's Newsletter</title>
    <link>${esc(homeLink)}</link>
    <atom:link href="${esc(feedLink)}" rel="self" type="application/rss+xml" />
    <description>${esc(desc)}</description>
    <language>en</language>
    <itunes:author>Norm</itunes:author>
    <itunes:summary>${esc(desc)}</itunes:summary>
    <itunes:owner>
      <itunes:name>Norm</itunes:name>
      <itunes:email>aryanzodge1@gmail.com</itunes:email>
    </itunes:owner>
    <itunes:category text="News" />
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="${esc(artwork)}" />
${items}
  </channel>
</rss>
`;

  return new Response(xml, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
}
