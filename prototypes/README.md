# prototypes/

The Claude Design export of the Norm's Newsletter app, exported 2026-08-02 and
committed 2026-08-04.

**This governs nothing.** SPEC.md and DESIGN.md are authoritative. These files
are a design medium, not production code, and the app's visual system is still
unspecified: DESIGN.md covers the site only. Where anything here disagrees with
SPEC.md, SPEC.md wins.

It is committed because SPEC decisions #45 through #47 and part of #56 were
taken by reading it, and because `ds/` is the closest thing that exists to an
app visual system. It previously lived only in a Downloads folder.

## What is here

| Path | What it is |
| --- | --- |
| `App Interface.dc.html` | The live prototype: Today, Archive, More, the reader, Norm chat, the mini-player |
| `App Onboarding.dc.html` | The live prototype: intro, name, topics with weights, delivery time, plan |
| `Norms Newsletter *.dc.html` | Annotated design documents that embed the two above |
| `ds/` | The design system as standalone files: 18 components, 3 foundations |
| `norm-editions.js` | The data, generated from `site/content/editions/*.json` |
| `support.js`, `ios-frame.jsx` | The design-canvas runtime and the phone frame |
| `github.md` | The sync log, including a screen-to-source map |

Two things from the original export are deliberately not here: the export's own
copy of `site/content/editions/`, which duplicates this repo, and `screenshots/`,
which held working files.

`norm-editions.js` **is** included even though it is generated, because the
regenerator lives in Claude Design rather than in this repo. Without it the
prototype silently falls back to placeholder data.

## Running it

It needs an HTTP server. It will not work from `file://`.

```
python3 -m http.server 8055 --directory prototypes
```

Then open `http://localhost:8055/App%20Interface.dc.html`.

`App Interface.dc.html` loads its data inside `componentDidMount`:

```js
import("./norm-editions.js")
  .then(m => { window.NORM_EDITIONS = m.EDITIONS; this.forceUpdate(); })
  .catch(() => {});
```

That is a real ES module. A dynamic import from a `file://` page is
cross-origin from an opaque origin, so the browser blocks it and the `.catch`
swallows the failure. **The page still renders, with hardcoded placeholder
data.** It looks right and is wrong, which is the whole reason for the server.

To confirm the data actually loaded, check that the masthead matches the first
entry in `norm-editions.js` and that the Archive tab shows the full edition
count.

`support.js` also fetches React, ReactDOM and Babel from unpkg at runtime, plus
fonts from Google, so it needs network access as well as a server.

## Reading it

The export's own README says to read the HTML and CSS directly rather than
screenshotting, because dimensions, colors and layout rules are all in the
source. That is good advice: the data contracts and state shapes are literal
constants near the top of each file, and they are what made the reconciliation
in APP-ARCHITECTURE.md section 15b possible.

## What the prototype shows that v1 will not ship

Recorded so nobody implements them from these files:

- **Saved chat history.** Deferred by decision #54.
- **Free-text topics**, sold as a Pro benefit. Out of scope, SPEC 14.3.
- **The Sunday retrospective.** Named in SPEC 14.10, not specified.
- **The edition number** ("No. 056"), which runs through the masthead, the push
  copy and the agent's opening line. Removed by decision #53.
- **A 20-topic menu.** v1 ships the existing ten, SPEC 14.3.
- **A direct payment path** (`payMode: "direct"`). In-app purchase only,
  decision #47.

See APP-ARCHITECTURE.md section 15b for the port notes, including the four
things here that have no React Native equivalent.
