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
