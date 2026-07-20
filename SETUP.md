# SETUP.md - Getting your M4 MacBook Air ready to build Norm's Newsletter

Status: v1.1 (aligned with SPEC.md v1.2 and DESIGN.md v1.0)
Companion documents: SPEC.md v1.2, DESIGN.md v1.0
This file is committed to the repo: SPEC.md section 13 (migration) re-runs
the verification spikes in Part 5, and the repo should carry its own
bootstrap instructions.
Time required: roughly 2-3 hours, mostly account setup and waiting on
installs. Nothing here writes project code. When you finish this document,
you open Claude Code, paste the kickoff prompt, and Milestone M1 starts
with zero blockers.

How to use this document: work top to bottom. Every section ends with a
"Verify" step. Do not move on until the verify step passes. Placeholders
you must replace are written LIKE_THIS.

A note on where things run: you are developing everything on the MacBook.
The always-on collector moves to the mini PC later, during Milestone M5.
Nothing in this guide touches the mini PC.

---

## Part 1: The Mac itself

### 1.1 Xcode Command Line Tools (git and compilers)

Open Terminal and run:

```bash
xcode-select --install
```

A dialog appears; click Install. If it says "already installed," you are
done with this step.

**Verify:** `git --version` prints a version number.

### 1.2 Homebrew (the package manager everything else installs through)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

At the end, Homebrew prints two or three "Next steps" commands that add
brew to your PATH (on Apple Silicon it lives in /opt/homebrew). Copy and
run exactly what it prints, then close and reopen Terminal.

**Verify:** `brew --version` prints a version number.

### 1.3 uv (Python version and dependency manager)

We use uv for everything Python: it installs Python itself, creates the
virtual environment, and manages dependencies. You never touch pip or
pyenv directly.

```bash
brew install uv
uv python install 3.12
```

**Verify:** `uv --version` works, and `uv python list` shows a 3.12.x
entry marked as installed.

### 1.4 Node.js (needed by Astro and Claude Code)

```bash
brew install node
```

**Verify:** `node --version` prints v20 or higher and `npm --version`
prints a version number.

### 1.5 Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

Then run `claude` once in any folder and follow the login flow in your
browser.

**Verify:** `claude --version` prints a version number. Full docs if
anything differs: https://docs.claude.com/en/docs/claude-code/overview

### 1.6 Git identity (skip if already configured)

```bash
git config --global user.name "Milind YOUR_LAST_NAME"
git config --global user.email "YOUR_GITHUB_EMAIL"
```

**Verify:** `git config --global --list` shows both values.

---

## Part 2: Accounts and API keys

You will collect seven credentials in this part. As you get each one,
paste it into a temporary note; Part 4 moves them all into a proper .env
file and GitHub secrets, then you delete the note.

### 2.1 Anthropic API key (powers scoring, editing, writing)

1. Go to https://console.anthropic.com and sign in or create an account.
2. Left sidebar: API Keys. Create Key. Name it `norms-newsletter`.
3. Copy the key (it is shown once). This is ANTHROPIC_API_KEY.
4. Now the important part: set a spend limit. Go to Settings, then
   Billing (or Limits), and set a monthly spend cap of $20. This is your
   budget enforcement of last resort; if a bug loops API calls at 3am,
   this cap is what stops it, not you.

**Verify:** deferred to Part 5, where a script makes a real call.

### 2.2 Cloudflare R2 (object storage and the Iceberg catalog)

This is the newest integration in the stack, so the steps are the most
detailed. UI labels occasionally move; if a menu name differs, the
concepts are: create a bucket, enable its data catalog, create a token.

1. Go to https://dash.cloudflare.com and create a free account.
2. Left sidebar: R2 Object Storage. You may be asked to add a payment
   method to enable R2; the free tier (10 GB storage, no egress fees) is
   far more than this project ever uses.
3. Create bucket. Name: `norms-newsletter`. Location: automatic. Leave
   the storage class as Standard.
4. Create a second bucket named `norms-audio`. This one holds the public
   MP3s. Open the bucket, go to Settings, and enable public access (the
   dashboard calls this a public bucket or an r2.dev subdomain). Note the
   public URL it gives you.
