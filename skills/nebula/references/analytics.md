# Analytics reference

Run `stats --root ANCESTOR [--output NEW_FILE.html] [--open]` through this
skill's bundled launcher. Without `--root`, scan the current folder. The ancestor
need not be a Nebula or selected child. Each descendant Nebula retains its own
identity, configuration and learning state, including OFF roots.

The command saves a standalone HTML file and emits compact JSON: output path,
generation time, discovered/available root counts, discovery/detail completeness
and bounded warnings. A browser failure preserves the file. Invalid roots,
write failures and output collisions return nonzero. Partial discovery and
unavailable descendants remain visible in a useful report.

Counters track unique suggestions, each suggestion/verdict pair, genuine claims
and the first recorded application outcome. Acceptance does not imply execution;
an explicit exception counts separately from rejection. Counters belong to the
actual project and lesson version, survive raw history expiry, and begin at
schema 3 initialization. They do not backfill older behavior or alter scoring.
Unfinished claims include no invented outcome; “successful” means suitable
recorded execution, without measuring minutes saved. Confidence is preference
consistency, not a probability of correctness.

Schema 1/2 reports show retained history with analytics uninitialized. Stats
never migrates, maintains, checkpoints or enables state. Snapshots are consistent
within each root; different roots are read at different instants. Detail filters
do not change global summary cards. Project counters use recorded project rows,
not the lesson's eligible scope. Coverage notices mark truncated details.

Discovery skips dependencies/build/state directories and descendant directory
symlinks. Budgets: 10,000 directories, 100,000 entries, depth 12, 100 candidate
roots; per-root details: 1,000 lesson versions and 100 activity records; payload:
8 MiB. These limits can produce partial reports. The report contains local paths,
lesson text and retained human reasons, without remote assets. Output is an
owner-only file; inspect it before sharing. Regenerate to refresh it.
