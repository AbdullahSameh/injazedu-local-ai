-- The disposable test database — note the _test marker (FR-029).
-- Reproducible from migrations plus fixtures; the only database any test may touch.
CREATE DATABASE injaz_ai_test;

-- Default privileges are per-database, so injaz_ai's setup in 01-roles.sql does not carry over.
-- Mirror it here — same roles (already created cluster-wide), same schema privileges — so
-- FR-013's guarantee is provable against the test database too.
\connect injaz_ai_test

CREATE EXTENSION IF NOT EXISTS vector;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  USAGE  ON SCHEMA public TO ai_app, ai_control;
GRANT  CREATE ON SCHEMA public TO ai_migrator;

ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO ai_app, ai_control;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO ai_app, ai_control;