5. Back in the `norms-newsletter` bucket: open Settings and enable the
   Data Catalog (Cloudflare's built-in Apache Iceberg REST catalog). When
   enabled, the dashboard displays two values: a Catalog URI and a
   Warehouse name. Copy both exactly as shown. These are R2_CATALOG_URI
   and R2_WAREHOUSE. Current docs, in case the toggle has moved:
   https://developers.cloudflare.com/r2/
6. Create the API token. In R2, find API Tokens (called "Manage R2 API
   Tokens" or under Account API Tokens). Create a token with Admin Read
   and Write permission, scoped to your two buckets if the UI allows
   scoping. Copy the token value. This is R2_TOKEN. Also note your
   Account ID (shown on the R2 overview page); some tools ask for it.

**Verify:** deferred to Part 5, the PyIceberg spike.

### 2.3 Google AI Studio key (Gemini TTS for the podcast audio)

1. Go to https://aistudio.google.com and sign in with a Google account.
2. Find Get API key and create one in a new project.
3. Copy it. This is GEMINI_API_KEY.

**Verify:** deferred to Part 5.

### 2.4 Your existing data keys

Gather your existing NewsAPI, Finnhub, and FRED keys into the temporary
note as NEWSAPI_KEY, FINNHUB_KEY, and FRED_KEY. If any has expired, their
free-tier signup pages are newsapi.org, finnhub.io, and
fred.stlouisfed.org (API keys under My Account).

### 2.5 healthchecks.io (the dead man's switch)

1. Go to https://healthchecks.io and create a free account.
2. Create two checks:
   - Name: `norm-publish`. Schedule: a cron expression of `0 10 * * *`
     with a grace time of 2 hours (this tolerates the DST hour shift).
   - Name: `norm-collector`. Period: every 3 hours, grace time 2 hours.
3. Each check has a unique ping URL like
   `https://hc-ping.com/LONG-UUID`. Copy both. These are
   HEALTHCHECKS_PUBLISH_URL and HEALTHCHECKS_COLLECT_URL.
4. In Integrations, confirm email alerts point at an address you read.

**Verify:** run `curl HEALTHCHECKS_PUBLISH_URL` in Terminal, then refresh
the dashboard; the check shows a recent ping.

### 2.6 GoatCounter (privacy-friendly analytics)

1. Go to https://www.goatcounter.com, sign up free.
2. Choose a site code, e.g. `norms-newsletter`, giving you
   https://norms-newsletter.goatcounter.com.
3. Note the site code; DESIGN.md's footer script uses it in M4. No key
   needed.

---

## Part 3: The GitHub repository

1. On https://github.com create a new repository named
   `norms-newsletter`. Keep it **private** for now (SPEC section 11: the
   site launches publicly only after your OBA preclearance clears; you
   can build everything privately in the meantime).
2. Clone it and add the two governing documents:

```bash
cd ~
mkdir -p projects && cd projects
git clone https://github.com/YOUR_GITHUB_USERNAME/norms-newsletter.git
cd norms-newsletter
```

3. Copy SPEC.md and DESIGN.md (downloaded from our conversation) into
   this folder, then:

```bash
git add SPEC.md DESIGN.md
git commit -m "Add SPEC v1.1 and DESIGN v1.0"
git push
```

4. Add the secrets Actions will need. On GitHub: repo Settings, then
   Secrets and variables, then Actions, then New repository secret. Add
   each of these, names exactly as written:

   - ANTHROPIC_API_KEY
   - R2_CATALOG_URI
   - R2_WAREHOUSE
   - R2_TOKEN
   - GEMINI_API_KEY
   - NEWSAPI_KEY
   - FINNHUB_KEY
   - FRED_KEY
   - HEALTHCHECKS_PUBLISH_URL
   - HEALTHCHECKS_COLLECT_URL
   - R2_S3_ENDPOINT
   - R2_ACCESS_KEY_ID
   - R2_SECRET_ACCESS_KEY
   - R2_AUDIO_BUCKET
   - R2_AUDIO_PUBLIC_BASE

   The last five power the M6 audio upload (SPEC 6.7). The MP3 goes to an R2
   bucket over the S3 API, which uses account access keys (R2 dashboard, R2
   API Tokens, "Manage API token") rather than the catalog token above.
   R2_AUDIO_BUCKET is the bucket name, and R2_AUDIO_PUBLIC_BASE is that
   bucket's public URL (enable "Public access" or a custom domain in the R2
   dashboard). Until these are set the edition still publishes, without an
   audio row.

5. GitHub Pages itself gets configured in Milestone M5 (Settings, Pages,
   Source: GitHub Actions). Nothing to do now; noted here so you know it
   is intentionally deferred.

**Verify:** the repo shows both .md files, and the Actions secrets page
lists all fifteen names.

---

## Part 4: Local environment and secrets

Inside the repo folder:

### 4.1 Python project

```bash
cd ~/projects/norms-newsletter
uv init --python 3.12
uv add pyiceberg pyarrow duckdb anthropic google-genai \
       sentence-transformers httpx pydantic feedparser python-dotenv
```

This creates pyproject.toml, uv.lock, and a .venv. The first
sentence-transformers install downloads PyTorch, which is the longest
single step in this guide; Apple Silicon wheels install cleanly.

### 4.2 The .env file

```bash
touch .env
```

Open .env in your editor and fill it from your temporary note:

```
ANTHROPIC_API_KEY=sk-ant-...
R2_CATALOG_URI=...
R2_WAREHOUSE=...
R2_TOKEN=...
GEMINI_API_KEY=...
NEWSAPI_KEY=...
FINNHUB_KEY=...
FRED_KEY=...
R2_S3_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_AUDIO_BUCKET=norms-newsletter-audio
R2_AUDIO_PUBLIC_BASE=https://<your-r2-public-domain>
HEALTHCHECKS_PUBLISH_URL=https://hc-ping.com/...
HEALTHCHECKS_COLLECT_URL=https://hc-ping.com/...
```

### 4.3 .gitignore, before anything else is committed

```bash
cat > .gitignore << 'EOF'
.env
.venv/
__pycache__/
*.pyc
.DS_Store
node_modules/
dist/
site/dist/
EOF
git add .gitignore pyproject.toml uv.lock
git commit -m "Bootstrap Python project and gitignore"
git push
```

Now delete the temporary note holding your keys.

**Verify:** `git status` does NOT list .env. If it does, stop and fix
.gitignore before continuing. A leaked key means revoking and reissuing
everything in Part 2.

---

## Part 5: Verification spikes

Four tiny scripts prove every external integration works before any real
code depends on it. Put them in a `spikes/` folder; they get deleted after
M1. Run each with `uv run spikes/NAME.py`.

### 5.1 Anthropic API

```python
# spikes/check_anthropic.py
from dotenv import load_dotenv
import anthropic
load_dotenv()
client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=50,
    messages=[{"role": "user", "content": "Reply with exactly: Norm is ready."}],
)
print(msg.content[0].text)
```

**Pass:** it prints "Norm is ready." If the model name is rejected, check
the current model list at https://docs.claude.com/en/api/overview and use
the current Haiku model string.

### 5.2 R2 Data Catalog + PyIceberg (the one that matters most)

```python
# spikes/check_iceberg.py
import os
import pyarrow as pa
from dotenv import load_dotenv
from pyiceberg.catalog import load_catalog

load_dotenv()
catalog = load_catalog(
    "r2",
    **{
        "type": "rest",
        "uri": os.environ["R2_CATALOG_URI"],
        "warehouse": os.environ["R2_WAREHOUSE"],
        "token": os.environ["R2_TOKEN"],
    },
)
catalog.create_namespace_if_not_exists("spike")
table = catalog.create_table_if_not_exists(
    "spike.hello",
    schema=pa.schema([("id", pa.int64()), ("msg", pa.string())]),
)
table.append(pa.table({"id": [1], "msg": ["norm was here"]}))
print(table.scan().to_arrow().to_pydict())
```

**Pass:** it prints the row back. This proves the entire storage layer:
auth, catalog, table creation, append, and read. If it fails, the fix is
almost always one of: the catalog URI copied incompletely, the token
missing write permission, or a PyIceberg version issue; Cloudflare's R2
Data Catalog docs page shows a known-good PyIceberg snippet to compare
against. Afterward, delete the spike table from the R2 dashboard or leave
it; M1 uses its own namespace.

### 5.3 Local embeddings on Apple Silicon

```python
# spikes/check_embeddings.py
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
vecs = model.encode(["Fed holds rates steady", "Interest rates unchanged"])
sim = float((vecs[0] @ vecs[1]) /
            ((vecs[0] @ vecs[0]) ** 0.5 * (vecs[1] @ vecs[1]) ** 0.5))
print(f"similarity: {sim:.3f}")
```

**Pass:** prints a similarity around 0.7-0.9, confirming the clustering
stack runs locally at zero cost. First run downloads the model (~90 MB).

### 5.4 Gemini TTS

```python
# spikes/check_tts.py
import os
from dotenv import load_dotenv
from google import genai
load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
models = [m.name for m in client.models.list() if "tts" in m.name.lower()]
print("TTS-capable models visible:", models or "none found, check docs")
```

**Pass:** the key authenticates and at least one TTS model is listed.
Actual audio generation is built properly in M6; today only proves the
credential works. Current API shape: https://ai.google.dev/gemini-api/docs

### 5.5 Astro

```bash
cd ~/projects/norms-newsletter
npm create astro@latest site -- --template minimal --no-install --no-git
cd site && npm install && npm run dev
```

**Pass:** open http://localhost:4321 and see the Astro starter page. Stop
the server with Ctrl+C. Commit the site folder.

---

## Part 6: Decisions (RESOLVED, recorded in SPEC.md)

These were open questions in v1.0 of this guide. All three are now
decided and live in SPEC.md; this section records where.

1. **URL and deployment identity (SPEC decision #19, section 13).** The
   build phase runs on the personal GitHub account as a project site at
   https://PERSONAL_USERNAME.github.io/norms-newsletter. The clean
   https://norms-newsletter.github.io URL requires a GitHub organization
   named `norms-newsletter` holding a repo named
   `norms-newsletter.github.io`; that move is deliberately deferred to
   the pre-launch migration plan in SPEC section 13, which also covers
   moving API keys and email to a project-owned identity. Because public
   launch and podcast submission happen only after the migration (SPEC
   decision #20), no subscriber-facing URL ever changes. Practical
   consequence now: astro.config carries site = the personal URL and
   base = "/norms-newsletter", and nothing else in the codebase may
   hardcode a URL (SPEC 6.6).
2. **Contact email (SPEC decision #21):** aryanzodge1@gmail.com, interim.
   It appears publicly on the About page and in feed metadata, so expect
   scraper spam over time; the migration may replace it with a
   project-owned address.
3. **OBA preclearance (SPEC decision #22):** a launch gate, not a build
   gate. The repo stays private and the site unpublished until the
   bank's outside-activity process (and the broker-dealer's equivalent)
   clears it. Build everything in the meantime.

---

## Part 7: Final checklist

Every box checked means you are ready to open Claude Code and paste the
kickoff prompt.

- [ ] git, brew, uv (Python 3.12), node, Claude Code all verified
- [ ] Anthropic key created AND monthly spend cap set
- [ ] R2 buckets created, Data Catalog enabled, token saved
- [ ] Gemini key created
- [ ] NewsAPI, Finnhub, FRED keys gathered
- [ ] healthchecks.io: two checks created, test ping seen
- [ ] GoatCounter site created
- [ ] Private GitHub repo with SPEC.md and DESIGN.md pushed
- [ ] All ten Actions secrets added
- [ ] .env filled locally, .gitignore protecting it, temp note deleted
- [ ] Spike 5.1 Anthropic: passed
- [ ] Spike 5.2 Iceberg on R2: passed
- [ ] Spike 5.3 Embeddings: passed
- [ ] Spike 5.4 Gemini auth: passed
- [ ] Spike 5.5 Astro dev server: passed
- [ ] SETUP.md committed to the repo alongside SPEC.md and DESIGN.md
- [ ] OBA preclearance submitted (launch gate, not build gate)

When all boxes are checked:

```bash
cd ~/projects/norms-newsletter
claude
```

Paste the kickoff prompt. Milestone M1 begins.
