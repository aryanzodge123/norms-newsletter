// Prints the waiting list as CSV.
//
//   npm run waitlist              read it
//   npm run waitlist > list.csv   keep it
//
// The rows go to stdout and the count goes to stderr, so the redirect above
// produces a clean file and the terminal still tells you how many there were.
//
// This is the only read path there is. functions/api/subscribe.js exports
// nothing but onRequestPost, so the list is not reachable over HTTP: seeing it
// requires an authenticated Cloudflare account, which is the intended bar for
// a table of other people's email addresses.
//
// To remove one person, which is the whole of the "reply with the word off"
// promise in the confirmation:
//
//   npx wrangler d1 execute norm-waitlist --remote \
//     --command "DELETE FROM waitlist WHERE email = 'them@example.com'"
//
// One statement, one table, nothing else to chase. That is decision #36's
// guarantee, kept here by hand because this table predates the Postgres it
// describes.

import { spawnSync } from 'node:child_process'

const SQL =
  'SELECT email, created_at, emailed_at FROM waitlist ORDER BY created_at, email'

// `npm run waitlist -- --local` reads the development copy that
// `wrangler pages dev` writes to. The default is --remote, and it has to be:
// without the flag wrangler reads the local copy, so on a machine that has
// never run the dev server the real list prints as empty, which looks exactly
// like nobody having signed up.
const local = process.argv.includes('--local')

const result = spawnSync(
  'npx',
  [
    'wrangler',
    'd1',
    'execute',
    'norm-waitlist',
    local ? '--local' : '--remote',
    '--json',
    '--command',
    SQL,
  ],
  { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
)

if (result.status !== 0) {
  process.stderr.write(result.stderr || 'wrangler failed\n')
  process.exit(result.status ?? 1)
}

// Wrangler prints its own banner before the JSON on some versions, so take the
// document from the first bracket rather than parsing the whole stream.
const start = result.stdout.indexOf('[')
if (start === -1) {
  process.stderr.write(`no JSON in wrangler output:\n${result.stdout}\n`)
  process.exit(1)
}

let rows
try {
  rows = JSON.parse(result.stdout.slice(start))[0].results
} catch (err) {
  process.stderr.write(`could not read wrangler output: ${err}\n`)
  process.exit(1)
}

const cell = (value) => {
  if (value === null || value === undefined) return ''
  const text = String(value)
  // An address cannot contain a comma or a quote, but the column is not the
  // only thing that could ever end up here.
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

process.stdout.write('email,created_at,emailed_at\n')
for (const row of rows) {
  process.stdout.write(`${cell(row.email)},${cell(row.created_at)},${cell(row.emailed_at)}\n`)
}

// emailed_at is null when the confirmation never sent. Worth naming rather
// than leaving to be noticed in the column, because it is the one state that
// needs a human to do something.
const unsent = rows.filter((row) => !row.emailed_at).length
const note = unsent ? `, ${unsent} with no confirmation sent` : ''
process.stderr.write(`${rows.length} on the list${note}\n`)
