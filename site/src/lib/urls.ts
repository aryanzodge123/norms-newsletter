// The only way components emit a self URL. Everything derives from
// astro.config (SPEC 6.6): import.meta.env.BASE_URL is the configured `base`
// and Astro.site is the configured `site`. No self URL is ever hardcoded.

// Astro sets BASE_URL from the `base` config, e.g. "/norms-newsletter/".
const BASE = import.meta.env.BASE_URL;

/** Root-relative URL for an internal path, base-prefixed exactly once. */
export function href(path = '/'): string {
  const b = BASE.endsWith('/') ? BASE.slice(0, -1) : BASE;
  const p = path.startsWith('/') ? path : `/${path}`;
  const joined = `${b}${p}`;
  // Keep the single trailing slash for directory-style routes; leave files
  // (feed.xml, .png) and the bare root alone.
  return joined;
}

/** Absolute URL for an internal path, built from Astro.site. */
export function abs(path: string, site: URL | undefined): string {
  if (!site) {
    throw new Error('Astro.site is undefined; set `site` in astro.config.mjs');
  }
  return new URL(href(path), site).href;
}

/** Permalink path for an edition date (YYYY-MM-DD) -> /YYYY/MM/DD/. */
export function editionPath(date: string): string {
  const [y, m, d] = date.split('-');
  return `/${y}/${m}/${d}/`;
}

/** Build-time Open Graph image path for an edition date -> /og/YYYY-MM-DD.png.
 *  Matches the getStaticPaths route in src/pages/og/[date].png.ts. The PNG is a
 *  file, not a directory route, so it keeps its extension and no trailing slash. */
export function ogImagePath(date: string): string {
  return `/og/${date}.png`;
}
