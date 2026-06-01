import {
    E_ENTITY_TYPES,
    IAccountAuxiliaryCounts,
    IAccountInteractions,
    IAccountRelationsResponse,
    IArchiveSession,
    IArchiveSessionWithEntities,
    ICommentsResponse,
    IExtractedEntitiesNested,
    ILikesResponse,
    IMediaPart,
    IPostAuxiliaryCounts,
} from "../types/entities";
import server, {HTTP_METHODS} from "./server";
import {Fields, JsonLogicFunction} from "@react-awesome-query-builder/mui";
import {IQuickAccessTypeDropdown, ITagStat, ITagWithType} from "../types/tags";
import {getShareTokenFromHref} from "./linkSharing";

interface FlattenedEntitiesTransform {
    strip_raw_data?: boolean;
    local_files_root?: string | null;
    retain_only_media_with_local_files?: boolean;
}

interface NestedEntitiesTransform {
    retain_only_posts_with_media?: boolean;
    retain_only_accounts_with_posts?: boolean;
}

interface EntitiesTransformConfig {
    flattened_entities_transform?: FlattenedEntitiesTransform | null;
    nested_entities_transform?: NestedEntitiesTransform | null;
}

const appendIfDefined = (params: URLSearchParams, key: string, value: string | boolean | null | undefined) => {
    if (value !== undefined) params.append(key, value === null ? "" : String(value));
};

const transformConfigToQueryParams = (config: EntitiesTransformConfig): string => {
    const params = new URLSearchParams();
    const shareToken = getShareTokenFromHref();
    if (shareToken) params.append("st", shareToken);
    const f = config.flattened_entities_transform;
    if (f) {
        appendIfDefined(params, "lfr", f.local_files_root);
        appendIfDefined(params, "mwf", f.retain_only_media_with_local_files);
        appendIfDefined(params, "srd", f.strip_raw_data !== undefined ? (f.strip_raw_data ? "1" : "0") : undefined);
    }
    const n = config.nested_entities_transform;
    if (n) {
        appendIfDefined(params, "pwm", n.retain_only_posts_with_media);
        appendIfDefined(params, "awp", n.retain_only_accounts_with_posts);
    }
    return params.toString();
}

const parseAccountTagsMap = (raw: Record<string, ITagWithType[]> | undefined): Record<number, ITagWithType[]> =>
    raw ? Object.fromEntries(Object.entries(raw).map(([k, v]) => [Number(k), v])) : {};

export const fetchAccount = async (accountId: number | string, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    const result = await server.get("account/" + accountId + "?" + transformConfigToQueryParams(config));
    return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
}

export const fetchPost = async (postId: number | string, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    const result = await server.get("post/" + postId + "?" + transformConfigToQueryParams(config));
    return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
}

export const fetchMedia = async (mediaId: number | string, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    return await server.get("media/" + mediaId + "?" + transformConfigToQueryParams(config));
}

export const fetchArchivingSession = async (archivingSessionId: number | string, config: EntitiesTransformConfig): Promise<IArchiveSessionWithEntities> => {
    return await server.get("archiving_session/" + archivingSessionId + "?" + transformConfigToQueryParams(config));
}

export const fetchAccountData = async (accountId: number): Promise<Record<string, unknown>> => {
    return await server.get(`account/data/${accountId}/`);
}

export const fetchPostData = async (postId: number): Promise<Record<string, unknown>> => {
    return await server.get(`post/data/${postId}/`);
}

export const fetchMediaData = async (mediaId: number): Promise<Record<string, unknown>> => {
    return await server.get(`media/data/${mediaId}/`);
}

export const fetchMediaParts = async (mediaId: number): Promise<IMediaPart[]> => {
    return await server.get(`media/parts/${mediaId}/`);
}

export const fetchPostComments = async (postId: number): Promise<ICommentsResponse> => {
    const result = await server.get(`post/${postId}/comments/`);
    return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
}

export const fetchPostLikes = async (postId: number): Promise<ILikesResponse> => {
    const result = await server.get(`post/${postId}/likes/`);
    return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
}

export const fetchAccountRelations = async (accountId: number): Promise<IAccountRelationsResponse | null> => {
    try {
        const result = await server.get(`account/${accountId}/relations/`);
        return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
    } catch {
        return null;
    }
}

export const fetchAccountInteractions = async (accountId: number): Promise<IAccountInteractions | null> => {
    try {
        const result = await server.get(`account/${accountId}/interactions/`);
        return {...result, account_tags: parseAccountTagsMap(result.account_tags)};
    } catch {
        return null;
    }
}

