import { Footer, Header, Reveal } from './App.jsx'
import Accordion from './Accordion.jsx'
import { FAQ_ITEMS, THE_BRIEF } from './faq-content.js'

/* /faq, the page.
 *
 * A second document rather than a second route. There is no router here and
 * adding one would break the contract in SPEC 15.1 (proposed): a client that
 * runs no JavaScript receives the whole page. This file is prerendered to
 * static markup by scripts/prerender.mjs and written into dist/faq/index.html,
 * exactly as App is written into dist/index.html.
 *
 * Header and Footer are imported rather than reimplemented, so the pages
 * cannot drift. The import runs one way: App.jsx knows nothing about this file.
 *
 * No delivery dial on this page, so nothing sets data-tod on the root and the
 * :root palette applies. That is the morning paper, which is the right default
 * and takes no code to get.
 */
export default function FaqPage() {
  return (
    <div className="tod">
      <Header />
      <main>
        <section className="pad-x pt-14 pb-6">
          <div className="mx-auto max-w-[1140px]">
            <Reveal>
              <p className="label-rule eyebrow">Questions</p>
              {/* Held below the homepage h1. This is a supporting page and
                  should not out-shout the front page it links back to. */}
              <h1 className="display mt-8 max-w-[16ch] text-[clamp(40px,6vw,60px)]">
                What Norm does, and what it does not.
              </h1>
              <p className="mt-5 max-w-[48ch] text-[17px] leading-[1.6] text-[var(--ink-soft)]">
                Ten questions, answered plainly. If yours is not here, write to{' '}
                <a href="mailto:norm@norm.news" className="footer-link">
                  norm@norm.news
                </a>{' '}
                and it probably should be.
              </p>
            </Reveal>
          </div>
        </section>

        <section className="pad-x pb-20">
          <div className="mx-auto max-w-[1140px]">
            {/* One Reveal around the whole list. Ten staggered rows would be a
                lot of motion for a page somebody came to in order to read. */}
            <Reveal delay={80} className="max-w-[820px]">
              <Accordion items={FAQ_ITEMS} idPrefix="faq" headingLevel="h2" />
            </Reveal>

            <Reveal delay={140} className="mt-10 max-w-[820px]">
              <p className="eyebrow">
                <a href="/" className="footer-link">
                  &larr; Back to the front page
                </a>{' '}
                &middot;{' '}
                <a href={THE_BRIEF} className="footer-link" target="_blank" rel="noopener">
                  The Original Daily Brief
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
