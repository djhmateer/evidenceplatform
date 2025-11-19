-- TODO
-- 'utf8mb3' is deprecated and will be removed in a future release. Please use utf8mb4 instead

-- Done
-- taken out     update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
-- to: update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,


-- DM 18th Nov 25 added 

--DROP DATABASE IF EXISTS evidenceplatform;
-- todo move to utf8mb4_0900_ai_ci once I know this is all working
CREATE DATABASE evidenceplatform
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;


-- DM - unsigned for id, timestamp types pas 2038.. other thoughts
create table account
(
    id             int auto_increment primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    id_on_platform varchar(100)                        null,
    url            varchar(200)                        not null,
    display_name   varchar(100)                        null,
    bio            varchar(200)                        null,
    data           json                                null,
    notes          text                                null,
    url_parts      text                                null
);

create index account_bio_index
    on account (bio);

create index account_display_name_index
    on account (display_name);

create index account_id_on_platform_index
    on account (id_on_platform);

create index account_url_index
    on account (url);

-- DM thoughts here with: InnoDB rebuilding table to add column FTS_DOC_ID
create fulltext index idx_search_fulltext
    on account (url, url_parts, display_name, bio, notes);

create table account_archive
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP not null,
    update_date        timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    canonical_id       int                                 null,
    archive_session_id int                                 null,
    id_on_platform     varchar(100)                        null,
    url                varchar(200)                        not null,
    display_name       varchar(100)                        null,
    bio                varchar(200)                        null,
    data               json                                null
);

create index account_archive_archive_session_id_index
    on account_archive (archive_session_id);

create index account_archive_canonical_id_index
    on account_archive (canonical_id);

create index account_archive_id_on_platform_index
    on account_archive (id_on_platform);

create index account_archive_url_index
    on account_archive (url);

create table account_relation
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    followed_account_id int                                 not null,
    follower_account_id int                                 not null,
    relation_type       varchar(30)                         null,
    notes               text                                null
);

create index account_relation_followed_account_id_index
    on account_relation (followed_account_id);

create index account_relation_follower_account_id_index
    on account_relation (follower_account_id);

create table account_relation_archive
(
    id                              int auto_increment
        primary key,
    create_date                     timestamp default CURRENT_TIMESTAMP not null,
    update_date                     timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    canonical_id                    int                                 null,
    archive_session_id              int                                 null,
    id_on_platform                  varchar(100)                        null,
    followed_account_url            varchar(200)                        not null,
    followed_account_id_on_platform varchar(100)                        null,
    follower_account_url            varchar(200)                        not null,
    follower_account_id_on_platform varchar(100)                        null,
    relation_type                   varchar(30)                         null,
    data                            json                                null
);

create index account_relation_archive_archive_session_id_index
    on account_relation_archive (archive_session_id);

create index account_relation_archive_canonical_id_index
    on account_relation_archive (canonical_id);

create index account_relation_archive_followed_account_id_on_platform_index
    on account_relation_archive (followed_account_id_on_platform);

create index account_relation_archive_followed_account_url_index
    on account_relation_archive (followed_account_url);

create index account_relation_archive_follower_account_id_on_platform_index
    on account_relation_archive (follower_account_id_on_platform);

create index account_relation_archive_follower_account_url_index
    on account_relation_archive (follower_account_url);

create index account_relation_archive_id_on_platform_index
    on account_relation_archive (id_on_platform);

create table account_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    account_id  int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint account_id
        unique (account_id, tag_id)
);

create index tag_id
    on account_tag (tag_id);

create table archive_session
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    external_id         varchar(60)                         null,
    archived_url        varchar(200)                        null,
    archive_location    varchar(200)                        null,
    summary_html        longtext                            null,
    parsed_content      int                                 null comment 'used to track which version of the parsing code was used to populate this row, to allow reprocessing outdated rows',
    structures          json                                null,
    metadata            json                                null,
    extracted_entities  int                                 null,
    archiving_timestamp datetime                            null,
    notes               text                                null,
    extraction_error    varchar(500)                        null,
    source_type         int       default 0                 not null comment '0=AA_xlsx; 1=local_hars; 2=local_wacz;',
    attachments         json                                null,
    archived_url_parts  text                                null
);

