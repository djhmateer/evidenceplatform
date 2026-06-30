-- V045 — Perceptual-hash reverse image search (Feature 01).
-- Gate the indexing batch with a status column on media (mirrors thumbnail_status), and store the
-- actual 64-bit hashes in a side table so a single video can carry many frame hashes (one row per
-- kept representative frame). Images get exactly one row (frame_time NULL).

ALTER TABLE media
    ADD COLUMN phash_status enum ('pending', 'generated', 'not_needed', 'error') NOT NULL DEFAULT 'pending';

CREATE INDEX media_phash_status_index ON media (phash_status);

CREATE TABLE media_hash
(
    id          int auto_increment PRIMARY KEY,
    media_id    int           NOT NULL,
    frame_time  decimal(10, 3) NULL,                                    -- seconds into video; NULL for images
    phash       bigint        NOT NULL,                                 -- 64-bit pHash, stored signed (two's-complement)
    dhash       bigint         NULL,                                    -- 64-bit dHash, secondary cross-check
    create_date timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT media_hash_media_fk FOREIGN KEY (media_id) REFERENCES media (id) ON DELETE CASCADE
)
    ENGINE = InnoDB;

CREATE INDEX media_hash_media_id_index ON media_hash (media_id);
