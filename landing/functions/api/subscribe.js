// The waiting list endpoint. POST /api/subscribe.
//
// A Cloudflare Pages Function, so it runs on the same origin as the page and
// there is no CORS to configure. It does two things: write the address to D1
// (schema.sql) and send one confirmation.
//
// **The order of those two is load-bearing.** The row is written first, and a
// failed send still returns success to the browser with `emailed_at` left
// null. The signup is the thing that cannot be lost; the confirmation can be
// sent again later, and the null column is what makes a failed one visible in
// `npm run waitlist` rather than silent. This is CLAUDE.md rule 3's
// containment principle applied to a form: contain the failure at the smallest
// scope, and never let a mail provider outage cost a subscriber.
//
// POST is the only method with an implementation, and onRequest below turns
// everything else into a 405. Leaving it unhandled is not the same thing: an
// unmatched path in Pages falls through to the static assets and answers a GET
// /api/subscribe with 200 and the landing page, which reads like an endpoint
// that exists and does nothing. There is no read path here at all. The list is
// seen through `npm run waitlist`, which needs a Cloudflare account.
//
// This endpoint is not covered by SPEC.md. It is the first thing in the
// project to hold personal data, and PROPOSED-SPEC.md in this directory is the
// addition it owes. Read that before extending it.

const RESEND_API = 'https://api.resend.com/emails'

// Enough for any address plus the honeypot. A body larger than this is not a
// signup, so it is refused before it is parsed rather than after.
const MAX_BODY = 1024

// RFC 5321's limit. Longer than this cannot be delivered anywhere.
const MAX_EMAIL = 254

export async function onRequestPost({ request, env }) {
  if (!env.DB) {
    // The binding is missing, which is a deploy problem and not the visitor's.
    // 500 rather than a quiet success: the form's error state tells them to
    // write to us directly, which is the only path that still works.
    console.error('subscribe: no DB binding')
    return json({ ok: false }, 500)
  }

  const body = await readJson(request)
  if (!body) return json({ ok: false }, 400)

  // The honeypot. The real form renders `company` off screen and leaves it
  // empty; a bot filling every field trips it. Answer 200 and write nothing,
  // because telling a bot it failed only teaches it to try again differently.
  if (typeof body.company === 'string' && body.company.trim() !== '') {
    return json({ ok: true })
  }

  const email = normalize(body.email)
  if (!email) return json({ ok: false }, 400)

  const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')

  // Insert-or-nothing in one statement. `changes` is 0 when the address was
  // already on the list, and that is the whole duplicate story: no second row
  // and, below, no second mail. One address receives at most one message from
  // this endpoint ever, which is what stops the form being an email cannon
  // pointed at whoever an attacker types in. It also makes a repeat submission
  // indistinguishable from a first one, so the endpoint cannot be used to test
  // whether a given person signed up.
  let inserted
  try {
    const result = await env.DB.prepare(
      'INSERT INTO waitlist (email, created_at, source) VALUES (?1, ?2, ?3) ' +
        'ON CONFLICT(email) DO NOTHING',
    )
      .bind(email, now, 'landing')
      .run()
    inserted = result.meta.changes > 0
  } catch (err) {
    // Note what failed, never who. Cloudflare's logs are not one of the places
    // enumerated for deletion, so an address must not end up in them.
    console.error(`subscribe: insert failed: ${err}`)
    return json({ ok: false }, 500)
  }

  if (!inserted) return json({ ok: true })

  // From here the person is on the list and the answer is 200 whatever
  // happens next.
  const sent = await sendConfirmation(env, email)
  if (sent) {
    try {
      await env.DB.prepare('UPDATE waitlist SET emailed_at = ?1 WHERE email = ?2')
        .bind(new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'), email)
        .run()
    } catch (err) {
      // The mail went out and the row exists. All this loses is the record
      // that it went out, which makes the export overstate the backlog rather
      // than understate it. Not worth failing the request over.
      console.error(`subscribe: emailed_at update failed: ${err}`)
    }
  }

  return json({ ok: true })
}

/** Everything that is not a POST. Pages routes a method to its own handler
 *  first and only falls back to this one, so onRequestPost above still owns
 *  POST and this never sees it. */
export function onRequest() {
  return new Response(null, { status: 405, headers: { allow: 'POST' } })
}

/* ------------------------------------------------------------------ input */

async function readJson(request) {
  const declared = Number(request.headers.get('content-length'))
  if (Number.isFinite(declared) && declared > MAX_BODY) return null

  let text
  try {
    text = await request.text()
  } catch {
    return null
  }
  // Checked again against the real length, because content-length is a claim.
  if (text.length > MAX_BODY) return null

  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

/** Lowercased and trimmed, or null if it is not plausibly an address.
 *
 *  Deliberately not a full RFC 5322 grammar. The only question worth asking
 *  here is whether this can be delivered at all; the real test of an address
 *  is whether the confirmation arrives, and no regex substitutes for it. */
function normalize(value) {
  if (typeof value !== 'string') return null

  const email = value.trim().toLowerCase()
  if (email.length < 6 || email.length > MAX_EMAIL) return null
  if (/\s/.test(email)) return null

  const parts = email.split('@')
  if (parts.length !== 2) return null

  const [local, domain] = parts
  if (!local || local.length > 64) return null
  if (!domain.includes('.') || domain.startsWith('.') || domain.endsWith('.')) return null
  if (domain.includes('..')) return null

  return email
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  })
}

/* ------------------------------------------------------------------- mail */

/** Returns true if Resend accepted the message. Never throws: the caller has
 *  already committed the signup and a send failure must not undo it. */
