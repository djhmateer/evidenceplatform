
-- todo move to utf8mb4_0900_ai_ci once I know this is all working
-- refactor column types
-- default is InnoDB on latest MySQL so probably don't need engine.

CREATE DATABASE evidenceplatform
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE evidenceplatform;
create table account
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date    timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform varchar(100)                                                                null,
    url_suffix     varchar(200)                                                                null,
    identifiers    json                                                                        null,
    display_name   varchar(100)                                                                null,
    bio            varchar(200)                                                                null,
    data           json                                                                        null,
    url_parts      text                                                                        null,
    post_count     int       default 0                                                         not null,
    platform       enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null
)
    engine = InnoDB;

create index account_bio_index
    on account (bio);

create index account_display_name_index
    on account (display_name);

create index account_id_on_platform_index
    on account (id_on_platform);

create index account_post_count_index
    on account (post_count);

create index account_url_suffix_index
    on account (url_suffix);

create fulltext index idx_search_fulltext
    on account (url_suffix, url_parts, display_name, bio);

create table account_relation
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    followed_account_id int                                 not null,
    follower_account_id int                                 not null,
    relation_type       varchar(30)                         null,
    notes               text                                null,
    id_on_platform      varchar(200)                        null,
    data                json                                null,
    constraint account_relation_followed_id_fk
        foreign key (followed_account_id) references account (id),
    constraint account_relation_follower_id_fk
        foreign key (follower_account_id) references account (id)
)
    engine = InnoDB;

create index account_relation_followed_account_id_index
    on account_relation (followed_account_id);

create index account_relation_follower_account_id_index
    on account_relation (follower_account_id);

create index account_relation_id_on_platform_index
    on account_relation (id_on_platform);

create table archive_session
(
    id                        int auto_increment
        primary key,
    create_date               timestamp                                                            default CURRENT_TIMESTAMP not null,
    update_date               timestamp                                                            default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    external_id               varchar(60)                                                                                    null,
    archived_url_suffix       varchar(200)                                                                                   null,
    archive_location          varchar(200)                                                                                   null,
    summary_html              longtext                                                                                       null,
    parse_algorithm_version   int                                                                                            null comment 'used to track which version of the parsing code was used to populate this row, to allow reprocessing outdated rows',
    structures                json                                                                                           null,
    metadata                  json                                                                                           null,
    extract_algorithm_version int                                                                                            null,
    archiving_timestamp       datetime                                                                                       null,
    extraction_error          varchar(500)                                                                                   null,
    source_type               enum ('AA_xlsx', 'local_har', 'local_wacz')                                                    not null,
    incorporation_status      enum ('pending', 'parse_failed', 'parsed', 'extract_failed', 'done') default 'pending'         not null,
    attachments               json                                                                                           null,
    archived_url_parts        text                                                                                           null,
    notes                     text                                                                                           null,
    platform                  enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads')                    null
)
    engine = InnoDB;

create table account_archive
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date        timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id       int                                                                         null,
    archive_session_id int                                                                         null,
    id_on_platform     varchar(100)                                                                null,
    url_suffix         varchar(200)                                                                null,
    display_name       varchar(100)                                                                null,
    bio                varchar(200)                                                                null,
    data               json                                                                        null,
    platform           enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_account_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint account_archive_account_id_fk
        foreign key (canonical_id) references account (id),
    constraint account_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id)
)
    engine = InnoDB;

create index account_archive_archive_session_id_index
    on account_archive (archive_session_id);

create index account_archive_canonical_id_index
    on account_archive (canonical_id);

create index account_archive_id_on_platform_index
    on account_archive (id_on_platform);

create index account_archive_url_suffix_index
    on account_archive (url_suffix);

create table account_relation_archive
(
    id                              int auto_increment
        primary key,
    create_date                     timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date                     timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id                    int                                                                         null,
    archive_session_id              int                                                                         null,
    id_on_platform                  varchar(100)                                                                null,
    followed_account_url_suffix     varchar(200)                                                                null,
    followed_account_id_on_platform varchar(100)                                                                null,
    follower_account_url_suffix     varchar(200)                                                                null,
    follower_account_id_on_platform varchar(100)                                                                null,
    relation_type                   varchar(30)                                                                 null,
    data                            json                                                                        null,
    platform                        enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_account_relation_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint account_relation_archive_account_relation_id_fk
        foreign key (canonical_id) references account_relation (id),
    constraint account_relation_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id)
)
    engine = InnoDB;

