import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    Autocomplete,
    Box,
    Button,
    CircularProgress,
    Collapse,
    Divider,
    Fab,
    FormControl,
    IconButton,
    MenuItem,
    OutlinedInput,
    Paper,
    Select,
    Stack,
    ToggleButton,
    Tooltip,
    Typography,
    useMediaQuery,
} from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import SearchIcon from '@mui/icons-material/Search';
import LocalOfferIcon from '@mui/icons-material/LocalOffer';
import QuestionMarkIcon from '@mui/icons-material/QuestionMark';
import HistoryIcon from '@mui/icons-material/History';
import CloseIcon from '@mui/icons-material/Close';
import {
    Builder,
    BuilderProps,
    ImmutableTree,
    JsonLogicFunction,
    MuiConfig,
    Query,
    Utils,
} from '@react-awesome-query-builder/mui';
import '@react-awesome-query-builder/mui/css/styles.css';
import {
    ADVANCED_FILTERS_CONFIG,
    defaultPageSize,
    fetchTagsForSearchResults,
    ISearchQuery,
    SEARCH_MODE_TO_ENTITY,
    SEARCH_MODES,
    searchData,
    SearchResult,
    SORT_OPTIONS,
    sortKeyFromQuery,
    T_Search_Mode,
} from '../../services/DataFetcher';
import {ITagWithType} from '../../types/tags';
import {E_ENTITY_TYPES} from '../../types/entities';
import TagFilterBar from '../Tags/TagFilterBar';
import TagSelector from '../Tags/TagSelector';
import {SEARCH_SHORTCUTS} from '../SearchShortcuts';
import {DefaultSearchResults, SEARCH_RESULT_RENDERERS} from '../SearchResults';

const InitialConfig = MuiConfig;

const getEmptyTree = (): ImmutableTree =>
    Utils.loadTree({id: Utils.uuid(), type: 'group', children1: []});

export interface SearchPanelSearchHistory {
    getSuggestions: (mode: T_Search_Mode, term: string) => string[];
    addSearch: (mode: T_Search_Mode, term: string) => void;
    removeSearch: (mode: T_Search_Mode, term: string) => void;
}

export interface SearchPanelTagging {
    isActive: boolean;
    onToggle: () => void;
    selectedIds: Set<number>;
    onToggleSelected: (id: number) => void;
    bulkTags: ITagWithType[];
    onBulkTagsChange: (tags: ITagWithType[]) => void;
    onApply: () => void;
    onClearSelection: () => void;
    entity: E_ENTITY_TYPES;
}

interface BaseProps {
    // Committed query (SearchPage passes this from URL; community page passes a fixed initial)
    query: ISearchQuery;
    // Called when user submits a search (SearchPage uses to update URL)
    onSearch: (q: ISearchQuery) => void;
    // Feature flags
    showModeSelector?: boolean;
    showAdvancedFilters?: boolean;
    showTaggingMode?: boolean;
    // Optional search history for autocomplete suggestions
    searchHistory?: SearchPanelSearchHistory;
    // Optional tagging mode (SearchPage uses this)
    tagging?: SearchPanelTagging;
    // Override result click (community page uses to add to kernel instead of navigating)
    onResultClick?: (result: SearchResult) => void;
    // Checked entries shown via checkboxes independent of tagging mode (community page uses for kernel membership)
    checkedIds?: Set<number>;
    onToggleChecked?: (result: SearchResult) => void;
}

// When autoSearch is set, the panel fetches results internally on each keystroke (debounced).
// When autoSearch is not set, the parent provides results and isLoading.
export type SearchPanelProps = BaseProps & (
    | { autoSearch: number; results?: never; isLoading?: never; tagsMap?: never }
    | { autoSearch?: never; results: SearchResult[]; isLoading: boolean; tagsMap?: Record<number, ITagWithType[]> }
    );