async function sendConfirmation(env, email) {
  if (!env.RESEND_API_KEY) {
    console.error('subscribe: no RESEND_API_KEY, confirmation not sent')
    return false
  }

  let response
  try {
    response = await fetch(RESEND_API, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        from: env.MAIL_FROM,
        to: [email],
        reply_to: env.MAIL_REPLY_TO,
        subject: 'You are on the list',
        text: TEXT,
        html: html(env.MAIL_IMAGE_ORIGIN),
        // Removal is by reply (see the footer), and this header is that same
        // path in the form Gmail and Apple Mail can offer as a button. It
        // costs nothing and it means the native unsubscribe control does the
        // thing the copy promises rather than nothing at all.
        headers: {
          'List-Unsubscribe': `<mailto:${env.MAIL_REPLY_TO}?subject=off>`,
        },
      }),
    })
  } catch (err) {
    console.error(`subscribe: resend unreachable: ${err}`)
    return false
  }

  if (response.ok) return true

  // Status and Resend's own message, which names the cause (an unverified
  // domain, a rejected key). The recipient is not logged.
  const detail = await response.text().catch(() => '')
  console.error(`subscribe: resend ${response.status} ${detail}`)
  return false
}

// Voice standard (prompts/voice.md): short sentences, one idea each, no hype,
// and no em dashes anywhere (CLAUDE.md rule 7).
const TEXT = `You are on the list.

Thank you. We are grateful you are here, and glad to have you along for this
part of it.

Norm's Newsletter is being built to do one thing well. It gives you the day's
news in plain English, and then it ends. No feed, no infinite scroll, and no
reason to keep going once you have finished.

Here is what happens next: not much, for a while. We will not fill your inbox.
You will hear from us when something real changes, and again on the day the app
opens. That is the whole promise.

Reply with the word off and you are removed. No form, no link, no questions.

Norm
`

// Tokens from src/index.css's default `morning` palette, which is also
// DESIGN.md section 3. The card in scripts/build-og.mjs uses the same four.
const PAPER = '#f6f4ee'
const INK = '#23231f'
const INK_SOFT = '#44433c'
const MUTED = '#6b6a62'
const OXIDE = '#3f6a50'

// The hero paragraph's stack. Newsreader is not loadable in mail, so this falls
// to Georgia, which is the closest thing installed everywhere.
const SERIF = "Newsreader,Georgia,'Times New Roman',serif"

/** Table layout and inline styles throughout, because that is the only thing
 *  every mail client agrees on.
 *
 *  The body is set to match the hero paragraph on the landing page: the same
 *  serif, 19px on 1.62, in --ink-soft, opening on an oxide drop cap. The
 *  content table is 520px, which at that size lands near the hero's own 47ch
 *  measure. This mail is the first thing a subscriber sees after the page, so
 *  it should read as the same publication rather than as a receipt.
 *
 *  The mug is served from the deployed site rather than embedded, so it is one
 *  file with the favicon and the shared-link card rather than a third copy.
 *  Mail clients that block images show the alt text and lose nothing else, and
 *  so does an unset origin. */
function html(origin) {
  const p = `margin:0 0 20px;font-family:${SERIF};font-size:19px;line-height:1.62;color:${INK_SOFT}`

  /* index.css uses ::first-letter for this, which is not available here: there
     is no <style> block to put it in and Gmail strips the rule anyway. A
     floated span is the one form of it that survives. Outlook's Word engine
     ignores float on an inline span, so there it degrades to an oversized first
     letter sitting on the line, which is a fair reading of the same idea. */
  const cap = `float:left;font-family:${SERIF};font-weight:500;font-size:3.4em;line-height:0.82;padding:0.06em 0.1em 0 0;color:${OXIDE}`
  const mug = origin
    ? `<tr><td style="padding-bottom:22px">
<img src="${origin}/apple-touch-icon.png" width="44" height="44" alt="Norm's Newsletter" style="display:block;border:0;width:44px;height:44px">
</td></tr>`
    : ''
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>You are on the list</title></head>
<body style="margin:0;padding:0;background:${PAPER}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">We will only write when there is something real.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${PAPER}">
<tr><td align="center" style="padding:40px 20px 56px">
<table role="presentation" width="520" cellpadding="0" cellspacing="0" border="0" style="width:520px;max-width:100%">

${mug}
<tr><td style="height:3px;background:${INK};font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="height:3px;font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="height:1px;background:${INK};font-size:0;line-height:0">&nbsp;</td></tr>

<tr><td style="padding-top:34px">
<h1 style="margin:0 0 24px;font-family:${SERIF};font-weight:500;font-size:30px;line-height:1.15;letter-spacing:-0.012em;color:${INK}">You are on the list.</h1>

<p style="${p}"><span style="${cap}">T</span>hank you. We are grateful you are here, and glad to have you along for this part of it.</p>

<p style="${p}">Norm&rsquo;s Newsletter is being built to do one thing well. It gives you the day&rsquo;s news in plain English, and then it ends. No feed, no infinite scroll, and no reason to keep going once you have finished.</p>

<p style="${p}">Here is what happens next: not much, for a while. We will not fill your inbox. You will hear from us when something real changes, and again on the day the app opens. That is the whole promise.</p>

<p style="margin:0;font-family:${SERIF};font-size:20px;line-height:1.4;color:${OXIDE}">Norm</p>
</td></tr>

<tr><td style="padding-top:38px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td style="height:1px;background:${MUTED};opacity:0.4;font-size:0;line-height:0">&nbsp;</td></tr>
</table>
<p style="margin:16px 0 0;font-family:'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace;font-size:11px;line-height:1.7;letter-spacing:0.08em;text-transform:uppercase;color:${MUTED}">You asked to hear from us, so this is the only mail you get until there is real news. Reply with the word off and you are removed.</p>
</td></tr>

</table>
</td></tr>
</table>
</body></html>`
}