create index account_relation_archive_archive_session_id_index
    on account_relation_archive (archive_session_id);

create index account_relation_archive_canonical_id_index
    on account_relation_archive (canonical_id);

create index account_relation_archive_followed_account_id_on_platform_index
    on account_relation_archive (followed_account_id_on_platform);

create index account_relation_archive_followed_account_url_suffix_index
    on account_relation_archive (followed_account_url_suffix);

create index account_relation_archive_follower_account_id_on_platform_index
    on account_relation_archive (follower_account_id_on_platform);

create index account_relation_archive_follower_account_url_suffix_index
    on account_relation_archive (follower_account_url_suffix);

create index account_relation_archive_id_on_platform_index
    on account_relation_archive (id_on_platform);

create index archive_session_archived_url_suffix_index
    on archive_session (archived_url_suffix);

create index archive_session_archiving_date
    on archive_session ((cast(`archiving_timestamp` as date)));

create index archive_session_archiving_timestamp_index
    on archive_session (archiving_timestamp);

create index archive_session_external_id_index
    on archive_session (external_id);

create index idx_incorporation_queue
    on archive_session (source_type, incorporation_status);

create fulltext index idx_search_fulltext
    on archive_session (archived_url_suffix, archived_url_parts, notes);

create table error_log
(
    id         int auto_increment
        primary key,
    timestamp  timestamp default CURRENT_TIMESTAMP                                                        null,
    event_type enum ('server_call', 'sql_error', 'unknown_error', 'unauthorized_access', 'login_attempt', '2fa_attempt') not null,
    user_id    int                                                                                        null,
    details    text                                                                                       null,
    args       text                                                                                       null
)
    engine = InnoDB
    charset = utf8mb3;

create table incorporation_job
(
    id                   int auto_increment
        primary key,
    started_at           datetime                                                  not null,
    completed_at         datetime                                                  null,
    status               enum ('running', 'completed', 'failed') default 'running' not null,
    triggered_by_user_id int                                                       null,
    triggered_by_ip      varchar(255)                                              null,
    log                  mediumtext                                                null,
    error                text                                                      null
);

create table post
(
    id               int auto_increment
        primary key,
    create_date      timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date      timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform   varchar(100)                                                                null,
    url_suffix       varchar(250)                                                                null,
    account_id       int                                                                         null,
    publication_date datetime                                                                    null,
    caption          text                                                                        null,
    data             json                                                                        null,
    platform         enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint post_account_id_fk
        foreign key (account_id) references account (id)
)
    engine = InnoDB;

