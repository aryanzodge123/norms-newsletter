/* The FAQ copy, and the only place it is written.
 *
 * Four things read this file: the homepage teaser (App.jsx, the five items
 * flagged `teaser`), the /faq page (FaqPage.jsx, all of them, in this order),
 * the FAQPage JSON-LD, and the "Common questions" block in llms.txt. The last
 * two are composed from these strings at build time rather than restated
 * beside them, for the reason SPEC 15.3 (proposed) gives about llms.txt: a
 * hand-maintained copy of text that changes is a copy that stops being true,
 * and nothing in the build would catch it.
 *
 * So a copy edit happens here and nowhere else.
 *
 * Plain strings, not JSX. They are rendered as React text children, where an
 * HTML entity would show up literally, so the curly quotes and apostrophes are
 * real characters. It is also what lets the same string go into JSON-LD and a
 * plain-text file untouched.
 *
 * No em dashes (CLAUDE.md rule 7). The supplied copy carried eleven; each one
 * is a full stop or a comma here. README.md records the divergence.
 */

/* The published daily brief this app grew out of. Named once, used by the
 * footer link row and by the origin-story answer below. */
export const THE_BRIEF = 'https://aryanzodge123.github.io/norms-newsletter/'

/* `teaser: true` puts an item on the homepage. `link` turns one substring of
 * the answer into an anchor at render time: the answer stays a single plain
 * string, so the structured data and llms.txt carry the same words a reader
 * sees, with no second copy to drift. */
export const FAQ_ITEMS = [
  {
    q: 'What is Norm’s Newsletter?',
    a:
      'One edition a day, built only from the topics you track, and finished when you ' +
      'finish it. Norm reads everything filed against your topics, scores it for ' +
      'relevance, filters the duplicates, and hands you a brief at the time you choose ' +
      'to read it, not the moment it happened.',
  },
  {
    q: 'How is this different from a news app or an RSS reader?',
    a:
      'Most of them are built to keep you scrolling. Norm is built to stop. You set how ' +
      'much each topic deserves, from “only if it’s genuinely big” to “everything, every ' +
      'morning”, and once you’ve read your edition, there’s nothing waiting behind it.',
  },
  {
    q: 'Who, or what, decides what makes the cut?',
    a:
      'A system that scores every story on how central it is to what’s actually ' +
      'happening, not how many outlets picked it up. Duplicate coverage gets filtered ' +
      'before it ever reaches your edition, so you’re never reading the same story five ' +
      'times under five different headlines.',
  },
  {
    q: 'Is this AI-written, or is there a real person behind it?',
    teaser: true,
    link: { text: 'aryanzodge123.github.io/norms-newsletter', href: THE_BRIEF },
    a:
      'Norm assembles and files each edition, but this isn’t a landing page for an idea ' +
      'that doesn’t exist yet. Before norm.news, there was just the brief: the same ' +
      'story-clustering and sourcing, running automatically every morning, compiled at ' +
      '6:00 am ET, no interface, no personalization, just the finished newsletter, every ' +
      'day. Aryan Zodge built that first, then built norm.news around it: the same ' +
      'scoring and clustering, now wrapped in the controls that make it yours. Your ' +
      'topics, your length, delivered when you want to read it. The original is still ' +
      'running, methodology and all, at aryanzodge123.github.io/norms-newsletter.',
  },
  {
    /* Verbatim NORM_POINTS (App.jsx), which the Norm section already renders.
       Restated here rather than imported: this file must not depend on the
       page's components, and the two say the same thing on purpose. */
    q: 'What does “Ask Norm” actually have access to?',
    teaser: true,
    a:
      'Only your editions, and the sources behind them. Not the open internet. Every ' +
      'lookup is scoped to one reader on the server, and the sandbox it runs in holds no ' +
      'database credentials at all. Ask a question, get an answer with a receipt: which ' +
      'editions, how many sources.',
  },
  {
    q: 'Does every story link back to a source?',
    a:
      'Yes, every one. Norm translates scattered updates into a clear narrative, but it ' +
      'never shortcuts the sourcing. Each story links directly back to the original ' +
      'reporting so you can check it yourself.',
  },
  {
    q: 'How often are sources checked?',
    a:
      'Every hour, around the clock, from everything Norm subscribes to, so nothing sits ' +
      'stale for a full day before your edition is filed overnight.',
  },
  {
    q: 'Can I change my topics and length later?',
    teaser: true,
    a:
      'Yes. Every topic carries its own weight, from “nice to have” to “keep me current,” ' +
      'and you can drag the running order, adjust length, or add a new section any time. ' +
      'Length changes the paper, not the archive. Everything Norm has ever filed stays ' +
      'searchable.',
  },
  {
    q: 'What time do I get my edition?',
    teaser: true,
    a:
      'Whenever you tell it to arrive. Pick a time, and both the edition and the app ' +
      'itself switch to match: an evening read comes in the dark palette, the way you’d ' +
      'actually be holding it then.',
  },
  {
    q: 'When does it launch, and what happens to my email if I sign up?',
    teaser: true,
    a:
      'Norm is in the final stretch of being built. Your email is used only to tell you ' +
      'how it’s coming along and when it opens. It is never sold, shared, or used to ' +
      'advertise anything. Reply to any message with the word OFF and you’re removed.',
  },
]

export const FAQ_TEASER = FAQ_ITEMS.filter((item) => item.teaser)
