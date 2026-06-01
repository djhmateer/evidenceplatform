import React, {useEffect, useRef, useState} from 'react';
import {useLocation, useNavigate, useSearchParams} from 'react-router';
import {Box, Button, IconButton, Stack, Tooltip, useMediaQuery} from '@mui/material';
import GridViewIcon from '@mui/icons-material/GridView';
import ViewComfyIcon from '@mui/icons-material/ViewComfy';
import {ITagWithType} from '../types/tags';
import {E_ENTITY_TYPES} from '../types/entities';
import {VALID_TAG_SCOPES, defaultScopesFor, isDefaultScopes} from '../lib/tagScopes';
import {
    ADVANCED_FILTERS_CONFIG,
    batchAnnotate,
    defaultPageSize,
    fetchTagsForSearchResults,
    ISearchQuery,
    SEARCH_MODE_TO_ENTITY,
    SEARCH_MODES,
    searchData,
    SearchResult,
    T_Search_Mode,
} from '../services/DataFetcher';
import TopNavBar from '../UIComponents/TopNavBar/TopNavBar';
import {useSearchHistory} from '../lib/useSearchHistory';
import SearchPanel, {SearchPanelTagging} from '../UIComponents/Search/SearchPanel';
import {JsonLogicFunction, MuiConfig, Utils as QbUtils} from '@react-awesome-query-builder/mui';
import rison from 'rison';
import {removeUndefinedValues} from '../services/utils';

const InitialConfig = MuiConfig;

const emptyFiltersCache: Partial<Record<T_Search_Mode, unknown>> = {};
const getEmptyFilters = (mode: T_Search_Mode) => {
    if (!(mode in emptyFiltersCache)) {
        emptyFiltersCache[mode] = QbUtils.Export.jsonLogicFormat(
            QbUtils.loadTree({id: QbUtils.uuid(), type: 'group', children1: []}),
            {...InitialConfig, fields: ADVANCED_FILTERS_CONFIG[mode]}
        ).logic;
    }
    return emptyFiltersCache[mode];
};

const extractQueryFromParams = (searchParams: URLSearchParams): ISearchQuery => {
    const search_mode = (() => {
        const raw = searchParams.get('sm') || 'accounts';
        return SEARCH_MODES.map(m => m.key).includes(raw) ? raw as T_Search_Mode : 'accounts';
    })();
    const modeDefault = defaultPageSize(search_mode);
    const advancedFiltersRaw = searchParams.get('f');
    const advanced_filters: JsonLogicFunction | null = advancedFiltersRaw ? (() => {
        try { return rison.decode(advancedFiltersRaw); } catch { return null; }
    })() : null;
    return {
        search_term: searchParams.get('s') || '',
        search_mode,
        advanced_filters,
        page_number: Math.max(1, parseInt(searchParams.get('p') || '1', 10) || 1),
        page_size: Math.max(20, parseInt(searchParams.get('ps') || String(modeDefault), 10) || modeDefault),
        tag_ids: (searchParams.get('t') || '').split(',').map(Number).filter(n => !isNaN(n) && n > 0),
        tag_filter_mode: searchParams.get('tm') === 'all' ? 'all' : 'any',
        tag_scopes: ((): ISearchQuery['tag_scopes'] => {
            const raw = (searchParams.get('ts') || '')
                .split(',')
                .filter((s): s is E_ENTITY_TYPES => VALID_TAG_SCOPES.includes(s as E_ENTITY_TYPES));
            return raw.length ? raw : defaultScopesFor(SEARCH_MODE_TO_ENTITY[search_mode]);
        })(),
        sort_by: searchParams.get('sb') || null,
        sort_order: searchParams.get('so') === 'asc' ? 'asc' : searchParams.get('so') === 'desc' ? 'desc' : null,
    };
};