create table comment
(
    id                            int auto_increment
        primary key,
    create_date                   timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date                   timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform                varchar(100)                                                                null,
    url_suffix                    varchar(250)                                                                null,
    post_id                       int                                                                         null,
    account_id                    int                                                                         null,
    parent_comment_id_on_platform varchar(100)                                                                null,
    text                          text                                                                        null,
    publication_date              datetime                                                                    null,
    data                          json                                                                        null,
    notes                         text                                                                        null,
    platform                      enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint comment_account_id_fk
        foreign key (account_id) references account (id),
    constraint comment_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

create index comment_account_id_index
    on comment (account_id);

create index comment_id_on_platform_index
    on comment (id_on_platform);

create index comment_post_id_index
    on comment (post_id);

create index comment_url_suffix_index
    on comment (url_suffix);

create table comment_archive
(
    id                            int auto_increment
        primary key,
    create_date                   timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date                   timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id                  int                                                                         null,
    archive_session_id            int                                                                         null,
    id_on_platform                varchar(100)                                                                null,
    url_suffix                    varchar(250)                                                                null,
    post_url_suffix               varchar(250)                                                                null,
    post_id_on_platform           varchar(100)                                                                null,
    account_id_on_platform        varchar(100)                                                                null,
    account_url_suffix            varchar(200)                                                                null,
    parent_comment_id_on_platform varchar(100)                                                                null,
    text                          text                                                                        null,
    publication_date              datetime                                                                    null,
    data                          json                                                                        null,
    platform                      enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_comment_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint comment_archive_canonical_fk
        foreign key (canonical_id) references comment (id),
    constraint comment_archive_session_fk
        foreign key (archive_session_id) references archive_session (id)
)
    engine = InnoDB;

create index comment_archive_canonical_id_index
    on comment_archive (canonical_id);

create index comment_archive_id_on_platform_index
    on comment_archive (id_on_platform);

create index comment_archive_post_id_on_platform_index
    on comment_archive (post_id_on_platform);

create index comment_archive_session_id_index
    on comment_archive (archive_session_id);

create table media
(
    id               int auto_increment
        primary key,
    create_date      timestamp                                            default CURRENT_TIMESTAMP not null,
    update_date      timestamp                                            default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform   varchar(100)                                                                   null,
    url_suffix       varchar(250)                                                                   null,
    post_id          int                                                                            null,
    local_url        varchar(500)                                                                   null,
    media_type       enum ('video', 'audio', 'image')                                               not null,
    data             json                                                                           null,
    annotation       text                                                                           null,
    thumbnail_path   varchar(200)                                                                   null,
    thumbnail_status enum ('pending', 'generated', 'not_needed', 'error') default 'pending'         not null,
    publication_date datetime                                                                       null,
    account_id       int                                                                            null,
    platform         enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads')    null,
    constraint media_account_id_fk
        foreign key (account_id) references account (id),
    constraint media_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

create index media_account_id_index
    on media (account_id);

create index media_id_on_platform_index
    on media (id_on_platform);

create index media_local_url_index
    on media (local_url);

create index media_media_type_index
    on media (media_type);

create index media_post_id_index
    on media (post_id);

create index media_publication_date_date
    on media ((cast(`publication_date` as date)));

create index media_publication_date_index
    on media (publication_date);

create index media_thumbnail_path_index
    on media (thumbnail_path);

create index media_thumbnail_status_index
    on media (thumbnail_status);

create index media_url_suffix_index
    on media (url_suffix);

create fulltext index search_idx_fulltext
    on media (annotation);

create table media_archive
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date         timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id        int                                                                         null,
    archive_session_id  int                                                                         null,
    id_on_platform      varchar(100)                                                                null,
    url_suffix          varchar(250)                                                                null,
    post_url_suffix     varchar(250)                                                                null,
    post_id_on_platform varchar(100)                                                                null,
    local_url           varchar(500)                                                                null,
    media_type          enum ('video', 'audio', 'image')                                            not null,
    data                json                                                                        null,
    platform            enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_media_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint media_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id),
    constraint media_archive_media_id_fk
        foreign key (canonical_id) references media (id)
)
    engine = InnoDB;

create index media_archive_archive_session_id_index
    on media_archive (archive_session_id);

create index media_archive_canonical_id_index
    on media_archive (canonical_id);

create index media_archive_id_on_platform_index
    on media_archive (id_on_platform);

create index media_archive_post_id_on_platform_index
    on media_archive (post_id_on_platform);

create index media_archive_post_url_suffix_index
    on media_archive (post_url_suffix);

create index media_archive_url_suffix_index
    on media_archive (url_suffix);

create table media_part
(
    id                    int auto_increment
        primary key,
    create_date           timestamp default CURRENT_TIMESTAMP not null,
    update_date           timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    media_id              int                                 not null,
    crop_area             varchar(100)                        null,
    timestamp_range_start float                               null,
    timestamp_range_end   float                               null,
    constraint media_part_media_id_fk
        foreign key (media_id) references media (id)
)
    engine = InnoDB;

create index media_part_media_id_index
    on media_part (media_id);

create fulltext index idx_search_fulltext
    on post (caption, url_suffix);

create index post_account_id_index
    on post (account_id);

create index post_id_on_platform_index
    on post (id_on_platform);

