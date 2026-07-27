"""Publish workflow posture (Finding 2, SPEC 6.8 / SPEC 7).

The in-code containment (a built edition always survives, run() never escapes)
is only half the guarantee. The other half is that the workflow does not throw
a built edition away by failing fast on a non-blocking step. These checks pin
that in the yaml so a future edit cannot quietly reopen the hole.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"


def _doc():
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers():
    """The `on:` block.

    YAML 1.1 reads a bare `on` as the boolean True, so PyYAML keys this block
    under True and not under "on". Asking for doc["on"] returns nothing and any
    assertion built on it passes vacuously, which is worse than failing.
    """
    doc = _doc()
    assert "on" not in doc, "PyYAML changed: `on` now parses as a string key"
    return doc[True]


def _steps():
    return _doc()["jobs"]["publish"]["steps"]


def _step(name):
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r}")


def test_audio_is_non_blocking():
    # Audio runs between Build edition and Commit; a hard failure must not
    # stop the commit and deploy (SPEC 7: audio failure is non-blocking).
    assert _step("Audio build")["continue-on-error"] is True


def test_archive_is_non_blocking():
    # Archive runs after deploy and the healthcheck ping, so its failure must
    # not turn an already-published morning red.
    assert _step("Archive to gold")["continue-on-error"] is True


def test_build_edition_stays_fail_fast():
    # Build edition is the one step that MUST fail the job when it fails:
    # a non-zero exit there means nothing was published, so there is nothing
    # to deploy. It must not be marked continue-on-error.
    assert _step("Build edition").get("continue-on-error") is not True


def test_audio_runs_before_commit():
    # The whole point of Finding 2: audio sits between building and committing
    # the edition, which is why its failure could strand the edition. If a
    # future edit moves commit before audio, this guard is worth revisiting.
    names = [s.get("name") for s in _steps()]
    assert names.index("Audio build") < names.index("Commit edition")


def test_external_trigger_is_wired():
    # SPEC 6.11: the Cloudflare Worker's dispatch. Without this the Worker
    # POSTs into a void and every morning silently reverts to GitHub's cron
    # timing, which is the failure the whole milestone exists to prevent.
    assert _triggers()["repository_dispatch"]["types"] == ["publish-window"]


def test_github_crons_are_kept_alongside_it():
    # Decision #31: the crons stay as the backstop, they are not replaced. The
    # gate makes the redundancy free, so removing them would trade one single
    # point of failure for another.
    crons = [c["cron"] for c in _triggers()["schedule"]]
    assert crons == ["30 9 * * *", "30 10 * * *"]


def test_force_input_stays_on_workflow_dispatch_only():
    # 6.11: `force` must be unreachable from a dispatch, so an external trigger
    # can never bypass the window or the idempotency check. It is only a
    # workflow_dispatch input; github.event.inputs is empty for other events.
    assert "force" in _triggers()["workflow_dispatch"]["inputs"]
    assert _triggers()["repository_dispatch"] == {"types": ["publish-window"]}


def test_site_run_is_recorded_after_the_ping_and_is_non_blocking():
    # SPEC section 8: ended_at on this row is the timeliness measure's clock,
    # so it must close after the deploy succeeded and the ping went green.
    # continue-on-error because a run_log write must never redden a publish
    # that is already live.
    names = [s.get("name") for s in _steps()]
    assert names.index("Record site run") > names.index("Ping healthchecks")
    assert _step("Record site run")["continue-on-error"] is True


def test_site_run_records_the_triggering_event():
    # The trigger provenance the migration exit criterion (SPEC 13) turns on.
    assert "${{ github.event_name }}" in _step("Record site run")["run"]


def test_degraded_check_is_last_and_fail_fast():
    # Finding 3: the degraded signal must run after the deploy and the
    # healthcheck ping (so the site is live and green first), and it must NOT
    # be continue-on-error, because a red exit is the whole alert.
    names = [s.get("name") for s in _steps()]
    assert names[-1] == "Flag degraded publication"
    assert names.index("Flag degraded publication") > names.index("Ping healthchecks")
    assert _step("Flag degraded publication").get("continue-on-error") is not True
