-- Only executed by the official image when PGDATA is empty.
-- Read fixed secret paths without placing passwords in command-line arguments.
\set ON_ERROR_STOP on
\set app_password `tr -d '\r\n' < /run/secrets/db_app_password`
\set migration_password `tr -d '\r\n' < /run/secrets/db_migration_password`

BEGIN;

SELECT format(
    'CREATE ROLE sophikron_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'migration_password'
) \gexec
SELECT format(
    'CREATE ROLE sophikron_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'app_password'
) \gexec

SELECT current_database() AS database_name \gset
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO sophikron_app, sophikron_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA sophikron AUTHORIZATION sophikron_migrator;
REVOKE ALL ON SCHEMA sophikron FROM PUBLIC;
GRANT USAGE ON SCHEMA sophikron TO sophikron_app;

ALTER DEFAULT PRIVILEGES FOR ROLE sophikron_migrator IN SCHEMA sophikron
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sophikron_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sophikron_migrator IN SCHEMA sophikron
    GRANT USAGE ON SEQUENCES TO sophikron_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sophikron_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

COMMIT;
\unset app_password
\unset migration_password