create index post_publication_date_date
    on post ((cast(`publication_date` as date)));

create index post_publication_date_index
    on post (publication_date);

create index post_url_suffix_index
    on post (url_suffix);

create table post_archive
(
    id                     int auto_increment
        primary key,
    create_date            timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date            timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id           int                                                                         null,
    archive_session_id     int                                                                         null,
    id_on_platform         varchar(100)                                                                null,
    url_suffix             varchar(250)                                                                null,
    account_url_suffix     varchar(200)                                                                null,
    account_id_on_platform varchar(100)                                                                null,
    publication_date       datetime                                                                    null,
    caption                text                                                                        null,
    data                   json                                                                        null,
    platform               enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_post_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint post_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id),
    constraint post_archive_post_id_fk
        foreign key (canonical_id) references post (id)
)
    engine = InnoDB;

create index post_archive_account_id_on_platform_index
    on post_archive (account_id_on_platform);

create index post_archive_account_url_suffix_index
    on post_archive (account_url_suffix);

create index post_archive_archive_session_id_index
    on post_archive (archive_session_id);

create index post_archive_canonical_id_index
    on post_archive (canonical_id);

create index post_archive_id_on_platform_index
    on post_archive (id_on_platform);

create index post_archive_url_suffix_index
    on post_archive (url_suffix);

create table post_like
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform varchar(200)                        null,
    post_id        int                                 null,
    account_id     int                                 null,
    data           json                                null,
    notes          text                                null,
    constraint post_like_account_id_fk
        foreign key (account_id) references account (id),
    constraint post_like_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

create index post_like_account_id_index
    on post_like (account_id);

create index post_like_id_on_platform_index
    on post_like (id_on_platform);

create index post_like_post_id_index
    on post_like (post_id);

create table post_like_archive
(
    id                     int auto_increment
        primary key,
    create_date            timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date            timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id           int                                                                         null,
    archive_session_id     int                                                                         null,
    id_on_platform         varchar(200)                                                                null,
    post_id_on_platform    varchar(100)                                                                null,
    post_url_suffix        varchar(250)                                                                null,
    account_id_on_platform varchar(100)                                                                null,
    account_url_suffix     varchar(200)                                                                null,
    data                   json                                                                        null,
    platform               enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_post_like_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint post_like_archive_canonical_fk
        foreign key (canonical_id) references post_like (id),
    constraint post_like_archive_session_fk
        foreign key (archive_session_id) references archive_session (id)
)
    engine = InnoDB;

create index post_like_archive_canonical_id_index
    on post_like_archive (canonical_id);

create index post_like_archive_id_on_platform_index
    on post_like_archive (id_on_platform);

create index post_like_archive_post_id_on_platform_index
    on post_like_archive (post_id_on_platform);

create index post_like_archive_session_id_index
    on post_like_archive (archive_session_id);

create table schema_migration
(
    version     int                                not null
        primary key,
    description varchar(200)                       not null,
    applied_at  datetime default CURRENT_TIMESTAMP not null
)
    engine = InnoDB;

create table tag_type
(
    id              int auto_increment
        primary key,
    create_date     timestamp  default CURRENT_TIMESTAMP not null,
    update_date     timestamp  default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    name            varchar(200)                         not null,
    description     text                                 null,
    notes           text                                 null,
    entity_affinity json                                 null comment 'e.g. ["account","post"] — which entity types this type is most used for. NULL = unrestricted.',
    quick_access    tinyint(1) default 0                 not null
)
    engine = InnoDB;

create table tag
(
    id                          int auto_increment
        primary key,
    create_date                 timestamp  default CURRENT_TIMESTAMP not null,
    update_date                 timestamp  default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    name                        varchar(200)                         not null,
    description                 text                                 null,
    tag_type_id                 int                                  null,
    quick_access                tinyint(1) default 0                 not null,
    omit_from_tag_type_dropdown tinyint(1) default 0                 not null,
    notes_recommended           tinyint(1) default 1                 not null,
    constraint name
        unique (name, tag_type_id),
    constraint tag_tag_type_id_fk
        foreign key (tag_type_id) references tag_type (id)
)
    engine = InnoDB;

