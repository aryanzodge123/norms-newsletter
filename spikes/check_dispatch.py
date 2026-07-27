# spikes/check_dispatch.py
# Proves the trigger-worker's GitHub token can actually fire a publish
# (SPEC 6.11, section 13 step 5). Run this before deploying the Worker and
# again after the migration, when the token and the repo path both change.
#
# Sending a real dispatch is safe: the publish gate no-ops it unless the
# window is open and today is unpublished.
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

OWNER = os.environ.get("GITHUB_TRIGGER_OWNER", "aryanzodge123")
REPO = os.environ.get("GITHUB_TRIGGER_REPO", "norms-newsletter")
TOKEN = os.environ.get("GITHUB_TRIGGER_TOKEN")

if not TOKEN:
    sys.exit("GITHUB_TRIGGER_TOKEN is not set (put it in .env or the environment)")

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "norms-newsletter-trigger",
}

response = httpx.post(
    f"https://api.github.com/repos/{OWNER}/{REPO}/dispatches",
    headers=headers,
    json={"event_type": "publish-window"},
    timeout=30,
)

if response.status_code == 204:
    print(f"OK: dispatched publish-window to {OWNER}/{REPO}")
    print("The gate decides whether it publishes. Check the Actions tab.")
else:
    print(f"FAILED: {response.status_code} {response.text}")
    if response.status_code == 401:
        print("401: the token is wrong or expired.")
    elif response.status_code == 403:
        print(
            "403: the token lacks 'Actions: read and write', or the org has "
            "not enabled fine-grained PAT access (SPEC 13 step 4b)."
        )
    elif response.status_code == 404:
        print(f"404: {OWNER}/{REPO} is wrong, or the token cannot see it.")
    sys.exit(1)
