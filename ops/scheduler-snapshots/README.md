# Cloud Scheduler snapshots

Version-controlled snapshots of every Cloud Scheduler job in
`nba-props-platform / us-west2`.

## Why these live in git

On 2026-07-03 an off-season purge deleted 94 scheduler jobs. The restore plan in
`docs/02-operations/scheduler-restore-manifest-2026.md` named a single source of
truth for their configurations:

```
gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json
```

That bucket has a lifecycle rule deleting objects at 30 days:

```
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
```

The backup aged out around 2026-08-02. It was discovered missing on 2026-08-19,
when the restore script was about to be written — four weeks of runway spent on a
plan whose input no longer existed. The oldest surviving object in that bucket is
dated 2026-07-21, exactly consistent with a 30-day TTL.

A backup stored under a delete-at-30-days lifecycle rule is not a backup. These
snapshots live in git, which has no TTL, no lifecycle rule, and no quota that
silently reclaims them. They are ~110KB and diff readably, so the history also
serves as an audit trail of schedule changes.

## Usage

```bash
./bin/scheduler/backup_scheduler_jobs.sh          # write + refresh 'latest'
./bin/scheduler/backup_scheduler_jobs.sh --gcs    # also copy to gs://nba-props-status/
git add ops/scheduler-snapshots && git commit
```

Take a snapshot before any bulk scheduler change (pause sweeps, purges, wave
resumes) and after it, so the diff shows exactly what moved.

`scheduler-jobs-latest.json` is a copy of the most recent dated snapshot, kept so
tooling does not have to guess a filename.
