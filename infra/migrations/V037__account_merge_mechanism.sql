-- V037 — account soft-merge mechanism
--
-- Accounts observed only by username (mentions, tags, captions never surface
-- the pk) get their own canonical row; when a later observation proves such a
-- row is the same profile as a pk-holder, the two are merged. Internal account
-- ids are cited in external sources, so a merged row is never deleted: it
-- becomes a tombstone whose merged_into_account_id points at the surviving
-- row, and the read path serves the keeper for stale citations.
-- account_merge_log records every merge with a snapshot of the tombstoned
-- row's fields for audit and unmerge.
--
-- See db_loaders/account_merge.py for the merge implementation.

ALTER TABLE account
    ADD COLUMN merged_into_account_id int null;

CREATE INDEX account_merged_into_account_id_index
    ON account (merged_into_account_id);

ALTER TABLE account
    ADD CONSTRAINT account_merged_into_account_id_fk
        FOREIGN KEY (merged_into_account_id) REFERENCES account (id);

CREATE TABLE account_merge_log
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP          not null,
    keeper_account_id  int                                          not null,
    merged_account_id  int                                          not null,
    source             enum ('intake_auto', 'migration', 'manual')  not null,
    archive_session_id int                                          null comment 'session whose observation triggered an intake_auto merge',
    user_id            int                                          null comment 'user who requested a manual merge',
    merged_snapshot    json                                         null comment 'identity fields of the merged row at merge time (pre-tombstone), for audit/unmerge',
    constraint account_merge_log_keeper_fk
        foreign key (keeper_account_id) references account (id),
    constraint account_merge_log_merged_fk
        foreign key (merged_account_id) references account (id)
)
    engine = InnoDB;

CREATE INDEX account_merge_log_keeper_index
    ON account_merge_log (keeper_account_id);

CREATE INDEX account_merge_log_merged_index
    ON account_merge_log (merged_account_id);
