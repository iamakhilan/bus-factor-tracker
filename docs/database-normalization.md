# Database normalization: 1NF through 5NF

The MySQL schema is designed to satisfy 5NF for the stated application facts and functional/join dependencies. This is a schema-design claim, not a guarantee that arbitrary future business rules cannot introduce a dependency.

## Design rules

- Store one value per column; do not store lists, comma-separated IDs, or repeating groups (1NF).
- Every non-key attribute in a relation depends on the whole candidate key, not a proper subset (2NF).
- Non-key attributes do not determine other non-key attributes inside the same relation; repository and contributor descriptive data live in their own relations (3NF).
- Every non-trivial functional dependency has a candidate key as its determinant (BCNF).
- Relations are decomposed along the identified join dependencies so they can be joined back losslessly without spurious rows (5NF, under the application's declared facts).

## Relations and candidate keys

| Relation | Candidate key(s) | Fact represented |
|---|---|---|
| `repository` | `repo_id`; (`owner`, `name`) | One GitHub repository and its current metadata |
| `contributor` | `contributor_id`; `github_username` | One GitHub account identity |
| `repo_contributor` | (`repo_id`, `contributor_id`) | Aggregate contribution metrics for one contributor in one repository |
| `issue` | `issue_id` | One GitHub issue and its tracked lifecycle timestamps |
| `pull_request` | `pr_id` | One GitHub pull request and its tracked lifecycle timestamps |
| `repo_release` | `release_id` | One GitHub release |
| `weekly_activity` | (`repo_id`, `week_start`) | One repository's activity total for one week |
| `bus_factor_snapshot` | `snapshot_id` | One time-stamped calculated risk snapshot |
| `repo_module` | `module_id`; (`repo_id`, `module_path`) | One top-level module/path within one repository |
| `repository_file` | `file_id`; (`repo_id`, `file_path`) | One file path within one repository and its module |
| `file_contributor_activity` | (`file_id`, `contributor_id`) | One contributor's sampled activity for one file |

Foreign keys express relationships; they do not copy repository names or contributor usernames into every fact table. For example, `repo_contributor` references `repository` and `contributor`, rather than repeating their descriptive attributes.

## Why the file-ownership relation was decomposed

The previous `module_ownership(repo_id, file_path, contributor_id, commit_count, additions, deletions, sampled_at)` mixed three concepts in one relation: repository-specific modules, repository files, and the many-to-many activity fact between a file and a contributor.

The normalized design separates these concepts:

1. `repo_module` stores each module once per repository.
2. `repository_file` stores each path once per repository and references its module.
3. `file_contributor_activity` stores the many-to-many file/contributor fact, keyed by the complete pair.

This removes repeated module/file identity data from each contributor activity row and makes the join paths explicit. The `module_ownership` SQL view preserves the former read shape for existing read-only API queries; it is a derived view, not a duplicate stored base table.

## Important caveats

- `bus_factor_snapshot` intentionally stores historical calculated metrics. They are snapshots, not duplicated current repository facts.
- `repo_contributor` stores GitHub's aggregate contribution totals; `file_contributor_activity` stores a bounded recent sample. They represent different grains and must not be merged.
- First-response timestamps are observed comment proxies, not proof that a maintainer responded.
- MySQL does not automatically enforce the business rule that a file's `module_id` matches the first segment of `file_path`; the sync code derives both consistently. Add a trigger or controlled write procedure only if writes outside the sync service must also be constrained.
- The schema uses surrogate primary keys where useful, plus unique candidate-key constraints to preserve natural uniqueness.

## Existing database migration

Back up your database, then run this migration exactly once from the repository root:

```bash
mysql -u root -p bus_factor_tracker < sql/migrations/002_5nf_file_ownership.sql
```

The migration creates the normalized tables, copies existing ownership rows, drops the old base table, and creates the compatibility view. It is intended for an existing installation that already has the old `module_ownership` table. Do not run it on a fresh database; fresh installs should use `sql/schema_mysql.sql`.

Verify the migration:

```sql
SHOW TABLES LIKE '%module%';
SHOW TABLES LIKE 'repository_file';
SHOW TABLES LIKE 'file_contributor_activity';
SELECT COUNT(*) FROM module_ownership;
SELECT COUNT(*) FROM repository_file;
SELECT COUNT(*) FROM file_contributor_activity;
```

After migrating, run the normal sync to refresh the sample. The sync updates the normalized base tables; the existing read-only API query continues to work through the compatibility view.
