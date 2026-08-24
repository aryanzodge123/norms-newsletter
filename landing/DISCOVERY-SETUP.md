# Getting the page found

A one-time setup guide for the two things that are not in this repo: the
Cloudflare crawler policy, and telling search engines the site exists.

**This is an operator guide, not a spec.** It governs nothing. The reasoning
behind Part 1 is recorded in `PROPOSED-SPEC-DISCOVERY.md` section 15.4, which
is the thing to read if you want the argument rather than the steps.

Everything here happens in a web dashboard. You do not deploy anything, and you
do not touch the code.

---

## Where things stand

Run these four checks any time. All four should pass.

```bash
# 1. AI crawlers are not blocked
curl -s https://norm.news/robots.txt | grep -c "Disallow: /"
# expect: 0

# 2. The sitemap is reachable
curl -s -o /dev/null -w "%{http_code}\n" https://norm.news/sitemap.xml
# expect: 200

# 3. The page has real content in it, not an empty root div
curl -s https://norm.news/ | grep -c "<h1"
# expect: 1

# 4. Your Google verification record is live
dig TXT norm.news +short | grep -c google-site-verification
# expect: 1
```

As of 2026-08-24, checks 1 through 3 pass and check 4 does not. Part 2 below is
what closes the last one.

---

## Part 1. The AI crawler policy

### What this is about

Cloudflare can add its own text to your `robots.txt` at the edge, on top of
whatever your site serves. On new accounts it does this by default, and the
text it adds blocks the crawlers that build AI systems: GPTBot, ClaudeBot,
CCBot, Google-Extended, Bytespider and several others. It also sets
`Content-Signal: ai-train=no`.

Nobody chooses this. It arrives with the account.

### What it does and does not block

This is the part that is easy to get wrong in both directions.

**Not affected.** Ordinary Google and Bing search. `Googlebot` and `Bingbot`
are not on the block list, and the content signal says `search=yes` explicitly.
Your rankings are untouched. Blocking `Google-Extended` also does not remove
you from Google Search or from AI Overviews, because that crawler only governs
Gemini training.

**Also not affected.** Somebody pasting `norm.news` into ChatGPT or Claude.
Those use different crawlers (`ChatGPT-User`, `Claude-User`) which are not on
the list, because a person asked for that specific page.

**What is blocked.** The crawlers that build the general background knowledge
these systems have without being handed a link. An assistant can read the page
when told to, but has no awareness that Norm exists when nobody mentions it.

### The trade-off

It is a real judgment call rather than an obvious fix.

**Keeping the block** protects your writing from being absorbed into systems
that can then answer questions about it without sending anybody to you. For a
news product that is not paranoia. Summarizing news is the product.

**Lifting it** matters because this particular page is a marketing page for an
unreleased app. There is no journalism on it. Its whole job is to be found, and
while the block is on it structurally cannot be recommended by an assistant.

The sensible split: lift it for the marketing page, and treat it as a separate
decision if the published editions ever move onto this domain. Those two things
deserve different answers, and applying the archive's answer to a page with no
archive on it is the mistake to avoid.

### Checking the current state

```bash
curl -s https://norm.news/robots.txt
```

**Currently blocked** looks like roughly 60 lines, opening with a long comment
about content signals, containing `# BEGIN Cloudflare Managed content`, and
listing `Disallow: /` under a series of named crawlers.

**Currently open** looks like the 10 lines this repo's build writes: a short
comment, `User-agent: *`, `Allow: /`, and a `Sitemap:` line. Nothing else.

As of 2026-08-24 it is open.

### Changing it

1. Go to **dash.cloudflare.com** and log in.
2. Click **`norm.news`** in the list of domains.
3. In the left sidebar find **AI Crawl Control**.

   If you cannot find it, Cloudflare renames this feature often. It has been
   called *AI Scrapers and Crawlers*, *Bots*, and *AI Audit*. Use the search box
   at the top of the dashboard and type `AI`. It normally sits under Security.

4. Look for either a single toggle named something like **Block AI crawlers**,
   or a section named **Manage robots.txt**. Some accounts show a per-crawler
   list instead, in which case set GPTBot, ClaudeBot, CCBot, Google-Extended
   and Applebot-Extended individually.

Changes save immediately. There is no deploy step. Wait a minute, then re-run
the `curl` above to confirm. Edge caching can hold the old copy briefly, so give
it five minutes before concluding it did not work.

---

## Part 2. Google Search Console

### The problem

A sitemap is a list of your pages handed to a search engine so it does not have
to guess. You have one at `norm.news/sitemap.xml` and `robots.txt` points at it.

The catch is that Google only reads your `robots.txt` after it already knows the
site exists, and it normally learns that by following a link from a site it
already crawls. `norm.news` is a new domain with almost nothing linking to it.
The sign is up and nobody has walked down that street yet.

