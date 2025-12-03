create table account
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform varchar(100)                        null,
    url            varchar(200)                        not null,
    display_name   varchar(100)                        null,
    bio            varchar(200)                        null,
    data           json                                null,
    notes          text                                null,
    url_parts      text                                null
)
    engine = InnoDB;

create index account_bio_index
    on account (bio);

create index account_display_name_index
    on account (display_name);

create index account_id_on_platform_index
    on account (id_on_platform);

create index account_url_index
    on account (url);

create fulltext index idx_search_fulltext
    on account (url, url_parts, display_name, bio, notes);

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

create table archive_session
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
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
)
    engine = InnoDB;

create table account_archive
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP not null,
    update_date        timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    canonical_id       int                                 null,
    archive_session_id int                                 null,
    id_on_platform     varchar(100)                        null,
    url                varchar(200)                        not null,
    display_name       varchar(100)                        null,
    bio                varchar(200)                        null,
    data               json                                null,
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

create index account_archive_url_index
    on account_archive (url);

create table account_relation_archive
(
    id                              int auto_increment
        primary key,
    create_date                     timestamp default CURRENT_TIMESTAMP not null,
    update_date                     timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    canonical_id                    int                                 null,
    archive_session_id              int                                 null,
    id_on_platform                  varchar(100)                        null,
    followed_account_url            varchar(200)                        not null,
    followed_account_id_on_platform varchar(100)                        null,
    follower_account_url            varchar(200)                        not null,
    follower_account_id_on_platform varchar(100)                        null,
    relation_type                   varchar(30)                         null,
    data                            json                                null,
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

create index account_relation_archive_followed_account_url_index
    on account_relation_archive (followed_account_url);

create index account_relation_archive_follower_account_id_on_platform_index
    on account_relation_archive (follower_account_id_on_platform);

create index account_relation_archive_follower_account_url_index
    on account_relation_archive (follower_account_url);

create index account_relation_archive_id_on_platform_index
    on account_relation_archive (id_on_platform);

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
    engine = InnoDB
    charset = utf8mb3;

create table post
(
    id               int auto_increment
        primary key,
    create_date      timestamp default CURRENT_TIMESTAMP not null,
    update_date      timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform   varchar(100)                        null,
    url              varchar(250)                        not null,
    account_id       int                                 null,
    publication_date datetime                            null,
    caption          text                                null,
    data             json                                null,
    notes            text                                null,
    constraint post_account_id_fk
        foreign key (account_id) references account (id)
)
    engine = InnoDB;

create table media
(
    id             int auto_increment
        primary key,
    create_date    timestamp default CURRENT_TIMESTAMP not null,
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform varchar(100)                        null,
    url            varchar(250)                        not null,
    post_id        int                                 null,
    local_url      varchar(500)                        null,
    media_type     enum ('video', 'audio', 'image')    not null,
    data           json                                null,
    notes          text                                null,
    annotation     text                                null,
    thumbnail_path varchar(200)                        null,
    constraint media_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

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
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    canonical_id        int                                 null,
    archive_session_id  int                                 null,
    id_on_platform      varchar(100)                        null,
    url                 varchar(250)                        not null,
    post_url            varchar(250)                        null,
    post_id_on_platform varchar(100)                        null,
    local_url           varchar(500)                        null,
    media_type          enum ('video', 'audio', 'image')    not null,
    data                json                                null,
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

create index media_archive_post_url_index
    on media_archive (post_url);

create index media_archive_url_index
    on media_archive (url);

create table media_part
(
    id                    int auto_increment
        primary key,
    create_date           timestamp default CURRENT_TIMESTAMP not null,
    update_date           timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    media_id              int                                 not null,
    crop_area             varchar(100)                        null,
    notes                 text                                null,
    timestamp_range_start float                               null,
    timestamp_range_end   float                               null,
    constraint media_part_media_id_fk
        foreign key (media_id) references media (id)
)
    engine = InnoDB;

create index media_part_media_id_index
    on media_part (media_id);

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
    update_date            timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    canonical_id           int                                 null,
    archive_session_id     int                                 null,
    id_on_platform         varchar(100)                        null,
    url                    varchar(250)                        not null,
    account_url            varchar(200)                        null,
    account_id_on_platform varchar(100)                        null,
    publication_date       datetime                            null,
    caption                text                                null,
    data                   json                                null,
    constraint post_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id),
    constraint post_archive_post_id_fk
        foreign key (canonical_id) references post (id)
)
    engine = InnoDB;

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
    update_date    timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    id_on_platform varchar(100)                        null,
    url            varchar(250)                        not null,
    post_id        int                                 null,
    account_id     int                                 null,
    notes          text                                null,
    constraint post_engagement_account_id_fk
        foreign key (account_id) references account (id),
    constraint post_engagement_post_id_fk
        foreign key (post_id) references post (id)
)
    engine = InnoDB;

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
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    canonical_id        int                                 null,
    archive_session_id  int                                 null,
    id_on_platform      varchar(100)                        null,
    url                 varchar(250)                        not null,
    post_url            varchar(250)                        null,
    post_id_on_platform varchar(100)                        null,
    engagement_date     datetime                            null,
    caption             text                                null,
    data                json                                null,
    constraint post_engagement_archive_archive_session_id_fk
        foreign key (archive_session_id) references archive_session (id),
    constraint post_engagement_archive_post_engagement_id_fk
        foreign key (canonical_id) references post_engagement (id)
)
    engine = InnoDB;

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

