-- V042 — Backfill platform = 'instagram' on legacy rows that predate per-platform identity.
--
-- V041 made entity identity per-platform and backfilled the account/post/media/
-- comment CANONICAL tables. This migration extends that backfill to every
-- remaining table that carries a `platform` column (the *_archive tables and
-- archive_session) so no legacy row is left with a NULL platform. All
-- pre-Threads data is Instagram, so 'instagram' is the correct value.
--
-- Intentionally NOT touched: the engagement canonical tables post_like,
-- tagged_account and account_relation have no `platform` column by design. A
-- like/tag/relation's platform is normalized away because it is always that of
-- the related post and account, so there is nothing to backfill there.
--
-- New rows already get platform written by the archive INSERTs in db_intake, so
-- this is a one-time cleanup of pre-existing rows. The UPDATEs on the four
-- canonical tables V041 already handled are harmless no-ops, included so this
-- migration is a self-contained "no NULL platform anywhere" sweep.

UPDATE account                  SET platform = 'instagram' WHERE platform IS NULL;
UPDATE account_archive          SET platform = 'instagram' WHERE platform IS NULL;
UPDATE account_relation_archive SET platform = 'instagram' WHERE platform IS NULL;
UPDATE archive_session          SET platform = 'instagram' WHERE platform IS NULL;
UPDATE post                     SET platform = 'instagram' WHERE platform IS NULL;
UPDATE post_archive             SET platform = 'instagram' WHERE platform IS NULL;
UPDATE post_like_archive        SET platform = 'instagram' WHERE platform IS NULL;
UPDATE comment                  SET platform = 'instagram' WHERE platform IS NULL;
UPDATE comment_archive          SET platform = 'instagram' WHERE platform IS NULL;
UPDATE media                    SET platform = 'instagram' WHERE platform IS NULL;
UPDATE media_archive            SET platform = 'instagram' WHERE platform IS NULL;
UPDATE tagged_account_archive   SET platform = 'instagram' WHERE platform IS NULL;
