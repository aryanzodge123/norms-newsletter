import { Footer, Header, Reveal } from './App.jsx'
import { postBySlug } from './blog-content.js'

/* One post, as its own document.
 *
 * The fourth page, and a document rather than a route for the reason /faq and
 * /blog are documents: SPEC 15.1 (proposed) wants every word in the response
 * body, and public/404.html exists specifically to defeat the SPA fallback, so
 * a client route would 404 on a direct load anyway. scripts/prerender.mjs
 * writes this into dist/blog/put-my-phone-down.html, which Cloudflare Pages
 * serves at /blog/put-my-phone-down with no redirect, the same way faq.html is
 * served at /faq.
 *
 * The slug is named here rather than passed in. There is one post, and a
 * second one is a second five-line file beside this one plus its entry in
 * PAGES; parameterising a route this app does not have would be building the
 * router SPEC 15.1 exists to avoid.
 *
 * No eyebrow above the headline, unlike /faq and /blog. Those are supporting
 * pages that need to say which one they are. This is an article, and an
 * article says what it is by having a headline and a dateline under it, which
 * is also the masthead idiom DESIGN.md section 4 sets for the site.
 *
 * No delivery dial on this page, so nothing sets data-tod and the :root
 * palette applies. That is the morning paper, and it takes no code to get.
 */
const POST = postBySlug('put-my-phone-down')

export default function PostPage() {
  return (
    <div className="tod">
      <Header />
      <main>
        <article className="post-article pad-x pt-14 pb-8">
          <div className="mx-auto max-w-[1140px]">
            {/* The title block runs the full container, edge to edge. No
                measure on either line: a headline and a standfirst are the
                page's masthead rather than its reading matter, and a masthead
                spans the paper. The running text below is where the measure
                comes back.

                No text-balance on the headline for the same reason. Balancing
                evens the two lines and pulls the first one off the right
                margin, which is the margin this block exists to reach.

                Below 720 it comes back. There is no margin worth reaching on a
                phone, the headline runs to three lines there, and unbalanced
                the third was one word. */}
            <Reveal>
              <h1 className="display text-[clamp(34px,5.2vw,72px)] max-[720px]:text-balance">{POST.title}</h1>
              <p className="mt-6 text-pretty text-[clamp(18px,1.7vw,24px)] leading-[1.45] text-[var(--ink-soft)]">
                {POST.dek}
              </p>
            </Reveal>

            {/* The dateline, and then the rule under it. A rule closes a
                masthead rather than opening one: byline left, date right, and
                the double rule beneath drawing a line under the whole block
                before the story starts. */}
            <Reveal delay={80} className="mt-10">
              <div className="eyebrow flex flex-wrap justify-between gap-x-8 gap-y-2 pb-3">
                <span>{POST.author}</span>
                <span>
                  {POST.dateLabel} &middot; {POST.minutes} minute read
                </span>
              </div>
              <hr className="rule-double" />
            </Reveal>

            {/* One Reveal around the whole post. Fifteen staggered paragraphs
                would be a lot of motion for a page somebody came to in order
                to read, which is the same call /faq makes about its ten rows.

                Centred on the same 720 as the headline above it, so the two
                share an edge on both sides. */}
            <Reveal delay={140} className="post-body mx-auto mt-12 max-w-[720px]">
              {POST.body.map((block, i) => {
                if (block.kind === 'pull') {
                  return (
                    <p key={i} className="post-pull">
                      {block.text}
                    </p>
                  )
                }
                if (block.kind === 'close') {
                  return (
                    <p key={i} className="post-close">
                      {block.text}
                    </p>
                  )
                }
                /* The drop cap is the front page's, on the one paragraph that
                   opens a body of text, which is what it was cut for. */
                return (
                  <p key={i} className={i === 0 ? 'dropcap' : undefined}>
                    {block.text}
                  </p>
                )
              })}
            </Reveal>
          </div>
        </article>

        <section className="pad-x pt-4 pb-20">
          <div className="mx-auto max-w-[1140px]">
            {/* No rule here. The footer opens with the page's other
                rule-double a hundred pixels below, and two of them that close
                together read as one mistake rather than two endings. /faq
                ends on this line alone for the same reason. */}
            <Reveal delay={60} className="mx-auto max-w-[720px]">
              <p className="eyebrow">
                <a href="/blog" className="footer-link">
                  &larr; All posts
                </a>{' '}
                &middot;{' '}
                <a href="/" className="footer-link">
                  The front page
                </a>
              </p>
            </Reveal>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  )
}
