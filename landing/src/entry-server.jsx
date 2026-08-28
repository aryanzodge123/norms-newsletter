/* The prerender entry (SPEC 15.2, proposed).
   scripts/prerender.mjs bundles this file, renders <App/> to static markup,
   and writes the result into dist/index.html.

   It deliberately does not import index.css. The client entry owns the
   stylesheet, and pulling it in here would make the SSR bundle carry Tailwind
   and the font faces for no reason: nothing in this pass paints.

   The copy constants are re-exported because llms.txt is composed from them
   rather than written alongside them. A hand-maintained summary of a page that
   changes is a summary that stops being true. */

export { default as App } from './App.jsx'
export { BENEFITS, NS_TOPICS, NS_LEN, STOPS, STAGES, NORM_POINTS } from './App.jsx'

/* The second page, and its copy. FAQ_ITEMS feeds three things at build time:
   the FAQPage structured data, the "Common questions" block in llms.txt, and
   the page itself, which is why it is exported rather than read from a copy. */
export { default as FaqPage } from './FaqPage.jsx'
export { FAQ_ITEMS } from './faq-content.js'

/* The third and fourth pages, and their copy. POSTS feeds four things at
   build time: the /blog index, the post document, the Blog and BlogPosting
   JSON-LD, and the Links block in llms.txt, for the same reason FAQ_ITEMS is
   exported rather than read from a copy. */
export { default as BlogPage } from './BlogPage.jsx'
export { default as PostPage } from './PostPage.jsx'
export { POSTS } from './blog-content.js'
