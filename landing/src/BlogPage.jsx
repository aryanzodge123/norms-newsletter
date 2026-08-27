import { Footer, Header, Reveal } from './App.jsx'

/* /blog, the page.
 *
 * The third document, and a document rather than a route for the same reason
 * /faq is one (SPEC 15.1, proposed): a client that runs no JavaScript receives
 * the whole page. scripts/prerender.mjs writes this into dist/blog.html.
 *
 * PROPOSED-SPEC-DISCOVERY.md listed a blog under what the domain deliberately
 * does not have. That line is reversed there rather than contradicted here.
 *
 * There are no posts yet, and this file says so in one sentence rather than
 * standing up a post list, a feed and a date format for zero entries. When
 * the first post exists, the copy below is what it replaces.
 *
 * No delivery dial on this page, so nothing sets data-tod and the :root
 * palette applies. That is the morning paper, and it takes no code to get.
 */
export default function BlogPage() {
  return (
    <div className="tod">
      <Header />
      <main>
        <section className="pad-x pt-14 pb-24">
          <div className="mx-auto max-w-[1140px]">
            <Reveal>
              <p className="label-rule eyebrow">Blog</p>
              {/* Held below the homepage h1, like /faq. A supporting page
                  should not out-shout the front page it links back to. */}
              <h1 className="display mt-8 max-w-[16ch] text-[clamp(40px,6vw,60px)]">
                Nothing published yet.
              </h1>
              <p className="mt-5 max-w-[48ch] text-[17px] leading-[1.6] text-[var(--ink-soft)]">
                There aren&rsquo;t any posts just yet, but there is a lot we want to talk about, so
                stay tuned. This is where the thinking behind Norm will go: what we are building,
                what we got wrong, and why the news reads the way it does.
              </p>
            </Reveal>

            <Reveal delay={80} className="mt-10 max-w-[820px]">
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