create index archive_session_archived_url_index
    on archive_session (archived_url);

create index archive_session_archiving_timestamp_index
    on archive_session (archiving_timestamp);

create index archive_session_external_id_index
    on archive_session (external_id);

create fulltext index idx_search_fulltext
    on archive_session (archived_url, archived_url_parts, notes);

create table error_log
(
    id         int auto_increment
        primary key,
    timestamp  timestamp default CURRENT_TIMESTAMP                                                        null,
    event_type enum ('server_call', 'sql_error', 'unknown_error', 'unauthorized_access', 'login_attempt') not null,
    user_id    int                                                                                        null,
    details    text                                                                                       null,
    args       text                                                                                       null
)
    charset = utf8mb3;

create table media
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    id_on_platform varchar(100)                        null,
    url            varchar(250)                        not null,
    post_id        int                                 null,
    local_url      varchar(500)                        null,
    media_type     enum ('video', 'audio', 'image')    not null,
    data           json                                null,
    notes          text                                null,
    annotation     text                                null,
    thumbnail_path varchar(200)                        null
);

create index media_id_on_platform_index
    on media (id_on_platform);

create index media_post_id_index
    on media (post_id);

create index media_url_index
    on media (url);

create fulltext index search_idx_fulltext
    on media (notes, annotation);

create table media_archive
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    canonical_id        int                                 null,
    archive_session_id  int                                 null,
    id_on_platform      varchar(100)                        null,
    url                 varchar(250)                        not null,
    post_url            varchar(250)                        null,
    post_id_on_platform varchar(100)                        null,
    local_url           varchar(500)                        null,
    media_type          enum ('video', 'audio', 'image')    not null,
    data                json                                null
);

create index media_archive_archive_session_id_index
    on media_archive (archive_session_id);

create index media_archive_canonical_id_index
    on media_archive (canonical_id);

create index media_archive_id_on_platform_index
    on media_archive (id_on_platform);

create index media_archive_post_id_on_platform_index
    on media_archive (post_id_on_platform);

create index media_archive_post_url_index
    on media_archive (post_url);

create index media_archive_url_index
    on media_archive (url);

create table media_part
(
    id                    int auto_increment
        primary key,
    create_date           timestamp default CURRENT_TIMESTAMP not null,
    update_date           timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    media_id              int                                 not null,
    crop_area             varchar(100)                        null,
    notes                 text                                null,
    timestamp_range_start float                               null,
    timestamp_range_end   float                               null
);

create index media_part_media_id_index
    on media_part (media_id);

create table media_part_tag
(
    id            int auto_increment
        primary key,
    create_date   timestamp default CURRENT_TIMESTAMP not null,
    update_date   timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    media_part_id int                                 not null,
    tag_id        int                                 not null,
    notes         text                                null,
    constraint media_part_id
        unique (media_part_id, tag_id)
);

create index tag_id
    on media_part_tag (tag_id);

create table media_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    media_id    int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint media_id
        unique (media_id, tag_id)
);

create index tag_id
    on media_tag (tag_id);

create table post
(
    id               int auto_increment
        primary key,
    create_date      timestamp default CURRENT_TIMESTAMP not null,
    update_date      timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    id_on_platform   varchar(100)                        null,
    url              varchar(250)                        not null,
    account_id       int                                 null,
    publication_date datetime                            null,
    caption          text                                null,
    data             json                                null,
    notes            text                                null
);

create fulltext index idx_search_fulltext
    on post (notes, caption, url);

create index post_account_id_index
    on post (account_id);

create index post_id_on_platform_index
    on post (id_on_platform);

create index post_publication_date_index
    on post (publication_date);

create index post_url_index
    on post (url);