create table account_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    account_id  int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint account_id
        unique (account_id, tag_id),
    constraint account_tag_account_id_fk
        foreign key (account_id) references account (id),
    constraint account_tag_tag_id_fk
        foreign key (tag_id) references tag (id)
)
    engine = InnoDB;

create index idx_account_tag_tag_id
    on account_tag (tag_id);

create table media_part_tag
(
    id            int auto_increment
        primary key,
    create_date   timestamp default CURRENT_TIMESTAMP not null,
    update_date   timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    media_part_id int                                 not null,
    tag_id        int                                 not null,
    notes         text                                null,
    constraint media_part_id
        unique (media_part_id, tag_id),
    constraint media_part_tag_media_part_id_fk
        foreign key (media_part_id) references media_part (id),
    constraint media_part_tag_tag_id_fk
        foreign key (tag_id) references tag (id)
)
    engine = InnoDB;

create index idx_media_part_tag_tag_id
    on media_part_tag (tag_id);

create table media_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    media_id    int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint media_id
        unique (media_id, tag_id),
    constraint media_tag_media_id_fk
        foreign key (media_id) references media (id),
    constraint media_tag_tag_id_fk
        foreign key (tag_id) references tag (id)
)
    engine = InnoDB;

create index idx_media_tag_tag_id
    on media_tag (tag_id);

create table post_tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    post_id     int                                 not null,
    tag_id      int                                 not null,
    notes       text                                null,
    constraint post_id
        unique (post_id, tag_id),
    constraint post_tag_post_id_fk
        foreign key (post_id) references post (id),
    constraint post_tag_tag_id_fk
        foreign key (tag_id) references tag (id)
)
    engine = InnoDB;

create index idx_post_tag_tag_id
    on post_tag (tag_id);

create table tag_hierarchy
(
    id           int auto_increment
        primary key,
    create_date  timestamp default CURRENT_TIMESTAMP not null,
    update_date  timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    super_tag_id int                                 not null,
    sub_tag_id   int                                 not null,
    notes        text                                null,
    constraint super_tag_id
        unique (super_tag_id, sub_tag_id),
    constraint tag_hierarchy_sub_tag_id_fk
        foreign key (sub_tag_id) references tag (id),
    constraint tag_hierarchy_super_tag_id_fk
        foreign key (super_tag_id) references tag (id)
)
    engine = InnoDB;

create index idx_tag_hierarchy_sub_tag_id
    on tag_hierarchy (sub_tag_id);

