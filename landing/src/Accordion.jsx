import { useState } from 'react'

/* The FAQ accordion, shared by the homepage teaser and /faq.
 *
 * There was no accordion on this page before, so this is new construction
 * rather than a port. What it borrows is the vocabulary the topic list already
 * speaks: a full-width button row on a --rule-faint divider, a 44px minimum
 * target, the paper-raised hover, and the 260ms settle curve the FLIP reorder
 * uses. No new token.
 *
 * ---------------------------------------------------------------------------
 * THE ONE THING NOT TO CHANGE: every answer is in the markup at every state.
 *
 * Not `{open && <p>}`. The answers are the reason this page exists. They are
 * what a crawler, a retrieval system, or a reader with JavaScript off comes
 * here to find, and the homepage is thin on the literal words people search
 * for. Rendering them conditionally would put them behind a click that only a
 * browser running React can perform, which is the same as not publishing them.
 *
 * The panel is therefore collapsed by CSS (grid-template-rows: 0fr) rather
 * than by React, and `visibility` is what keeps a closed answer out of the
 * accessibility tree so it agrees with aria-expanded. index.css carries both,
 * and the <noscript> block in each page's head opens every panel for a reader
 * without JavaScript.
 * ---------------------------------------------------------------------------
 *
 * One open row at a time, held as an index, which is how TopicStudio holds its
 * open sheet. `idPrefix` keeps the teaser's ids from colliding with /faq's if
 * both ever render in one document.
 */
export default function Accordion({ items, idPrefix, headingLevel: H = 'h3' }) {
  const [open, setOpen] = useState(null)

  return (
    <ul className="faq-list">
      {items.map((item, i) => {
        const qId = `${idPrefix}-q-${i}`
        const aId = `${idPrefix}-a-${i}`
        const isOpen = open === i

        return (
          <li key={item.q}>
            {/* The button carries the heading rather than sitting inside a
                bare div, so the question list is navigable as headings. */}
            <H className="faq-h">
              <button
                type="button"
                id={qId}
                className="faq-q"
                aria-expanded={isOpen}
                aria-controls={aId}
                onClick={() => setOpen(isOpen ? null : i)}
              >
                <span className="faq-q-text">{item.q}</span>
                {/* A drawn plus that loses its upright stroke on open. Two
                    spans rather than a glyph, so it inherits the rule colour
                    and the palette transition like everything else. */}
                <span className="faq-mark" aria-hidden="true" data-open={isOpen}>
                  <span className="faq-mark-h" />
                  <span className="faq-mark-v" />
                </span>
              </button>
            </H>

            <div id={aId} role="region" aria-labelledby={qId} className="faq-panel" data-open={isOpen}>
              <div className="faq-panel-clip">
                <p className="faq-a">{answer(item)}</p>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/* An answer is one plain string, so that the structured data and llms.txt can
   carry exactly what a reader sees. Where an item names a link, the string is
   split on that substring and only the middle piece becomes an anchor. The
   copy stays single-source; the markup gets the link. */
function answer({ a, link }) {
  if (!link) return a
  const at = a.indexOf(link.text)
  if (at === -1) return a
  return (
    <>
      {a.slice(0, at)}
      <a href={link.href} className="footer-link">
        {link.text}
      </a>
      {a.slice(at + link.text.length)}
    </>
  )
}
