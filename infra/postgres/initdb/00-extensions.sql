-- Creates the vector capability as the image superuser, on first boot only.
-- Alembic's baseline migration asserts this extension exists; it never creates it
-- (research D-03) — vector is untrusted and CREATE EXTENSION requires superuser.
CREATE EXTENSION IF NOT EXISTS vector;
