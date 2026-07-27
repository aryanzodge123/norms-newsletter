# spikes/check_dispatch.py
# Proves the trigger-worker's GitHub token can actually start a publish
# (SPEC 6.11, section 13 step 5). Run this before deploying the Worker and
# again after the migration, when the token and the repo path both change.
#
# Uses the workflow dispatch endpoint, not repository dispatch: the latter is
# granted under `Contents: write` (which would also let the token commit code),
# this one needs only `Actions: write`.
#
# Sending a real dispatch is safe. It does not set `force`, so the publish gate
# no-ops it unless the window is open and today is unpublished.
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

OWNER = os.environ.get("GITHUB_TRIGGER_OWNER", "aryanzodge123")
REPO = os.environ.get("GITHUB_TRIGGER_REPO", "norms-newsletter")
WORKFLOW = os.environ.get("GITHUB_TRIGGER_WORKFLOW", "publish.yml")
REF = os.environ.get("GITHUB_TRIGGER_REF", "main")
TOKEN = os.environ.get("GITHUB_TRIGGER_TOKEN")

if not TOKEN:
    sys.exit("GITHUB_TRIGGER_TOKEN is not set (put it in .env or the environment)")

response = httpx.post(
    f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
    headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "norms-newsletter-trigger",
    },
    json={"ref": REF, "inputs": {"source": "worker"}},
    timeout=30,
)

if response.status_code == 204:
    print(f"OK: dispatched {WORKFLOW} on {OWNER}/{REPO}@{REF}")
    print("The gate decides whether it publishes. Check the Actions tab.")
    print("The run's site run_log row should record trigger=worker.")
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
        print(
            f"404: {OWNER}/{REPO} or the workflow {WORKFLOW} is wrong, or the "
            "token cannot see the repo. A fine-grained token scoped to another "
            "repository also 404s here rather than 403."
        )
    elif response.status_code == 422:
        print(f"422: {REF} is not a valid ref, or an input was rejected.")
    sys.exit(1)
