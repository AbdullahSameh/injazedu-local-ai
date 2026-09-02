-- Identities. Passwords come from the environment; none is hard-coded in this file.
-- \set ... `echo "$VAR"` reads the value from this container's own environment, which
-- docker-compose populates from the repo-root .env (research D-04).
\set migrator_password `echo "$AI_MIGRATOR_PASSWORD"`
\set app_password `echo "$AI_APP_PASSWORD"`
\set control_password `echo "$AI_CONTROL_PASSWORD"`

CREATE ROLE ai_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE ai_app      LOGIN PASSWORD :'app_password';
CREATE ROLE ai_control  LOGIN PASSWORD :'control_password';

-- Nobody but the migrator may create objects. PostgreSQL 15+ already revokes this from PUBLIC;
-- stating it explicitly means the guarantee does not depend on a version default.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  USAGE  ON SCHEMA public TO ai_app, ai_control;
GRANT  CREATE ON SCHEMA public TO ai_migrator;

-- Objects the migrator creates from now on are automatically readable/writable by the others,
-- so a future migration never needs a follow-up GRANT.
ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO ai_app, ai_control;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO ai_app, ai_control;
