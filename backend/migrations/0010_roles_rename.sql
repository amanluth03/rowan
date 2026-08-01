-- 0010_roles_rename: user_role 'pm' -> 'assistant'.
--
-- Epic 1 (Accounts & Running Live) introduces two named roles, owner and
-- assistant. The enum shipped as ('owner', 'pm') in 0002_enums.sql, when
-- CLAUDE.md still listed multi-user orgs as a non-goal and 0003_core.sql
-- assumed one user per org. Both positions are deliberately reversed by
-- this epic; see docs/adr/0007-authentication-and-authorization.md.
--
-- ALTER TYPE ... RENAME VALUE is transaction-safe on PG10+, so it runs
-- fine inside scripts/migrate.py's per-file transaction. It rewrites the
-- label in place -- existing rows keep their identity and no data moves.

alter type user_role rename value 'pm' to 'assistant';