create table tag_type
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    name        varchar(200)                        not null,
    description text                                null,
    notes       text                                null
)
    engine = InnoDB;

create table tag
(
    id          int auto_increment
        primary key,
    create_date timestamp default CURRENT_TIMESTAMP not null,
    update_date timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    name        varchar(200)                        not null,
    description text                                null,
    tag_type_id int                                 null,
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

create table post_engagement_tag
(
    id                 int auto_increment
        primary key,
    create_date        timestamp default CURRENT_TIMESTAMP not null,
    update_date        timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    post_engagement_id int                                 not null,
    tag_id             int                                 not null,
    notes              text                                null,
    constraint post_engagement_id
        unique (post_engagement_id, tag_id),
    constraint post_engagement_tag_post_engagement_id_fk
        foreign key (post_engagement_id) references post_engagement (id),
    constraint post_engagement_tag_tag_id_fk
        foreign key (tag_id) references tag (id)
)
    engine = InnoDB;

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

create table tag_hierarchy
(
    id                  int auto_increment
        primary key,
    create_date         timestamp default CURRENT_TIMESTAMP not null,
    update_date         timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    super_tag_id        int                                 not null,
    sub_tag_id          int                                 not null,
    temporal_constraint varchar(100)                        null,
    notes               text                                null,
    constraint super_tag_id
        unique (super_tag_id, sub_tag_id),
    constraint tag_hierarchy_sub_tag_id_fk
        foreign key (sub_tag_id) references tag (id),
    constraint tag_hierarchy_super_tag_id_fk
        foreign key (super_tag_id) references tag (id)
)
    engine = InnoDB;

create table user
(
    id               int auto_increment
        primary key,
    create_date      datetime  default CURRENT_TIMESTAMP not null,
    update_date      timestamp default CURRENT_TIMESTAMP not null on update CURRENT_TIMESTAMP invisible,
    email            varchar(200) charset utf8mb3        not null,
    locked           tinyint   default 0                 not null,
    password_hash    varchar(255) charset utf8mb3        null,
    password_alg     varchar(20) charset utf8mb3         null,
    password_set_at  datetime                            null,
    last_pwd_failure datetime                            null,
    force_pwd_reset  tinyint   default 0                 not null,
    last_login       datetime                            null,
    login_attempts   int       default 0                 not null,
    admin            tinyint   default 0                 not null,
    constraint email
        unique (email)
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