export const fetchAccountAuxiliaryCounts = async (accountId: number): Promise<IAccountAuxiliaryCounts | null> => {
    try {
        return await server.get(`account/${accountId}/auxiliary-counts/`, {ignoreErrors: true});
    } catch {
        return null;
    }
}

export const fetchPostAuxiliaryCounts = async (postId: number): Promise<IPostAuxiliaryCounts | null> => {
    try {
        return await server.get(`post/${postId}/auxiliary-counts/`, {ignoreErrors: true});
    } catch {
        return null;
    }
}

export const fetchArchivingSessionsAccount = async (accountId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/account/${accountId}/?${transformConfigToQueryParams(config)}`);
}

export const fetchArchivingSessionsPost = async (postId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/post/${postId}/?${transformConfigToQueryParams(config)}`);
}

export const fetchArchivingSessionsMedia = async (mediaId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/media/${mediaId}/?${transformConfigToQueryParams(config)}`);
}

export const lookupTags = async (tagQuery: string, entity?: E_ENTITY_TYPES): Promise<ITagWithType[]> => {
    const params = new URLSearchParams({q: tagQuery});
    if (entity) params.append('entity', entity);
    return await server.get(`tags/?${params}`);
}

export const SEARCH_MODE_TO_ENTITY: Partial<Record<T_Search_Mode, E_ENTITY_TYPES>> = {
    accounts: 'account',
    posts: 'post',
    media: 'media',
};

export const fetchTagsForSearchResults = async (
    mode: T_Search_Mode,
    ids: number[]
): Promise<Record<number, ITagWithType[]>> => {
    const entity = SEARCH_MODE_TO_ENTITY[mode];
    if (!entity || ids.length === 0) return {};
    const result = await server.get(`tags/by-entities/?entity=${entity}&ids=${ids.join(',')}`);
    return Object.fromEntries(Object.entries(result).map(([k, v]) => [Number(k), v as ITagWithType[]]));
};

export const batchAnnotate = async (
    entityType: E_ENTITY_TYPES,
    entityIds: number[],
    tags: Array<{id: number; notes?: string | null}>
): Promise<void> => {
    await server.post('annotate/batch', {entity_type: entityType, entity_ids: entityIds, tags});
};

export const SEARCH_MODES: readonly { key: string, label: string }[] = [
    {key: 'accounts', label: 'Accounts'},
    {key: 'posts', label: 'Posts'},
    {key: 'media', label: 'Media'},
    {key: 'archive_sessions', label: 'Archive Sessions'},
] as const;

export type T_Search_Mode = typeof SEARCH_MODES[number]['key'];

export const DEFAULT_PAGE_SIZES: Partial<Record<T_Search_Mode, number>> = {media: 100};
export const defaultPageSize = (mode: T_Search_Mode): number => DEFAULT_PAGE_SIZES[mode] ?? 20;

// Combined "Sort By" dropdown options per search mode. Each entry maps to a {sort_by, sort_order}
// pair sent to the server; the first entry ('default') preserves the server's default ordering
// (relevance while searching, id/date otherwise). archive_sessions is intentionally absent → no control.
export interface SortOption {
    key: string;
    label: string;
    sort_by: string | null;
    sort_order: 'asc' | 'desc' | null;
}

const POST_MEDIA_SORT_OPTIONS: SortOption[] = [
    {key: 'default', label: 'Best match', sort_by: null, sort_order: null},
    {key: 'date_desc', label: 'Newest first', sort_by: 'publication_date', sort_order: 'desc'},
    {key: 'date_asc', label: 'Oldest first', sort_by: 'publication_date', sort_order: 'asc'},
    {key: 'id_desc', label: 'Recently added', sort_by: 'id', sort_order: 'desc'},
    {key: 'id_asc', label: 'First added', sort_by: 'id', sort_order: 'asc'},
];

export const SORT_OPTIONS: Partial<Record<T_Search_Mode, SortOption[]>> = {
    accounts: [
        {key: 'default', label: 'Best match', sort_by: null, sort_order: null},
        {key: 'id_desc', label: 'Recently added', sort_by: 'id', sort_order: 'desc'},
        {key: 'id_asc', label: 'First added', sort_by: 'id', sort_order: 'asc'},
        {key: 'handle_az', label: 'Handle A–Z', sort_by: 'url_suffix', sort_order: 'asc'},
        {key: 'handle_za', label: 'Handle Z–A', sort_by: 'url_suffix', sort_order: 'desc'},
        {key: 'name_az', label: 'Name A–Z', sort_by: 'display_name', sort_order: 'asc'},
        {key: 'name_za', label: 'Name Z–A', sort_by: 'display_name', sort_order: 'desc'},
    ],
    posts: POST_MEDIA_SORT_OPTIONS,
    media: POST_MEDIA_SORT_OPTIONS,
};

// Resolve the active option key from a query, for use as the <Select value>.
export const sortKeyFromQuery = (q: ISearchQuery): string => {
    const opts = SORT_OPTIONS[q.search_mode];
    if (!opts) return 'default';
    return (opts.find(o => o.sort_by === (q.sort_by ?? null)
        && o.sort_order === (q.sort_order ?? null)) ?? opts[0]).key;
};

const disabled_operators_by_type: { [key: string]: string[] } = {
    'text': ['starts_with', 'ends_with', 'proximity'],
}

export const ADVANCED_FILTERS_CONFIG: { [key: T_Search_Mode]: Fields } = {
    'accounts': {
        url_parts: {
            label: 'User Name',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        display_name: {
            label: 'Display Name',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        bio: {
            label: 'Bio',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        data: {
            label: 'Account Data (Slow)',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        post_count: {
            label: 'Posts Archived',
            type: 'number',
        },
    },
    'posts': {
        publication_date: {
            label: 'Publication Date',
            type: 'date',
        },
        caption: {
            label: 'Caption',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        data: {
            label: 'Post Data (Slow)',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        url: {
            label: 'Post URL',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
    },
    'media': {
        publication_date: {
            label: 'Publication Date',
            type: 'date',
        },
        media_type: {
            label: 'Media Type',
            type: 'select',
            fieldSettings: {
                listValues: [
                    {value: 'video', title: 'Video'},
                    {value: 'image', title: 'Photo'},
                ],
            },
        },
        annotation: {
            label: 'AI Generated Caption',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        data: {
            label: 'Media Data (Slow)',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
    },
    'archive_sessions': {
        archiving_timestamp: {
            label: 'Archiving Date',
            type: 'date',
        },
        archived_url: {
            label: 'Archived URL',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        notes: {
            label: 'Notes',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        structures: {
            label: 'Full Accounts / Posts Data (Slow)',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
    }
}

export interface ISearchQuery {
    search_mode: T_Search_Mode;
    search_term: string;
    advanced_filters: JsonLogicFunction | null;
    page_number: number;
    page_size: number;
    tag_ids?: number[];
    tag_filter_mode?: "any" | "all";
    tag_scopes?: E_ENTITY_TYPES[];
    sort_by?: string | null;
    sort_order?: 'asc' | 'desc' | null;
}

export interface Thumbnail {
    src: string;
    aspect_ratio: number | null;
}


export interface SearchResult {
    page: string,
    id: number,
    title: string,
    details?: string;
    thumbnails?: Thumbnail[];
    metadata?: Record<string, any>;
}

export const searchData = async (
    query: ISearchQuery,
    options: { signal: AbortSignal }
): Promise<SearchResult[]> => {
    return await server.post("search/", query, HTTP_METHODS.post, {abortSignal: options.signal});
}

export const fetchRelatedTagStats = async (accountId: number): Promise<ITagStat[]> => {
    return await server.get(`account/${accountId}/related_tag_stats/`);
}

export interface TieWeights {
    follow: number;
    suggested: number;
    like: number;
    comment: number;
    tag: number;
}

export const DEFAULT_TIE_WEIGHTS: TieWeights = {
    follow: 1,
    suggested: 0,
    like: 1,
    comment: 1,
    tag: 1,
};

export interface CandidateAccount {
    id: number;
    url_suffix: string | null;
    display_name: string | null;
    bio: string | null;
    is_verified: boolean | null;
    score: number;
    kernel_connections: number;
    thumbnails: Thumbnail[];
    media_count: number;
}

export interface CommunityCandidatesResponse {
    candidates: CandidateAccount[];
}

export const fetchCommunityCandidates = async (
    kernelIds: number[],
    excludedIds: number[],
    weights: TieWeights,
): Promise<CommunityCandidatesResponse> => {
    return await server.post('community/candidates/', {
        kernel_ids: kernelIds,
        excluded_ids: excludedIds,
        weights,
    });
};

export interface TagKernelAccount {
    id: number;
    url_suffix: string | null;
    display_name: string | null;
    bio: string | null;
    thumbnails: Thumbnail[];
    media_count: number;
    applied_tags: ITagWithType[];
}

export interface TagKernelResponse {
    accounts: TagKernelAccount[];
    dropdown: IQuickAccessTypeDropdown;
}

export const fetchTagKernelAccounts = async (
    tagId: number,
): Promise<TagKernelResponse> =>
    server.get(`community/tag-kernel/${tagId}`);

export const removeAccountTag = async (
    accountId: number,
    tagId: number,
): Promise<void> =>
    server.post(`annotate/account/${accountId}/tag/${tagId}`, {}, HTTP_METHODS.delete);
