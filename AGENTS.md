### Mandatory Git Checkpoint Policy

1. Before starting a new feature, inspect the Git working tree and ensure the previous completed implementation has a verified Git checkpoint.
2. Every successfully implemented and verified feature must receive a Git commit before proceeding to another feature.
3. Every completed bug fix must also receive a Git commit.
4. Keep unrelated features in separate commits.
5. Never commit incomplete, broken or unverified implementations as completed features.
6. Use meaningful Conventional Commit messages:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `refactor:` for code restructuring
   - `docs:` for documentation
   - `style:` for presentation-only changes
   - `test:` for test changes
   - `chore:` for maintenance
7. Review staged changes before committing.
8. Never commit credentials, private ENV files, databases, candidate resumes, proposals, private browser snapshots, logs or backups.
9. Push to GitHub when explicitly requested by the user.
10. Never force-push, automatically merge into main or perform destructive Git operations.
11. Report the commit hash after each completed implementation.
12. If verification fails, report the blocker before proceeding to the next feature.
