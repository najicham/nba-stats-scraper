#!/usr/bin/env python3
"""Re-create the Cloud Scheduler jobs deleted in the 2026-07-03 off-season purge.

Every job is created PAUSED. Nothing this script does starts traffic; resuming is
a separate, deliberate act performed in waves (see the manifest).

    ./scripts/nba_offseason_restore_jobs.py                  # dry run, all waves
    ./scripts/nba_offseason_restore_jobs.py --wave A --apply
    ./scripts/nba_offseason_restore_jobs.py --job weekly-retrain-trigger --apply

WHAT THIS IS NOT
----------------
It is not a backup replay. The GCS backup the restore plan named as its source of
truth was deleted by a 30-day lifecycle rule and no copy survives; Cloud Scheduler
audit logs retain schedules but GCP redacts every target, body, header and OIDC
block. Definitions therefore come from ops/scheduler-catalog-2026.yaml, which is a
reconstruction with per-job provenance.

Jobs whose provenance is `needs_input` are refused unless --allow-unverified is
passed, so a guessed body cannot reach production by accident. Jobs marked
`verified: false` are created (their shape is known, a detail needs confirming)
but are listed in the summary so you can check them before the wave is resumed.

Idempotent: an existing job is left alone unless --force-update is given.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / 'ops' / 'scheduler-catalog-2026.yaml'
PROJECT = 'nba-props-platform'
LOCATION = 'us-west2'


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr.strip()}")
    return r


def job_exists(name):
    r = run(['gcloud', 'scheduler', 'jobs', 'describe', name,
             f'--location={LOCATION}', f'--project={PROJECT}',
             '--format=value(name)'], check=False)
    return r.returncode == 0


def resolve_uri(uri, services):
    for key, base in services.items():
        uri = uri.replace('{' + key + '}', base)
    return uri


def build_command(job, defaults, services):
    """Assemble the gcloud command for one job."""
    name = job['name']
    common = [
        f'--location={LOCATION}', f'--project={PROJECT}',
        f"--schedule={job['schedule']}",
        f"--time-zone={job['timezone']}",
    ]
    # Keep descriptions short and clean: gcloud accepts long strings but a
    # truncated mid-sentence note with stray quotes reads as corruption later.
    note = ' '.join((job.get('notes') or '').split())
    desc = f"[restored {job['wave']}/{job['provenance']}] " + note
    if len(desc) > 180:
        desc = desc[:177].rsplit(' ', 1)[0] + '...'
    common.append(f'--description={desc}')

    if job.get('target_type') == 'pubsub':
        # Fully qualify the topic. A bare topic name is resolved against the
        # LOCAL gcloud default project, which on this machine has variously been
        # jett-prod, dmhr-platform and urcwest — and Cloud Scheduler then refuses
        # the create with "topic projects/<wrong>/topics/... must have
        # nba-props-platform as project id". Two jobs failed exactly this way on
        # 2026-08-22. --project on the command does NOT fix it; the topic path
        # itself has to carry the project.
        topic = job['topic']
        if not topic.startswith('projects/'):
            topic = f'projects/{PROJECT}/topics/{topic}'
        cmd = ['gcloud', 'scheduler', 'jobs', 'create', 'pubsub', name,
               f'--topic={topic}',
               f"--message-body={json.dumps(job['body'], separators=(',', ':'))}"]
        return cmd + common

    uri = resolve_uri(job['uri'], services)
    cmd = ['gcloud', 'scheduler', 'jobs', 'create', 'http', name,
           f'--uri={uri}',
           f"--http-method={job.get('method', 'POST')}"]

    body = job.get('body')
    if body is not None:
        cmd.append(f"--message-body={json.dumps(body, separators=(',', ':'))}")
        for k, v in (defaults.get('headers') or {}).items():
            cmd.append(f'--headers={k}={v}')

    # Cloud Run JOB execution through the Admin API needs OAuth; everything else
    # is a Cloud Run service or Gen2 function and needs OIDC with audience == URI.
    sa = defaults['service_account']
    if job.get('oauth'):
        cmd.append(f'--oauth-service-account-email={sa}')
    else:
        cmd.append(f'--oidc-service-account-email={sa}')
        cmd.append(f"--oidc-token-audience={uri.split('?')[0]}")

    retry = defaults.get('retry') or {}
    if retry.get('minBackoffDuration'):
        cmd.append(f"--min-backoff={retry['minBackoffDuration']}")
    if retry.get('maxBackoffDuration'):
        cmd.append(f"--max-backoff={retry['maxBackoffDuration']}")
    if retry.get('maxDoublings') is not None:
        cmd.append(f"--max-doublings={retry['maxDoublings']}")
    if defaults.get('attempt_deadline'):
        cmd.append(f"--attempt-deadline={defaults['attempt_deadline']}")

    return cmd + common


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--wave', choices=['A', 'B', 'C', 'all'], default='all')
    ap.add_argument('--job', help='restore a single job by name')
    ap.add_argument('--apply', action='store_true',
                    help='actually create jobs (default is a dry run)')
    ap.add_argument('--force-update', action='store_true',
                    help='delete and re-create jobs that already exist')
    ap.add_argument('--allow-unverified', action='store_true',
                    help='also create jobs whose provenance is needs_input')
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text())
    defaults, services, jobs = cat['defaults'], cat['services'], cat['jobs']

    if args.job:
        jobs = [j for j in jobs if j['name'] == args.job]
        if not jobs:
            sys.exit(f'No such job in catalog: {args.job}')
    elif args.wave != 'all':
        jobs = [j for j in jobs if j['wave'] == args.wave]

    created, skipped, refused, failed, unverified = [], [], [], [], []

    print(f"{'DRY RUN — nothing will be created' if not args.apply else 'APPLYING'}"
          f"  ({len(jobs)} jobs, wave={args.wave})\n")

    for job in jobs:
        name = job['name']
        if job['provenance'] == 'needs_input' and not args.allow_unverified:
            refused.append(name)
            print(f'  REFUSE  {name}\n          needs_input — body cannot be '
                  f'reconstructed; supply it in the catalog first')
            continue

        exists = job_exists(name) if args.apply or args.force_update else False
        if exists and not args.force_update:
            skipped.append(name)
            print(f'  EXISTS  {name}')
            continue

        cmd = build_command(job, defaults, services)
        if not args.apply:
            print(f'  CREATE  {name}  [{job["provenance"]}'
                  f'{"" if job.get("verified") else ", UNVERIFIED"}]')
            print(f'          {" ".join(cmd[:6])} ...')
            if not job.get('verified'):
                unverified.append(name)
            continue

        try:
            if exists and args.force_update:
                run(['gcloud', 'scheduler', 'jobs', 'delete', name,
                     f'--location={LOCATION}', f'--project={PROJECT}', '--quiet'])
            run(cmd)
            # Everything lands paused. Resuming is a separate, deliberate act.
            run(['gcloud', 'scheduler', 'jobs', 'pause', name,
                 f'--location={LOCATION}', f'--project={PROJECT}'])
            created.append(name)
            if not job.get('verified'):
                unverified.append(name)
            print(f'  CREATED {name} (paused)')
        except RuntimeError as e:
            failed.append((name, str(e)))
            print(f'  FAILED  {name}\n          {e}')

    print(f'\n{"="*70}\nSUMMARY')
    print(f'  created  {len(created)}')
    print(f'  existing {len(skipped)}')
    print(f'  refused  {len(refused)}  (needs_input; pass --allow-unverified to override)')
    print(f'  failed   {len(failed)}')

    if unverified:
        print(f'\n  {len(unverified)} job(s) created from an UNVERIFIED definition — '
              f'confirm before resuming:')
        for n in unverified:
            print(f'    - {n}')

    print("""
REMINDERS
  - Every job above is PAUSED. Resume in waves per the manifest, not all at once.
  - execute-workflows must be resumed PAIRED with the live master-controller-hourly
    (pause that one now; it is writing decisions nothing executes).
  - nba-tracking-stats-daily: verify the first run's drive values are not 0.0.
  - nba-closing-lines-sweep is in no backup and not in this catalog. Create it with
    bin/deploy/deploy_closing_lines_scheduler.sh --paused.
  - br-rosters-batch-daily is critical:true in config/workflows.yaml but is in
    NEITHER this catalog NOR the live snapshot. This restore will not bring it
    back; br_rosters_current max season_year is still 2025. Re-create it separately.
  - The player registry has no 2026-27 rows (nba_players_registry max season
    2025-26, seeded 2025-10-02). Without a reseed the fallback silently serves
    LAST season's rosters. Equivalent due date: ~2026-10-01.
  - decay-detection and grading-gap-detector have NO scheduler at all, and both
    pipeline canaries are PAUSED. Restoring this catalog does not fix those.
  - Snapshot before and after: ./bin/scheduler/backup_scheduler_jobs.sh""")

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