Search Console is the way to skip the queue. It also shows you what Google
actually thinks, instead of leaving you guessing.

### Step 2.1. Add the property

1. Go to **search.google.com/search-console** and sign in.
2. Click **Add property**. It is the dropdown at the top left if you already
   have others.
3. You get two boxes. Choose the left one, **Domain**.
4. Type `norm.news`. No `https://`, no `www`, just the bare domain.
5. Click **Continue**.

Use Domain rather than URL prefix. Domain covers every version of the site at
once (`www`, bare, `http`, `https`). URL prefix covers only the exact string you
type, which is a common way to end up staring at an empty dashboard while the
real traffic sits on a version you did not add.

### Step 2.2. Copy the verification record

Google shows you a TXT record and asks you to put it in your DNS. It looks like
`google-site-verification=abc123XYZ...`. Click **Copy** and leave the tab open.

### Step 2.3. Add it in Cloudflare

1. New tab to **dash.cloudflare.com**, click **`norm.news`**.
2. Left sidebar, **DNS**, then **Records**.
3. Click **Add record** and fill it in exactly:

| Field | Value |
| --- | --- |
| Type | `TXT` |
| Name | `@` |
| Content | the `google-site-verification=...` string |
| TTL | Auto |

4. Click **Save**.

`@` means the domain itself rather than a subdomain. Cloudflare displays it as
`norm.news` after saving, which is correct and not a mistake. There is no orange
proxy cloud on a TXT record, so if you are hunting for one you are on the wrong
record type.

### Step 2.4. Verify

Confirm the record is live before clicking anything:

```bash
dig TXT norm.news +short
```

Your verification string should appear in the output. Then go back to the Google
tab and click **Verify**. You want a green "Ownership verified".

If it fails, DNS needs a few minutes. Wait, run `dig` again, and click Verify
only once you can see the string. Clicking repeatedly does not speed it up.

**Leave the TXT record in place permanently.** Google re-checks it, and deleting
it silently un-verifies the property months later.

### Step 2.5. Submit the sitemap

1. Left sidebar, **Sitemaps**.
2. In the *Add a new sitemap* box type exactly:

```
sitemap.xml
```

Not the full URL. Google prefills `https://norm.news/` for you, and pasting the
whole thing produces a doubled path and a fetch error.

3. Click **Submit**. You want Status **Success** and *Discovered URLs: 1*.

"Couldn't fetch" sometimes appears right after submitting and clears itself
within a day. Confirm the file is genuinely reachable with
`curl -s https://norm.news/sitemap.xml`, then leave it alone.

### Step 2.6. Ask for a crawl now

1. At the top of Search Console there is a bar reading *Inspect any URL*.
2. Paste `https://norm.news/` and press Enter.
3. Wait for the check to finish, roughly 10 to 30 seconds.
4. Click **Request Indexing**.

This puts the page in a priority queue. Once per URL per day is the limit, and
doing it more often achieves nothing.

---

## Part 3. Bing

Worth five minutes, because Bing's index is what **DuckDuckGo** and **ChatGPT's
web search** both read from. That is directly relevant to being easy to extract.

1. Go to **bing.com/webmasters** and sign in. A Microsoft, Google or Facebook
   account all work.
2. Choose **Import from Google Search Console**.
3. Approve the permission prompt.

Bing pulls in the verified domain and the sitemap together. If the import fails,
add `norm.news` manually. Bing accepts the same DNS TXT approach, so you repeat
step 2.3 with the record Bing gives you.

---

## What to expect, and when

So that nothing looks broken when it is merely slow.

| When | What you should see |
| --- | --- |
| Immediately | Sitemap shows *Success* in Search Console |
| 1 to 3 days | Search Console, Pages, shows the page as **Indexed** |
| 3 to 14 days | Searching `site:norm.news` on Google returns the page |
| 2 to 4 weeks | Search Console, Performance, starts showing real search terms |
| 1 to 3 months | Assistants may mention Norm unprompted. This is the slowest one, because those systems refresh their knowledge on long cycles |

**The one screen to watch** is Search Console, Pages. *Indexed* means everything
worked. *Excluded* or *Crawled, currently not indexed* means something needs
looking at, and the exact wording is what tells you which thing.

---

## Mistakes that are easy to make

- **Adding the TXT record to the wrong domain.** Check the domain name at the
  top of the Cloudflare page before clicking Add record.
- **Typing the full sitemap URL into Search Console.** It wants `sitemap.xml`.
- **Deleting the TXT record later.** It un-verifies the property. Leave it.
- **Expecting results on day two.** Indexing a new domain takes days.

---

## Optional

Cloudflare has a feature called **Crawler Hints**, under **Caching** then
**Configuration**. It pings Bing and Yandex when the site changes so they
re-crawl sooner instead of waiting for their own schedule. One toggle, no cost,
not required. It pairs well with the rest of this.