export default function SearchPage() {
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const isMobile = useMediaQuery('(max-width: 768px)');

    const query = extractQueryFromParams(searchParams);

    const [largeIcons, setLargeIcons] = useState<boolean>(
        () => localStorage.getItem('media_search_large_icons') === 'true'
    );

    const toggleLargeIcons = () => {
        setLargeIcons(prev => {
            const next = !prev;
            localStorage.setItem('media_search_large_icons', String(next));
            return next;
        });
    };

    const [results, setResults] = useState<SearchResult[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [tagsMap, setTagsMap] = useState<Record<number, ITagWithType[]>>({});
    const [taggingMode, setTaggingMode] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [bulkTags, setBulkTags] = useState<ITagWithType[]>([]);
    const abortControllerRef = useRef<AbortController | null>(null);
    const {addSearch, removeSearch, getSuggestions} = useSearchHistory();

    useEffect(() => {
        document.title = query.search_term
            ? `${query.search_term} | Search | Browsing Platform`
            : 'Search | Browsing Platform';
    }, [query.search_term]);

    useEffect(() => {
        if (abortControllerRef.current) abortControllerRef.current.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;
        setIsLoading(true);
        setTagsMap({});
        searchData(query, {signal: controller.signal}).then(r => {
            setResults(r);
            setIsLoading(false);
            abortControllerRef.current = null;
            const ids = r.map(x => x.id).filter((id): id is number => id != null);
            if (ids.length > 0) fetchTagsForSearchResults(query.search_mode, ids).then(setTagsMap);
        }).catch((e: any) => {
            if (e.name !== 'AbortError') { setIsLoading(false); abortControllerRef.current = null; }
        });
    }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

    const encodeQueryToParams = (q: ISearchQuery) => {
        const params = new URLSearchParams();
        if (q.search_term) params.append('s', q.search_term);
        const defaultFilters = getEmptyFilters(q.search_mode);
        if (q.advanced_filters && JSON.stringify(q.advanced_filters) !== JSON.stringify(defaultFilters)) {
            params.append('f', rison.encode(removeUndefinedValues(q.advanced_filters)));
        }
        if (q.page_number && q.page_number > 1) params.append('p', q.page_number.toString());
        if (q.page_size && q.page_size !== defaultPageSize(q.search_mode)) params.append('ps', q.page_size.toString());
        if (q.search_mode && q.search_mode !== 'accounts') params.append('sm', q.search_mode);
        if (q.tag_ids && q.tag_ids.length > 0) params.append('t', q.tag_ids.join(','));
        if (q.tag_ids && q.tag_ids.length > 1 && q.tag_filter_mode && q.tag_filter_mode !== 'any') params.append('tm', q.tag_filter_mode);
        // Only persist tag scopes when broadened beyond the default (the searched entity itself),
        // matching how `tm` is only written when non-default — keeps shareable URLs clean.
        if (q.tag_ids && q.tag_ids.length > 0 && q.tag_scopes && q.tag_scopes.length
            && !isDefaultScopes(q.tag_scopes, SEARCH_MODE_TO_ENTITY[q.search_mode])) {
            params.append('ts', q.tag_scopes.join(','));
        }
        if (q.sort_by) {
            params.append('sb', q.sort_by);
            if (q.sort_order) params.append('so', q.sort_order);
        }
        const newSearch = params.toString()
            .replaceAll('%28', '(').replaceAll('%29', ')').replaceAll('%27', "'")
            .replaceAll('%3A', ':').replaceAll('%3D', '=').replaceAll('%21', '!')
            .replaceAll('%2C', ',').replaceAll('%3C', '<').replaceAll('%3E', '>');
        if (newSearch !== searchParams.toString()) navigate({pathname: location.pathname, search: newSearch}, {replace: true});
    };

    const tagging: SearchPanelTagging | undefined = SEARCH_MODE_TO_ENTITY[query.search_mode] ? {
        isActive: taggingMode,
        onToggle: () => setTaggingMode(prev => {
            if (prev) { setSelectedIds(new Set()); setBulkTags([]); }
            return !prev;
        }),
        selectedIds,
        onToggleSelected: (id: number) => setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        }),
        bulkTags,
        onBulkTagsChange: setBulkTags,
        onApply: async () => {
            const entity = SEARCH_MODE_TO_ENTITY[query.search_mode]!;
            await batchAnnotate(entity, [...selectedIds], bulkTags.map(t => ({id: t.id})));
            const ids = results.map(r => r.id).filter((id): id is number => id != null);
            fetchTagsForSearchResults(query.search_mode, ids).then(setTagsMap);
            setBulkTags([]);
        },
        onClearSelection: () => { setSelectedIds(new Set()); setBulkTags([]); },
        entity: SEARCH_MODE_TO_ENTITY[query.search_mode]!,
    } : undefined;

    return (
        <div className="page-wrap">
            <TopNavBar>
                Search Archives
                {!isMobile && query.search_mode === 'media' && (
                    <Tooltip title={largeIcons ? 'Small icons' : 'Large icons'} arrow>
                        <IconButton color="inherit" onClick={toggleLargeIcons} sx={{ml: 'auto'}}>
                            {largeIcons ? <ViewComfyIcon/> : <GridViewIcon/>}
                        </IconButton>
                    </Tooltip>
                )}
            </TopNavBar>
            <div className="page-content content-wrap">
                <Stack gap={2} sx={{width: '100%'}}>
                    <SearchPanel
                        query={query}
                        onSearch={encodeQueryToParams}
                        results={results}
                        isLoading={isLoading}
                        tagsMap={tagsMap}
                        showModeSelector
                        showAdvancedFilters
                        showTaggingMode
                        searchHistory={{getSuggestions, addSearch, removeSearch}}
                        tagging={tagging}
                        largeIcons={largeIcons}
                    />
                    {/* Pagination (stays in SearchPage, outside SearchPanel) */}
                    <Stack direction="row" spacing={2} justifyContent="center" alignItems="center">
                        <Button variant="text" disabled={query.page_number <= 1}
                            onClick={() => encodeQueryToParams({...query, page_number: query.page_number - 1})}>
                            Previous
                        </Button>
                        <Box>Page {query.page_number}</Box>
                        <Button variant="text"
                            onClick={() => encodeQueryToParams({...query, page_number: query.page_number + 1})}>
                            Next
                        </Button>
                    </Stack>
                </Stack>
            </div>
        </div>
    );
}
