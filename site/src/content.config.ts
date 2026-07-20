import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// Front-end analogue of src/editor/schema.py. Mirrors the canonical
// edition.json schema (SPEC 6.5) so a malformed edition fails the build
// instead of rendering broken HTML. The edition data lives in
// content/editions/ (SPEC 6.6); M4 seeds it from the fixtures, M5 commits
// the real editions there.

const DATE = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'date must be YYYY-MM-DD');

const source = z.object({
  name: z.string(),
  url: z.string().url(),
});

const quote = z
  .object({
    text: z.string(),
    attribution: z.string(),
    source_url: z.string().url(),
  })
  .strict();

const article = z
  .object({
    background: z.string(),
    what_happened: z.string(),
    why_it_matters: z.string(),
    quote: quote.nullable().optional(),
  })
  .strict();

const story = z
  .object({
    cluster_id: z.string(),
    slug: z.string(),
    title: z.string(),
    summary: z.string(),
    score: z.number(),
    sources: z.array(source).min(1),
    // Null when the writer stage failed for this story: renders as a plain
    // card with no expand affordance (DESIGN.md StoryCard).
    article: article.nullable(),
  })
  .strict();

const section = z
  .object({
    name: z.string(),
    stories: z.array(story),
  })
  .strict();

const keyPoint = z
  .object({
    text: z.string(),
    topic: z.string(),
  })
  .strict();

const brieflyItem = z
  .object({
    title: z.string(),
    url: z.string().url(),
    topic: z.string(),
  })
  .strict();

const stats = z
  .object({
    items_ingested: z.number(),
    clusters_considered: z.number(),
    stories_run: z.number(),
    sources: z.number(),
    sections_held: z.number(),
  })
  .strict();

// normal and quiet share the full shape; only the literal differs.
const fullEdition = {
  date: DATE,
  edition_number: z.number(),
  headline_of_the_day: z.string(),
  key_points: z.array(keyPoint),
  audio: z
    .object({
      url: z.string().url(),
      duration_seconds: z.number(),
      size_bytes: z.number().int().positive(),
    })
    .strict()
    .nullable(),
  sections: z.array(section),
  briefly: z.array(brieflyItem),
  stats,
};

const normalEdition = z.object({ edition_type: z.literal('normal'), ...fullEdition }).strict();
const quietEdition = z.object({ edition_type: z.literal('quiet'), ...fullEdition }).strict();

// Fallback is a genuinely different, reduced shape (SPEC 6.5 / section 7).
const fallbackEdition = z
  .object({
    edition_type: z.literal('fallback'),
    date: DATE,
    edition_number: z.number(),
    notice: z.string(),
    stories: z.array(
      z
        .object({
          rank: z.number(),
          title: z.string(),
          score: z.number(),
          url: z.string().url(),
          source: z.string(),
        })
        .strict(),
    ),
  })
  .strict();

const editionSchema = z.discriminatedUnion('edition_type', [
  normalEdition,
  quietEdition,
  fallbackEdition,
]);

const editions = defineCollection({
  loader: glob({ pattern: '*.json', base: './content/editions' }),
  schema: editionSchema,
});

export const collections = { editions };