export default function SearchPanel(props: SearchPanelProps) {
    const {
        query, onSearch,
        showModeSelector = true,
        showAdvancedFilters: showAdvancedFiltersFeature = true,
        showTaggingMode = false,
        searchHistory, tagging, onResultClick,
        checkedIds, onToggleChecked,
    } = props;

    const isAutoSearch = props.autoSearch !== undefined;
    const isMobile = useMediaQuery('(max-width: 768px)');

    // ── Internal UI state ─────────────────────────────────────────────────────

    const [typedSearchTerm, setTypedSearchTerm] = useState(query.search_term || '');
    const [advancedFiltersTree, setAdvancedFiltersTree] = useState<ImmutableTree>(() =>
        query.advanced_filters
            ? Utils.Import.loadFromJsonLogic(
            query.advanced_filters,
            {...InitialConfig, fields: ADVANCED_FILTERS_CONFIG[query.search_mode]}
        ) || getEmptyTree()
            : getEmptyTree()
    );
    const [showFiltersPanel, setShowFiltersPanel] = useState(!!query.advanced_filters);
    const [tagFilterObjects, setTagFilterObjects] = useState<ITagWithType[]>([]);
    const isDropdownOpen = useRef(false);

    // ── Internal results state (auto-search mode only) ────────────────────────

    const [internalResults, setInternalResults] = useState<SearchResult[]>([]);
    const [internalIsLoading, setInternalIsLoading] = useState(false);
    const [internalTagsMap, setInternalTagsMap] = useState<Record<number, ITagWithType[]>>({});
    const abortRef = useRef<AbortController | null>(null);

    const results = isAutoSearch ? internalResults : props.results!;
    const isLoading = isAutoSearch ? internalIsLoading : props.isLoading!;
    const tagsMap = isAutoSearch ? internalTagsMap : (props.tagsMap ?? {});

    // ── Sync when parent query changes (URL back/forward navigation) ──────────

    const queryKey = useMemo(
        () => `${query.search_term}||${query.search_mode}||${JSON.stringify(query.advanced_filters)}||${JSON.stringify(query.tag_ids)}`,
        [query.search_term, query.search_mode, query.advanced_filters, query.tag_ids]
    );
    useEffect(() => {
        setTypedSearchTerm(query.search_term || '');
        setTagFilterObjects([]);
        setAdvancedFiltersTree(
            query.advanced_filters
                ? Utils.Import.loadFromJsonLogic(
                query.advanced_filters,
                {...InitialConfig, fields: ADVANCED_FILTERS_CONFIG[query.search_mode]}
            ) || getEmptyTree()
                : getEmptyTree()
        );
        setShowFiltersPanel(!!query.advanced_filters);
    }, [queryKey]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── Cleanup on unmount ────────────────────────────────────────────────────

    useEffect(() => () => {
        abortRef.current?.abort();
    }, []);

    // ── Auto-search fetch (auto-search mode) ──────────────────────────────────

    const doSearch = useCallback((searchQuery: ISearchQuery) => {
        abortRef.current?.abort();
        const ctrl = new AbortController();
        abortRef.current = ctrl;
        setInternalIsLoading(true);
        setInternalTagsMap({});
        searchData(searchQuery, {signal: ctrl.signal}).then(r => {
            setInternalResults(r);
            setInternalIsLoading(false);
            onSearch(searchQuery);
            const ids = r.map(x => x.id).filter((id): id is number => id != null);
            if (ids.length > 0) {
                fetchTagsForSearchResults(searchQuery.search_mode, ids).then(setInternalTagsMap);
            }
        }).catch((e: any) => {
            if (e.name !== 'AbortError') setInternalIsLoading(false);
        });
    }, [onSearch]);

    // Ref keeps doSearch stable in the effect below without requiring it as a dep
    // (onSearch may be an unstable inline function at the call site)
    const doSearchRef = useRef(doSearch);
    doSearchRef.current = doSearch;

    useEffect(() => {
        if (!isAutoSearch) return;
        if (!typedSearchTerm.trim()) {
            setInternalResults([]);
            return;
        }
        const t = setTimeout(() => {
            doSearchRef.current({...query, search_term: typedSearchTerm, page_number: 1});
        }, props.autoSearch as number);
        return () => clearTimeout(t);
    }, [typedSearchTerm, isAutoSearch, query, props.autoSearch]);

    // ── Checked entries toggle (kernel membership in community page) ──────────

    const handleToggleChecked = useCallback((id: number) => {
        if (!onToggleChecked) return;
        const result = results.find(r => r.id === id);
        if (result) onToggleChecked(result);
    }, [onToggleChecked, results]);

    // ── performSearch: build full query and hand off ──────────────────────────

    const performSearch = useCallback((overrides?: Partial<ISearchQuery>) => {
        const currentMode = overrides?.search_mode ?? query.search_mode;
        const filters = Utils.Export.jsonLogicFormat(advancedFiltersTree, {
            ...InitialConfig,
            fields: ADVANCED_FILTERS_CONFIG[currentMode],
        }).logic ?? null;
        const newQuery: ISearchQuery = {
            ...query,
            search_term: typedSearchTerm,
            advanced_filters: filters,
            page_number: 1,
            ...overrides,
        };
        if (isAutoSearch) {
            doSearch(newQuery);
        } else {
            onSearch(newQuery);
        }
    }, [query, typedSearchTerm, advancedFiltersTree, isAutoSearch, doSearch, onSearch]);

    const onShortcutChange = (newLogic: JsonLogicFunction | null) => {
        const modeConfig = {...InitialConfig, fields: ADVANCED_FILTERS_CONFIG[query.search_mode]};
        const newTree = newLogic
            ? Utils.Import.loadFromJsonLogic(newLogic, modeConfig) || getEmptyTree()
            : getEmptyTree();
        setAdvancedFiltersTree(newTree);
        performSearch({advanced_filters: newLogic});
    };

    // ── Render helpers ────────────────────────────────────────────────────────

    const SearchShortcuts = SEARCH_SHORTCUTS[query.search_mode];
    const ResultsComponent = SEARCH_RESULT_RENDERERS[query.search_mode] ?? DefaultSearchResults;

    const modeSelector = showModeSelector ? (
        <FormControl variant="standard" sx={{width: '200px'}}>
            <Select
                value={query.search_mode}
                onChange={e => {
                    const newMode = e.target.value as T_Search_Mode;
                    setAdvancedFiltersTree(getEmptyTree());
                    performSearch({search_mode: newMode, advanced_filters: null, page_size: defaultPageSize(newMode), sort_by: null, sort_order: null});
                }}
                sx={{
                    width: '100%',
                    '& .MuiSelect-select': {paddingLeft: '8px'},
                    '::before': {borderBottom: 'none !important'},
                }}
            >
                {SEARCH_MODES.map(m => (
                    <MenuItem key={m.key} value={m.key}>{m.label}</MenuItem>
                ))}
            </Select>
        </FormControl>
    ) : null;

    const sortOptions = SORT_OPTIONS[query.search_mode];
    const sortSelector = sortOptions ? (
        <FormControl variant="standard" sx={{minWidth: 160}}>
            <Select
                value={sortKeyFromQuery(query)}
                onChange={e => {
                    const opt = sortOptions.find(o => o.key === e.target.value);
                    if (opt) performSearch({sort_by: opt.sort_by, sort_order: opt.sort_order});
                }}
                sx={{
                    '& .MuiSelect-select': {paddingLeft: '8px'},
                    '::before': {borderBottom: 'none !important'},
                }}
            >
                {sortOptions.map(o => (
                    <MenuItem key={o.key} value={o.key}>{o.label}</MenuItem>
                ))}
            </Select>
        </FormControl>
    ) : null;

    const renderAdvancedFiltersBuilder = (builderProps: BuilderProps) => (
        <Box className="query-builder-container" style={{padding: '10px 0'}}>
            <Box className="query-builder"><Builder {...builderProps}/></Box>
        </Box>
    );

    const searchBarInput = searchHistory ? (
        <Autocomplete
            freeSolo
            autoHighlight={false}
            options={searchHistory.getSuggestions(query.search_mode, typedSearchTerm)}
            inputValue={typedSearchTerm}
            onInputChange={(_, value, reason) => {
                if (reason !== 'reset') setTypedSearchTerm(value);
            }}
            onChange={(_, value) => {
                if (typeof value === 'string' && value) {
                    searchHistory.addSearch(query.search_mode, value);
                    performSearch({search_term: value});
                }
            }}
            onOpen={() => {
                isDropdownOpen.current = true;
            }}
            onClose={() => {
                isDropdownOpen.current = false;
            }}
            filterOptions={x => x}
            renderOption={(optProps, option) => (
                <Box component="li" {...optProps} sx={{display: 'flex', alignItems: 'center', gap: 1, pr: 0.5}}>
                    <Box sx={{
                        flex: 1,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }}>{option}</Box>
                    <HistoryIcon fontSize="small" sx={{color: 'text.disabled', flexShrink: 0}}/>
                    <Tooltip title="Remove from Search History" arrow disableInteractive>
                        <IconButton size="small"
                                    onClick={e => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        searchHistory.removeSearch(query.search_mode, option);
                                    }}
                                    sx={{flexShrink: 0, p: 0.25}}>
                            <CloseIcon sx={{fontSize: '0.9rem'}}/>
                        </IconButton>
                    </Tooltip>
                </Box>
            )}
            sx={{flex: 1}}
            renderInput={params => (
                <OutlinedInput
                    {...params.InputProps}
                    inputProps={params.inputProps}
                    onKeyDown={e => {
                        if (e.key === 'Enter' && (!isDropdownOpen.current || typedSearchTerm === '')) {
                            searchHistory.addSearch(query.search_mode, typedSearchTerm);
                            performSearch();
                        }
                    }}
                    placeholder="Search..."
                    sx={{width: '100%', '& .MuiOutlinedInput-input': {width: isMobile ? '100%' : 'calc(100% - 200px)'}}}
                    size="small"
                    endAdornment={
                        isMobile ? (
                            <IconButton color="primary" sx={{padding: '4px'}} onClick={() => {
                                searchHistory?.addSearch(query.search_mode, typedSearchTerm);
                                performSearch();
                            }}>
                                <SearchIcon/>
                            </IconButton>
                        ) : (
                            <Stack direction="row" gap={2} alignItems="center">
                                <Tooltip title="Boolean Search Syntax Explainer" arrow disableInteractive>
                                    <Fab color="info"
                                         href="https://dev.mysql.com/doc/refman/8.4/en/fulltext-boolean.html"
                                         size="small" target="_blank"
                                         sx={{width: 24, height: 24, minHeight: 24}}>
                                        <QuestionMarkIcon fontSize="small" sx={{fontSize: '1em'}}/>
                                    </Fab>
                                </Tooltip>
                                {modeSelector}
                            </Stack>
                        )
                    }
                />
            )}
        />
    ) : (
        <OutlinedInput
            value={typedSearchTerm}
            onChange={e => setTypedSearchTerm(e.target.value)}
            onKeyDown={e => {
                if (e.key === 'Enter') performSearch();
            }}
            placeholder="Search..."
            size="small"
            sx={{flex: 1}}
            endAdornment={
                isMobile ? (
                    <IconButton color="primary" sx={{padding: '4px'}} onClick={() => performSearch()}>
                        <SearchIcon/>
                    </IconButton>
                ) : (modeSelector || undefined)
            }
        />
    );

    return (
        <>
            <Stack
                gap={isMobile ? 0 : 2}
                sx={{width: '100%'}}
                divider={<Divider orientation="horizontal" flexItem/>}
            >
                {/* Search bar */}
                <Stack direction="column" gap={isMobile ? 0 : 1}>
                    <Stack direction="row" spacing={2} sx={{width: '100%', minWidth: 0}}>
                        {searchBarInput}
                        {!isMobile && (
                            <Tooltip title="Search" arrow disableInteractive>
                                <IconButton color="primary" sx={{padding: '8px'}} onClick={() => {
                                    searchHistory?.addSearch(query.search_mode, typedSearchTerm);
                                    performSearch();
                                }}>
                                    <SearchIcon/>
                                </IconButton>
                            </Tooltip>
                        )}
                        {showAdvancedFiltersFeature && !isMobile && (
                            <Tooltip title="Advanced Filtering" arrow disableInteractive>
                                <ToggleButton
                                    value="check"
                                    selected={showFiltersPanel}
                                    color="primary" sx={{padding: '8px'}}
                                    onClick={() => setShowFiltersPanel(p => !p)}
                                >
                                    <FilterListIcon/>
                                </ToggleButton>
                            </Tooltip>
                        )}
                    </Stack>
                    {isMobile && (
                        <Stack
                            direction="row"
                            justifyContent="space-between"
                            alignItems="center"
                            sx={{padding: isMobile ? '1em' : '0'}}
                        >
                            {modeSelector}
                            {showAdvancedFiltersFeature && (
                                <Tooltip title="Advanced Filtering" arrow disableInteractive>
                                    <ToggleButton
                                        value="check"
                                        selected={showFiltersPanel}
                                        color="primary" sx={{padding: '8px'}}
                                        onClick={() => setShowFiltersPanel(p => !p)}
                                    >
                                        <FilterListIcon/>
                                    </ToggleButton>
                                </Tooltip>
                            )}
                        </Stack>
                    )}
                </Stack>

                {/* Advanced filters */}
                {showAdvancedFiltersFeature && (
                    <Collapse in={showFiltersPanel} timeout="auto" unmountOnExit>
                        <Stack
                            direction="column"
                            gap={1}
                            sx={{
                                width: '100%',
                                marginTop: isMobile ? '1em' : 0,
                            }}
                        >
                            <Box onKeyDown={(e: React.KeyboardEvent) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    performSearch();
                                }
                            }}>
                                {query.search_mode !== 'archive_sessions' && (
                                    <Box sx={{margin: isMobile ? '0 1em' : 0}}>
                                        <TagFilterBar
                                            tagIds={query.tag_ids || []}
                                            tagFilterMode={query.tag_filter_mode || 'any'}
                                            selectedTagObjects={tagFilterObjects}
                                            entity={SEARCH_MODE_TO_ENTITY[query.search_mode]}
                                            onChange={(tagIds, mode, tagObjects) => {
                                                setTagFilterObjects(tagObjects);
                                                performSearch({tag_ids: tagIds, tag_filter_mode: mode});
                                            }}
                                        />
                                    </Box>
                                )}
                                <Box sx={{
                                    '& .qb-lite': {
                                        '& .group--drag-handler, & .group--actions': {
                                            opacity: '1 !important',
                                            visibility: 'visible !important'
                                        },
                                        '& .group--header:not(:hover), & .rule_group:not(:hover), & .group--field--count--rule:not(:hover)': {
                                            '& .group--drag-handler, & .group--actions': {opacity: '1 !important'},
                                        },
                                    },
                                }}>
                                    <Query
                                        {...InitialConfig}
                                        fields={ADVANCED_FILTERS_CONFIG[query.search_mode]}
                                        value={advancedFiltersTree}
                                        onChange={setAdvancedFiltersTree}
                                        renderBuilder={renderAdvancedFiltersBuilder}
                                    />
                                </Box>
                            </Box>
                            <Button variant="contained" onClick={() => performSearch()}>Apply Filters</Button>
                        </Stack>
                    </Collapse>
                )}

                {/* Shortcuts + Sort By + Tag Mode toggle */}
                {(SearchShortcuts || sortSelector || (showTaggingMode && SEARCH_MODE_TO_ENTITY[query.search_mode])) && (
                    <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        sx={{padding: isMobile ? '1em' : '0'}}
                    >
                        {SearchShortcuts
                            ? <SearchShortcuts tree={advancedFiltersTree} onChange={onShortcutChange}/>
                            : <Box/>}
                        <Stack direction="row" alignItems="center" gap={2} sx={{flexShrink: 0, ml: 2}}>
                            {sortSelector}
                            {!isMobile && showTaggingMode && tagging && SEARCH_MODE_TO_ENTITY[query.search_mode] && (
                                <Button
                                    size="small"
                                    variant={tagging.isActive ? 'contained' : 'outlined'}
                                    startIcon={<LocalOfferIcon fontSize="small"/>}
                                    onClick={tagging.onToggle}
                                    sx={{flexShrink: 0}}
                                >
                                    Tag Mode
                                </Button>
                            )}
                        </Stack>
                    </Stack>
                )}

                {/* Results */}
                <Box sx={{minHeight: 200, marginTop: isMobile ? "1em" : 0}}>
                    {isLoading ? (
                        <Box sx={{display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200}}>
                            <CircularProgress/>
                        </Box>
                    ) : (
                        <ResultsComponent
                            results={results}
                            tagsMap={tagsMap}
                            selectedIds={tagging?.isActive ? tagging.selectedIds : checkedIds}
                            onToggleSelected={
                                tagging?.isActive ? tagging.onToggleSelected
                                    : (checkedIds ? handleToggleChecked : undefined)
                            }
                            onPrimaryClick={onResultClick}
                        />
                    )}
                </Box>
            </Stack>

            {/* Tagging toolbar (fixed bottom, only in tagging mode) */}
            {tagging?.isActive && (
                <Paper elevation={6} sx={{
                    position: 'fixed', bottom: 0, left: 0, right: 0,
                    p: 2, zIndex: 1300,
                    display: 'flex', alignItems: 'center', gap: 2,
                    borderTop: '1px solid', borderColor: 'divider',
                }}>
                    <Typography sx={{whiteSpace: 'nowrap'}}>{tagging.selectedIds.size} selected</Typography>
                    <Box sx={{flex: 1, minWidth: 0}}>
                        <TagSelector selectedTags={tagging.bulkTags} onChange={tagging.onBulkTagsChange}
                                     entity={tagging.entity}/>
                    </Box>
                    <Button variant="contained"
                            disabled={tagging.bulkTags.length === 0 || tagging.selectedIds.size === 0}
                            onClick={tagging.onApply}>
                        Add Tags
                    </Button>
                    <Button onClick={tagging.onClearSelection}>Clear Selection</Button>
                </Paper>
            )}
        </>
    );
}