create table post_archive
(
    id                     int auto_increment
        primary key,
    create_date            timestamp default CURRENT_TIMESTAMP not null,
    update_date            timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    canonical_id           int                                 null,
    archive_session_id     int                                 null,
    id_on_platform         varchar(100)                        null,
    url                    varchar(250)                        not null,
    account_url            varchar(200)                        null,
    account_id_on_platform varchar(100)                        null,
    publication_date       datetime                            null,
    caption                text                                null,
    data                   json                                null
);

create index post_archive_account_id_on_platform_index
    on post_archive (account_id_on_platform);

create index post_archive_account_url_index
    on post_archive (account_url);

create index post_archive_archive_session_id_index
    on post_archive (archive_session_id);

create index post_archive_canonical_id_index
    on post_archive (canonical_id);

create index post_archive_id_on_platform_index
    on post_archive (id_on_platform);

create index post_archive_url_index
    on post_archive (url);

create table post_engagement
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    id_on_platform varchar(100)                        null,
    url            varchar(250)                        not null,
    post_id        int                                 null,
    account_id     int                                 null,
    notes          text                                null
);

create index post_engagement_account_id_index
    on post_engagement (account_id);

create index post_engagement_id_on_platform_index
    on post_engagement (id_on_platform);

create index post_engagement_post_id_index
    on post_engagement (post_id);

create index post_engagement_url_index
    on post_engagement (url);

create table post_engagement_archive
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    canonical_id        int                                 null,
    archive_session_id  int                                 null,
    id_on_platform      varchar(100)                        null,
    url                 varchar(250)                        not null,
    post_url            varchar(250)                        null,
    post_id_on_platform varchar(100)                        null,
    engagement_date     datetime                            null,
    caption             text                                null,
    data                json                                null
);

create index post_engagement_archive_archive_session_id_index
    on post_engagement_archive (archive_session_id);

create index post_engagement_archive_canonical_id_index
    on post_engagement_archive (canonical_id);

create index post_engagement_archive_id_on_platform_index
    on post_engagement_archive (id_on_platform);

create index post_engagement_archive_post_id_on_platform_index
    on post_engagement_archive (post_id_on_platform);

create index post_engagement_archive_post_url_index
    on post_engagement_archive (post_url);

create index post_engagement_archive_url_index
    on post_engagement_archive (url);

create table post_engagement_tag
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP not null,
    update_date        timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    post_engagement_id int                                 not null,
    tag_id             int                                 not null,
    notes              text                                null,
    constraint post_engagement_id
        unique (post_engagement_id, tag_id)
);

create index tag_id
    on post_engagement_tag (tag_id);

create table post_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    post_id     int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint post_id
        unique (post_id, tag_id)
);

create index tag_id
    on post_tag (tag_id);

create table tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    name        varchar(200)                        not null,
    description text                                null,
    tag_type_id int                                 null,
    constraint name
        unique (name, tag_type_id)
);

create table tag_hierarchy
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    super_tag_id        int                                 not null,
    sub_tag_id          int                                 not null,
    temporal_constraint varchar(100)                        null,
    notes               text                                null,
    constraint super_tag_id
        unique (super_tag_id, sub_tag_id)
);

create index sub_tag_id
    on tag_hierarchy (sub_tag_id);

create table tag_type
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    name        varchar(200)                        not null,
    description text                                null,
    notes       text                                null
);

create table token
(
    id          int auto_increment
        primary key,
    user_id     int                                not null,
    create_date datetime default CURRENT_TIMESTAMP not null,
    last_use    datetime default CURRENT_TIMESTAMP not null,
    token       varchar(100)                       not null,
    constraint token_token_uindex
        unique (token)
);

create table user
(
    id               int auto_increment
        primary key,
    create_date      datetime  default CURRENT_TIMESTAMP not null,
    update_date      timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP,
    email            varchar(200)                        not null,
    locked           tinyint   default 0                 not null,
    password_hash    varchar(255)                        null,
    password_alg     varchar(20)                         null,
    password_set_at  datetime                            null,
    last_pwd_failure datetime                            null,
    force_pwd_reset  tinyint   default 0                 not null,
    last_login       datetime                            null,
    login_attempts   int       default 0                 not null,
    admin            tinyint   default 0                 not null,
    constraint email
        unique (email)
);

