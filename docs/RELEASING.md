# Releasing

## Versioning

The project follows Semantic Versioning:

- `MAJOR` — breaking API, database or behavior change;
- `MINOR` — new backward-compatible capability;
- `PATCH` — backward-compatible fix.

Before `1.0.0`, minor versions may include breaking changes, but they must be called out in the release notes.

## Checklist

1. Confirm the scope is merged on `main`.
2. Run the full suite:

   ```bash
   ./scripts/run_all_tests.sh --full
   ```

3. Update `CHANGELOG.md`:
   - move relevant items from `Unreleased`;
   - add the version and date;
   - add a link to the compare view.
4. Update the version in `CITATION.cff`.
5. Commit the release preparation.
6. Tag:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --tags
   ```

7. Create a GitHub Release from the tag.
8. Include:
   - highlights;
   - breaking changes;
   - upgrade and migration steps;
   - database backup reminder;
   - full changelog link.
9. Verify the release badge and README links.
10. Announce only after the release page is live.

## Database changes

If the schema changed:

- test an upgrade from the previous release database;
- test a fresh database;
- write the backup and migration steps in the release notes;
- never tell users to delete their production database as an upgrade step.

## Security releases

- Do not publish exploit details before a fix is available.
- Credit the reporter if they want credit.
- Publish the minimum affected versions.
- Add a `Security` section to the changelog.

## Rollback

If a release is broken:

- mark the GitHub Release as a pre-release or add a clear warning;
- publish a patched release;
- do not delete the old tag;
- document the rollback steps.
