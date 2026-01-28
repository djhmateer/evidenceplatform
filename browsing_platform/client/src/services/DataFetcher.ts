import {IArchiveSession, IArchiveSessionWithEntities, IExtractedEntitiesNested, IMediaPart} from "../types/entities";
import server, {HTTP_METHODS} from "./server";
import {Fields, JsonLogicFunction} from "@react-awesome-query-builder/mui";
import {ITagWithType} from "../types/tags";
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

const entitiesTransformConfigToQueryParams = (config: EntitiesTransformConfig): string => {
    const params = new URLSearchParams();
    const shareToken = getShareTokenFromHref()
    if (shareToken){
        params.append("st", shareToken);
    }
    if (config.flattened_entities_transform) {
        if (config.flattened_entities_transform.local_files_root !== undefined) {
            params.append("lfr", config.flattened_entities_transform.local_files_root || "");
        }
        if (config.flattened_entities_transform.retain_only_media_with_local_files !== undefined) {
            params.append("mwf", String(config.flattened_entities_transform.retain_only_media_with_local_files));
        }
        if (config.flattened_entities_transform.strip_raw_data !== undefined) {
            params.append("srd", config.flattened_entities_transform.strip_raw_data ? "1" : "0");
        }
    }
    if (config.nested_entities_transform) {
        if (config.nested_entities_transform.retain_only_posts_with_media !== undefined) {
            params.append("pwm", String(config.nested_entities_transform.retain_only_posts_with_media));
        }
        if (config.nested_entities_transform.retain_only_accounts_with_posts !== undefined) {
            params.append("awp", String(config.nested_entities_transform.retain_only_accounts_with_posts));
        }
    }
    return params.toString();
}

const sessionsTransformConfigToQueryParams = (config: EntitiesTransformConfig): string => {
    const params = new URLSearchParams();
    const shareToken = getShareTokenFromHref()
    if (shareToken){
        params.append("st", shareToken);
    }
    if (config.flattened_entities_transform) {
        if (config.flattened_entities_transform.local_files_root !== undefined) {
            params.append("lfr", config.flattened_entities_transform.local_files_root || "");
        }
    }
    return params.toString();
}

export const fetchAccount = async (accountId: number, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    return await server.get("account/" + accountId + "?" + entitiesTransformConfigToQueryParams(config));
}

export const fetchPost = async (postId: number, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    return await server.get("post/" + postId + "?" + entitiesTransformConfigToQueryParams(config));
}

export const fetchMedia = async (mediaId: number, config: EntitiesTransformConfig): Promise<IExtractedEntitiesNested> => {
    return await server.get("media/" + mediaId + "?" + entitiesTransformConfigToQueryParams(config));
}

export const fetchArchivingSession = async (archivingSessionId: number, config: EntitiesTransformConfig): Promise<IArchiveSessionWithEntities> => {
    return await server.get("archiving_session/" + archivingSessionId + "?" + entitiesTransformConfigToQueryParams(config));
}

export const fetchAccountData = async (accountId: number): Promise<any> => {
    return await server.get(`account/data/${accountId}/`);
}

export const fetchPostData = async (postId: number): Promise<any> => {
    return await server.get(`post/data/${postId}/`);
}

export const fetchMediaData = async (mediaId: number): Promise<any> => {
    return await server.get(`media/data/${mediaId}/`);
}

export const fetchMediaParts = async (mediaId: number): Promise<IMediaPart[]> => {
    return await server.get(`media/parts/${mediaId}/`);
}

export const fetchArchivingSessionData = async (archivingSessionId: number): Promise<any> => {
    return await server.get(`archiving_session/data/${archivingSessionId}/`);
}

export const fetchArchivingSessionsAccount = async (accountId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/account/${accountId}/?${sessionsTransformConfigToQueryParams(config)}`);
}

export const fetchArchivingSessionsPost = async (postId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/post/${postId}/?${sessionsTransformConfigToQueryParams(config)}`);
}

export const fetchArchivingSessionsMedia = async (mediaId: number, config: EntitiesTransformConfig): Promise<IArchiveSession[]> => {
    return await server.get(`archiving_session/media/${mediaId}/?${sessionsTransformConfigToQueryParams(config)}`);
}

export const lookupTags = async (tagQuery: string): Promise<ITagWithType[]> => {
    return await server.get(`tags/?q=` + encodeURIComponent(tagQuery));
}

export const SEARCH_MODES: readonly { key: string, label: string }[] = [
    {key: 'accounts', label: 'Accounts'},
    {key: 'posts', label: 'Posts'},
    {key: 'media', label: 'Media'},
    {key: 'archive_sessions', label: 'Archive Sessions'},
    //{key: 'all', label: 'All'},
] as const;

export type T_Search_Mode = typeof SEARCH_MODES[number]['key'];


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
        notes: {
            label: 'Notes',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        data: {
            label: 'Account Data (Slow)',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
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
        notes: {
            label: 'Notes',
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
        ai_caption: {
            label: 'AI Generated Caption',
            type: 'text',
            excludeOperators: disabled_operators_by_type['text'],
        },
        notes: {
            label: 'Notes',
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
}

export interface SearchResult {
    page: string,
    id: number,
    title: string,
    details?: string;
    thumbnails?: string[]
}

export const searchData = async (
    query: ISearchQuery,
    options: { signal: AbortSignal }
): Promise<SearchResult[]> => {
    return await server.post("search/", query, HTTP_METHODS.post, {abortSignal: options.signal});
}