create table tagged_account
(
    id                int auto_increment
        primary key,
    create_date       timestamp default CURRENT_TIMESTAMP not null,
    update_date       timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform    varchar(300)                        null,
    tagged_account_id int                                 null,
    post_id           int                                 null,
    media_id          int                                 null,
    tag_x_position    float                               null,
    tag_y_position    float                               null,
    data              json                                null,
    notes             text                                null,
    constraint tagged_account_account_id_fk
        foreign key (tagged_account_id) references account (id),
    constraint tagged_account_media_id_fk
        foreign key (media_id) references media (id),
    constraint tagged_account_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

create index tagged_account_id_on_platform_index
    on tagged_account (id_on_platform);

create index tagged_account_media_id_index
    on tagged_account (media_id);

create index tagged_account_post_id_index
    on tagged_account (post_id);

create index tagged_account_tagged_account_id_index
    on tagged_account (tagged_account_id);

create table tagged_account_archive
(
    id                            int auto_increment
        primary key,
    create_date                   timestamp default CURRENT_TIMESTAMP                                         not null,
    update_date                   timestamp default CURRENT_TIMESTAMP                                         not null on update CURRENT_TIMESTAMP invisible,
    canonical_id                  int                                                                         null,
    archive_session_id            int                                                                         null,
    id_on_platform                varchar(300)                                                                null,
    tagged_account_id_on_platform varchar(100)                                                                null,
    tagged_account_url_suffix     varchar(250)                                                                null,
    context_post_url_suffix       varchar(250)                                                                null,
    context_media_url_suffix      varchar(250)                                                                null,
    context_post_id_on_platform   varchar(100)                                                                null,
    context_media_id_on_platform  varchar(100)                                                                null,
    tag_x_position                float                                                                       null,
    tag_y_position                float                                                                       null,
    data                          json                                                                        null,
    platform                      enum ('instagram', 'facebook', 'telegram', 'youtube', 'twitter', 'threads') null,
    constraint uq_tagged_account_archive_canonical_session
        unique (canonical_id, archive_session_id),
    constraint tagged_account_archive_canonical_fk
        foreign key (canonical_id) references tagged_account (id),
    constraint tagged_account_archive_session_fk
        foreign key (archive_session_id) references archive_session (id)
)
    engine = InnoDB;

create index tagged_account_archive_canonical_id_index
    on tagged_account_archive (canonical_id);

create index tagged_account_archive_id_on_platform_index
    on tagged_account_archive (id_on_platform);

create index tagged_account_archive_session_id_index
    on tagged_account_archive (archive_session_id);

create index tagged_account_archive_tagged_id_on_platform_index
    on tagged_account_archive (tagged_account_id_on_platform);

create table user
(
    id                  int auto_increment
        primary key,
    create_date         datetime    default CURRENT_TIMESTAMP not null,
    update_date         timestamp   default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    email               varchar(200) charset utf8mb3          not null,
    locked              tinyint     default 0                 not null,
    password_hash       varchar(255) charset utf8mb3          null,
    password_alg        varchar(20) charset utf8mb3           null,
    password_set_at     datetime                              null,
    last_pwd_failure    datetime                              null,
    force_pwd_reset     tinyint     default 0                 not null,
    last_login          datetime                              null,
    login_attempts      int         default 0                 not null,
    admin               tinyint     default 0                 not null,
    totp_configured     tinyint(1)  default 0                 not null,
    totp_secret         varchar(64)                           null,
    totp_method         varchar(20) default 'totp'            null,
    totp_pending_secret varchar(64)                           null,
    totp_last_used_at   datetime                              null,
    constraint email
        unique (email)
)
    engine = InnoDB;

create table entity_share_link
(
    id                        int auto_increment
        primary key,
    create_date               timestamp default CURRENT_TIMESTAMP                                  null,
    update_date               timestamp default CURRENT_TIMESTAMP                                  null on update CURRENT_TIMESTAMP,
    created_by_user_id        int                                                                  not null,
    valid                     tinyint   default 1                                                  not null,
    entity                    enum ('archiving_session', 'account', 'post', 'media', 'media_part') not null,
    entity_id                 int                                                                  null,
    link_suffix               varchar(100)                                                         not null,
    include_screen_recordings tinyint   default 1                                                  not null,
    include_har               tinyint   default 1                                                  not null,
    password_hash             varchar(255)                                                         null,
    password_alg              varchar(20)                                                          null,
    constraint entity_share_link_pk
        unique (link_suffix),
    constraint entity_share_link_user_id_fk
        foreign key (created_by_user_id) references user (id)
)
    engine = InnoDB;

create index entity_share_link_entity_entity_id_index
    on entity_share_link (entity, entity_id);

create table pre_auth_token
(
    id          int auto_increment
        primary key,
    user_id     int                                   not null,
    token       varchar(64)                           not null,
    create_date datetime    default CURRENT_TIMESTAMP not null,
    expires_at  datetime                              not null,
    purpose     varchar(32) default 'unknown'         not null,
    constraint uq_pre_auth_token
        unique (token),
    constraint fk_pre_auth_user
        foreign key (user_id) references user (id)
            on delete cascade
)
    engine = InnoDB;

create table token
(
    id          int auto_increment
        primary key,
    user_id     int                                not null,
    create_date datetime default CURRENT_TIMESTAMP not null,
    last_use    datetime default CURRENT_TIMESTAMP not null,
    token       varchar(100) charset utf8mb3       not null,
    constraint token_token_uindex
        unique (token),
    constraint token_user_id_fk
        foreign key (user_id) references user (id)
)
    engine = InnoDB;

