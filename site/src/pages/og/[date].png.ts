import type { APIContext } from 'astro';
import { allEditions } from '../../lib/editions';
import { renderOgPng } from '../../lib/og';

// One prerendered Open Graph PNG per edition (DESIGN.md section 10). This is a
// build-time endpoint: getStaticPaths enumerates the editions collection and
// each route renders a 1200x630 PNG with satori + resvg. No live pipeline and
// no client JavaScript are involved; the site builds from committed editions.

export async function getStaticPaths() {
  const editions = await allEditions();
  return editions.map((e) => {
    const d = e.data;
    const headline =
      d.edition_type === 'fallback'
        ? 'Abbreviated edition'
        : d.headline_of_the_day;
    return { params: { date: d.date }, props: { date: d.date, headline } };
  });
}

interface Props {
  date: string;
  headline: string;
}

export async function GET(context: APIContext): Promise<Response> {
  const { date, headline } = context.props as Props;
  const png = await renderOgPng(date, headline);
  return new Response(png, {
    headers: {
      'Content-Type': 'image/png',
      'Cache-Control': 'public, max-age=31536000, immutable',
    },
  });
}
