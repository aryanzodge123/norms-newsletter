import { getCollection, type CollectionEntry } from 'astro:content';

export type Edition = CollectionEntry<'editions'>;
export type EditionData = Edition['data'];

/** All editions, newest first (date is YYYY-MM-DD so string sort is safe). */
export async function allEditions(): Promise<Edition[]> {
  const entries = await getCollection('editions');
  return entries.sort((a, b) => (a.data.date < b.data.date ? 1 : -1));
}

/** The most recent edition, rendered at `/`. */
export async function latestEdition(): Promise<Edition> {
  const all = await allEditions();
  if (all.length === 0) {
    throw new Error('No editions found in content/editions/');
  }
  return all[0];
}

/** Prev (older) and next (newer) neighbours for the prev/next bar. */
export async function neighbours(
  date: string,
): Promise<{ prev: Edition | null; next: Edition | null }> {
  const all = await allEditions(); // newest first
  const i = all.findIndex((e) => e.data.date === date);
  if (i === -1) return { prev: null, next: null };
  return {
    next: i > 0 ? all[i - 1] : null,
    prev: i < all.length - 1 ? all[i + 1] : null,
  };
}

/** Slugify a section name for a topic filter URL: "Artificial intelligence" -> "artificial-intelligence". */
export function topicSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** All topics (section names) present across editions, with their editions. */
export async function topicsWithEditions(): Promise<Map<string, Edition[]>> {
  const all = await allEditions();
  const map = new Map<string, Edition[]>();
  for (const e of all) {
    if (e.data.edition_type === 'fallback') continue;
    const names = new Set(e.data.sections.map((s) => s.name));
    for (const name of names) {
      const list = map.get(name) ?? [];
      list.push(e);
      map.set(name, list);
    }
  }
  return map;
}

// ---- formatting -----------------------------------------------------------

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** "July 20, 2026" for the masthead. */
export function formatDateLong(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** "Jul 20" for archive rows. */
export function formatDateShort(date: string): string {
  const [, m, d] = date.split('-').map(Number);
  return `${MONTHS[m - 1].slice(0, 3)} ${d}`;
}

/** "2026" grouping key / "July 2026" heading for the archive. */
export function monthKey(date: string): string {
  const [y, m] = date.split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** Glance read time: 12s per point, rounded to a friendly 15s value. */
export function readTimeLabel(points: number): string {
  const seconds = Math.max(15, Math.round((points * 12) / 15) * 15);
  return `${seconds}-second read`;
}

/** Audio length "9:08" from seconds. */
export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
