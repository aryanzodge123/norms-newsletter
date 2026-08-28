import { Footer, Header, Reveal } from './App.jsx'
import { POSTS } from './blog-content.js'

/* /blog, the index.
 *
 * The third document, and a document rather than a route for the same reason
 * /faq is one (SPEC 15.1, proposed): a client that runs no JavaScript receives
 * the whole page. scripts/prerender.mjs writes this into dist/blog.html.
 *
 * PROPOSED-SPEC-DISCOVERY.md listed a blog under what the domain deliberately
 * does not have. That line is reversed there rather than contradicted here.
 *
 * It was an empty-state page until the first post existed. It is now a list,
 * and the list is one row, which is the honest shape: rows come from POSTS, so
 * a second post is a second entry in blog-content.js and nothing here changes.
 *
 * No delivery dial on this page, so nothing sets data-tod and the :root
 * palette applies. That is the morning paper, and it takes no code to get.
 */
export default function BlogPage() {
  return (
    <div className="tod">
      <Header />
      <main>
        <section className="pad-x pt-14 pb-6">
          <div className="mx-auto max-w-[1140px]">
            <Reveal>
              <p className="label-rule eyebrow">Blog</p>
              {/* Both lines run the full container, between the label rule
                  above them and the first post row below, so the page is built
                  on one set of edges from the eyebrow down to the footer. */}
              <h1 className="display mt-8 text-[clamp(40px,8.6vw,104px)] max-[720px]:text-balance">
                Notes on building Norm.
              </h1>
              <p className="mt-6 text-pretty text-[clamp(17px,1.5vw,21px)] leading-[1.5] text-[var(--ink-soft)]">
                What we are making, what we got wrong, and why the news reads the way it does.
                Written when there is something worth saying, which is not the same as often.
              </p>
            </Reveal>
          </div>
        </section>

        <section className="pad-x pb-20">
          <div className="mx-auto max-w-[1140px]">
            {/* One Reveal around the whole list, like the accordion on /faq.
                Newest first, which POSTS is already in.

                A card per post, in the shape DESIGN.md section 4 gives
                StoryCard: title, one line of summary, then a meta row with the
                metadata on the left and the way in on the right. The whole
                card is the link, so there is one target rather than a title
                that navigates sitting inside a box that does not. */}
            <Reveal delay={80} className="post-list mt-10">
              {POSTS.map((post) => (
                <a key={post.slug} href={`/blog/${post.slug}`} className="post-card">
                  <h2 className="display max-w-[24ch] text-[clamp(24px,3vw,34px)] max-[720px]:text-balance">
                    {post.title}
                  </h2>
                  <p className="mt-4 max-w-[62ch] text-pretty text-[17px] leading-[1.6] text-[var(--ink-soft)]">
                    {post.dek}
                  </p>
                  {/* The meta row. Mono metadata left, the way in right, which
                      is StoryCard's own arrangement with the score and the
                      source count swapped for the two numbers a post has. */}
                  <div className="mt-7 flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2">
                    <span className="eyebrow">
                      {post.dateLabel} &middot; {post.minutes} minute read
                    </span>
                    <span className="post-card-go text-[13px] font-medium">
                      Read the post
                      {/* The header's chevron, at the weight it draws there:
                          the stroke is in viewBox units, so it is scaled up to
                          hold the same 1.9px on screen at this size. */}
                      <svg viewBox="0 0 12 20" width="8" height="13" aria-hidden="true" focusable="false">
                        <path
                          d="M2 1l8 9-8 9"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                  </div>
                </a>
              ))}
            </Reveal>

            <Reveal delay={140} className="mt-10">
              <p className="eyebrow">
                <a href="/" className="footer-link">
                  &larr; Back to the front page
                </a>{' '}
                &middot;{' '}
                <a href="/faq" className="footer-link">
                  Frequently asked questions
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
