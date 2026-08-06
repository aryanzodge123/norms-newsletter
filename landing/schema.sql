-- The waiting list. Applied once, by hand:
--
--   npx wrangler d1 execute norm-waitlist --remote --file=schema.sql
--
-- Four columns and deliberately no fifth. No IP, no user agent, no country,
-- no referrer. Every column here is personal data that a deletion request has
-- to reach, and decision #36's promise that deletion is one operation holds
-- only while the list of places to look is short enough to be obviously
-- complete. Analytics is the temptation; that promise is the reason not to.
--
-- This table is not covered by SPEC.md. See PROPOSED-SPEC.md in this
-- directory for the addition it needs, including a retention period, which
-- SPEC 14.12 sets for every other piece of personal data in the system.

CREATE TABLE IF NOT EXISTS waitlist (
  -- Lowercased before it is written. This is the dedupe and, through it, the
  -- guarantee that one address receives at most one mail from the endpoint
  -- ever. Making it the primary key is what lets the insert be a single
  -- atomic statement rather than a read followed by a write, which under
  -- concurrent submissions of the same address would send twice.
  email      TEXT PRIMARY KEY,

  -- ISO 8601, UTC, seconds precision.
  created_at TEXT NOT NULL,

  -- Null means the confirmation was never sent. The endpoint writes the row
  -- before it calls Resend and returns success either way, so a mail provider
  -- outage costs a confirmation and never a signup. This column is how that
  -- shows up in the export instead of vanishing.
  emailed_at TEXT,

  -- 'landing' today. Present so a second entry point does not need a
  -- migration to be told apart from this one.
  source     TEXT NOT NULL
);

-- The export sorts by signup order, and it is the only read there is.
CREATE INDEX IF NOT EXISTS waitlist_created_at ON waitlist (created_at);
