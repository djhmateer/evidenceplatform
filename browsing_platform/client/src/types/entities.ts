import {ITagWithType} from "./tags";


export type E_ENTITY_TYPES = "archiving_session" | "account" | "post" | "media" | "media_part"

interface IEntityBase {
    id?: number;
    created_at?: string; // ISO date string
    updated_at?: string;
    canonical_id?: number;
    tags?: ITagWithType[];
}

interface IAccount extends IEntityBase {
    id_on_platform?: string;
    url: string;
    url_suffix: string;
    display_name?: string;
    bio?: string;
    data?: any;
    identifiers?: string[]
}

interface IPost extends IEntityBase {
    id_on_platform: string;
    url?: string;
    url_suffix: string;
    account_id?: number;
    account_id_on_platform?: string;
    account_url?: string;
    publication_date?: string;
    caption?: string;
    data?: any;
}

type EMediaType = 'video' | 'audio' | 'image';

export interface IMedia extends IEntityBase {
    id_on_platform?: string;
    url: string;
    url_suffix: string;
    post_id?: number;
    post_id_on_platform?: string;
    post_url?: string;
    local_url?: string;
    thumbnail_path?: string;
    aspect_ratio?: number;
    media_type: EMediaType;
    data?: any;
}

export interface IMediaPart extends IEntityBase {
    media_id?: number;
    timestamp_range_start?: number;
    timestamp_range_end?: number;
    crop_area?: number[];
}

export interface IComment extends IEntityBase {
    id_on_platform?: string;
    url: string;
    post_id?: number;
    post_id_on_platform: string;
    post_url?: string;
    account_id?: number;
    account_id_on_platform?: string;
    account_url?: string;
    account_display_name?: string;
    text?: string;
    publication_date?: string;
    parent_comment_id_on_platform?: string;
    post_publication_date?: string;
    post_author_account_id?: number;
    post_author_url_suffix?: string;
    post_author_display_name?: string;
    data?: any;
}

export interface IPostLike extends IEntityBase {
    id_on_platform?: string;
    post_id?: number;
    post_id_on_platform?: string;
    post_url?: string;
    account_id?: number;
    account_id_on_platform?: string;
    account_url?: string;
    account_display_name?: string;
    post_publication_date?: string;
    post_author_account_id?: number;
    post_author_url_suffix?: string;
    post_author_display_name?: string;
    data?: any;
}

export interface IAccountRelation extends IEntityBase {
    id_on_platform?: string;
    follower_account_id?: number;
    follower_account_id_on_platform?: string;
    follower_account_url?: string;
    follower_account_display_name?: string;
    followed_account_id?: number;
    followed_account_id_on_platform?: string;
    followed_account_url?: string;
    followed_account_display_name?: string;
    relation_type?: string;
    data?: any;
}

export interface ITaggedAccount extends IEntityBase {
    id_on_platform?: string;
    tagged_account_id?: number;
    tagged_account_id_on_platform?: string;
    tagged_account_url?: string;
    tagged_account_display_name?: string;
    post_id?: number;
    context_post_url?: string;
    context_media_url?: string;
    context_post_id_on_platform?: string;
    context_media_id_on_platform?: string;
    tag_x_position?: number;
    tag_y_position?: number;
    post_publication_date?: string;
    post_author_account_id?: number;
    post_author_url_suffix?: string;
    post_author_display_name?: string;
    data?: any;
}

interface IExtractedEntitiesFlattened {
    accounts: IAccount[];
    posts: IPost[];
    media: IMedia[];
    comments: IComment[];
    likes: IPostLike[];
    account_relations: IAccountRelation[];
    tagged_accounts: ITaggedAccount[];
}

export interface IMediaAndAssociatedEntities extends IMedia {
    media_parent_post?: IPostAndAssociatedEntities;
    media_parts?: IMediaPart[];
}

export interface IPostAndAssociatedEntities extends IPost {
    post_author?: IAccountAndAssociatedEntities;
    post_media: IMediaAndAssociatedEntities[];
    post_comments: IComment[];
    post_likes: IPostLike[];
    post_tagged_accounts: ITaggedAccount[];
}

export interface IAccountAndAssociatedEntities extends IAccount {
    account_posts: IPostAndAssociatedEntities[];
    account_relations: IAccountRelation[];
}

export interface IExtractedEntitiesNested {
    accounts: IAccountAndAssociatedEntities[];
    posts: IPostAndAssociatedEntities[];
    media: IMediaAndAssociatedEntities[];
    account_tags?: Record<number, ITagWithType[]>;
}

interface ISessionAttachments {
    screen_recordings: string[];
    screen_shots: string[];
    wacz_archives: string[];
    har_archives: string[];
    hash_files: string[];
    timestamp_files: string[];
    other_files: string[];
}

export interface IArchiveSession {
    id?: number;
    create_date?: string;
    update_date?: string;
    external_id?: string;
    archived_url?: string;
    archive_location?: string;
    summary_html?: string;
    parse_algorithm_version?: number;
    structures?: Record<string, any>;
    metadata?: Record<string, any>;
    attachments?: ISessionAttachments;
    attachments_redacted?: string[];
    extract_algorithm_version?: number;
    archiving_timestamp?: string;
    notes?: string;
    extraction_error?: string;
    source_type: 'AA_xlsx' | 'local_har' | 'local_wacz';
    incorporation_status?: 'pending' | 'parse_failed' | 'parsed' | 'extract_failed' | 'done';
}

/** Entities that support annotation (notes + tags). Extend this union when adding annotation support to a new entity type. */
export type IAnnotatableEntity = IMedia | IPost | IAccount;
export type AnnotatableEntityType = "media" | "post" | "account";

export interface IArchiveSessionWithEntities {
    session: IArchiveSession;
    entities: IExtractedEntitiesNested;
}

export interface IAccountInteractions {
    comments: IComment[];
    likes: IPostLike[];
    tagged_in: ITaggedAccount[];
    account_tags?: Record<number, ITagWithType[]>;
}

export interface IAccountRelationsResponse {
    relations: IAccountRelation[];
    account_tags: Record<number, ITagWithType[]>;
}

export interface ICommentsResponse {
    comments: IComment[];
    account_tags: Record<number, ITagWithType[]>;
}

export interface ILikesResponse {
    likes: IPostLike[];
    account_tags: Record<number, ITagWithType[]>;
}

interface IAccountInteractionCounts {
    comments_count: number;
    likes_count: number;
    tagged_in_count: number;
}

export interface IAccountAuxiliaryCounts {
    relations_count: number;
    interaction_counts: IAccountInteractionCounts;
}

export interface IPostAuxiliaryCounts {
    comments_count: number;
    likes_count: number;
}

export interface IAttributionAffiliationCounts {
    total: number;
    uncertain: number;
}

export interface IAttributionContester {
    id: number;
    id_on_platform?: string;
    url_suffix?: string;
    display_name?: string;
}

export interface IAttributionReport {
    account_id: number;
    url_suffix?: string;
    contested: boolean;
    contesting_accounts: IAttributionContester[];
    uncertain_affiliations: {
        posts_authored?: IAttributionAffiliationCounts;
        comments?: IAttributionAffiliationCounts;
        post_likes?: IAttributionAffiliationCounts;
        tagged_in_posts?: IAttributionAffiliationCounts;
    };
    note?: string;
}