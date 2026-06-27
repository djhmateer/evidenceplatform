import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    Autocomplete,
    Box,
    Button,
    CircularProgress,
    Collapse,
    Divider,
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
import ImageSearchIcon from '@mui/icons-material/ImageSearch';
import UploadFileIcon from '@mui/icons-material/UploadFile';
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
    searchByImage,
    searchData,
    SearchResult,
    SORT_OPTIONS,
    sortKeyFromQuery,
    T_Search_Mode,
} from '../../services/DataFetcher';
import {ITagWithType} from '../../types/tags';
import {E_ENTITY_TYPES} from '../../types/entities';
import {resolveScopes} from '../../lib/tagScopes';
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
    // Desktop-only: render media results as large, auto-loading icons (SearchPage uses this)
    largeIcons?: boolean;
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
        largeIcons,
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
    // Cache of every tag object we've seen this session, keyed by id. The URL only carries
    // tag ids, so this lets us re-derive the selected-tag chips from query.tag_ids without
    // losing their display info (names/types) when the committed query changes.
    const tagObjectCache = useRef(new Map<number, ITagWithType>());
    const isDropdownOpen = useRef(false);
    // Set when a search shortcut applies/clears advanced_filters, so the queryKey effect below
    // skips its auto-open of the filters pane for that one update — shortcuts write the same
    // URL params a shared link would, but the user didn't ask to see the builder.
    const suppressFiltersAutoOpenRef = useRef(false);

    // ── Internal results state (auto-search mode only) ────────────────────────

    const [internalResults, setInternalResults] = useState<SearchResult[]>([]);
    const [internalIsLoading, setInternalIsLoading] = useState(false);
    const [internalTagsMap, setInternalTagsMap] = useState<Record<number, ITagWithType[]>>({});
    const abortRef = useRef<AbortController | null>(null);

    // ── Image-search state (mode === 'image') ─────────────────────────────────
    const isImageMode = query.search_mode === 'image';
    const [imageResults, setImageResults] = useState<SearchResult[]>([]);
    const [imageLoading, setImageLoading] = useState(false);
    const [imagePreview, setImagePreview] = useState<string | null>(null);
    const [imageError, setImageError] = useState<string | null>(null);
    const [dragActive, setDragActive] = useState(false);
    const imageReqRef = useRef(0);                       // ignore out-of-order responses
    const imagePreviewUrlRef = useRef<string | null>(null);  // revoke prior object URLs

    const runImageSearch = useCallback((file: File | Blob) => {
        if (imagePreviewUrlRef.current) URL.revokeObjectURL(imagePreviewUrlRef.current);
        const url = URL.createObjectURL(file);
        imagePreviewUrlRef.current = url;
        setImagePreview(url);
        setImageError(null);
        setImageLoading(true);
        const seq = ++imageReqRef.current;
        searchByImage(file, {pageSize: query.page_size})
            .then(r => {
                if (seq !== imageReqRef.current) return;
                setImageResults(r);
                setImageLoading(false);
            })
            .catch((e: any) => {
                if (seq !== imageReqRef.current) return;
                setImageError(e?.message || 'Image search failed');
                setImageResults([]);
                setImageLoading(false);
            });
    }, [query.page_size]);

    const handleImageFiles = useCallback((files: FileList | null) => {
        const f = files?.[0];
        if (f) runImageSearch(f);
    }, [runImageSearch]);

    // In image mode, Ctrl/Cmd+V searches the pasted image from anywhere on the page — no need to
    // focus a field first. (There is no text input in this mode, so a document-level listener is
    // safe.)
    useEffect(() => {
        if (!isImageMode) return;
        const onPaste = (e: ClipboardEvent) => {
            const item = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith('image/'));
            const f = item?.getAsFile();
            if (f) runImageSearch(f);
        };
        document.addEventListener('paste', onPaste);
        return () => document.removeEventListener('paste', onPaste);
    }, [isImageMode, runImageSearch]);

    useEffect(() => () => {
        if (imagePreviewUrlRef.current) URL.revokeObjectURL(imagePreviewUrlRef.current);
    }, []);

    const results = isImageMode ? imageResults : (isAutoSearch ? internalResults : props.results!);
    const isLoading = isImageMode ? imageLoading : (isAutoSearch ? internalIsLoading : props.isLoading!);
    const tagsMap = isAutoSearch && !isImageMode ? internalTagsMap : (props.tagsMap ?? {});

    // ── Sync when parent query changes (URL back/forward navigation) ──────────

    const queryKey = useMemo(
        () => `${query.search_term}||${query.search_mode}||${JSON.stringify(query.advanced_filters)}||${JSON.stringify(query.tag_ids)}||${JSON.stringify(query.tag_scopes)}`,
        [query.search_term, query.search_mode, query.advanced_filters, query.tag_ids, query.tag_scopes]
    );
    useEffect(() => {
        setTypedSearchTerm(query.search_term || '');
        setAdvancedFiltersTree(
            query.advanced_filters
                ? Utils.Import.loadFromJsonLogic(
                query.advanced_filters,
                {...InitialConfig, fields: ADVANCED_FILTERS_CONFIG[query.search_mode]}
            ) || getEmptyTree()
                : getEmptyTree()
        );
        // Re-derive the selected-tag chips from the committed query.tag_ids using cached
        // objects, instead of clearing them — so picking a tag (which updates the URL) keeps
        // the chips visible. Ids we've never seen this session (e.g. a shared URL) resolve to
        // nothing and are simply dropped, matching prior behaviour.
        const tagIds = query.tag_ids || [];
        setTagFilterObjects(
            tagIds
                .map(id => tagObjectCache.current.get(id))
                .filter((t): t is ITagWithType => !!t)
        );
        // Only ever open the panel here (e.g. when navigating to a URL that carries filters or
        // tags) — never force it closed, so a user-opened panel doesn't collapse on each search.
        // A shortcut-driven update suppresses this auto-open: read and clear the flag now so the
        // closure captures it synchronously, before the deferred state updater runs.
        const suppressAutoOpen = suppressFiltersAutoOpenRef.current;
        suppressFiltersAutoOpenRef.current = false;
        setShowFiltersPanel(prev =>
            suppressAutoOpen ? prev : prev || !!query.advanced_filters || tagIds.length > 0
        );
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
        if (!isAutoSearch || query.search_mode === 'image') return;
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
        // Image search has no text term / filters — switching to it just commits the mode.
        const filters = currentMode === 'image' ? null : (Utils.Export.jsonLogicFormat(advancedFiltersTree, {
            ...InitialConfig,
            fields: ADVANCED_FILTERS_CONFIG[currentMode],
        }).logic ?? null);
        const newQuery: ISearchQuery = {
            ...query,
            search_term: typedSearchTerm,
            advanced_filters: filters,
            page_number: 1,
            ...overrides,
        };
        if (isAutoSearch && currentMode !== 'image') {
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
        suppressFiltersAutoOpenRef.current = true;
        performSearch({advanced_filters: newLogic});
    };

    // ── Render helpers ────────────────────────────────────────────────────────

    const SearchShortcuts = SEARCH_SHORTCUTS[query.search_mode];
    const ResultsComponent = SEARCH_RESULT_RENDERERS[query.search_mode] ?? DefaultSearchResults;

    const modeSelector = showModeSelector ? (
        <Select
            variant="standard"
            disableUnderline
            value={query.search_mode}
            onChange={e => {
                const newMode = e.target.value as T_Search_Mode;
                setAdvancedFiltersTree(getEmptyTree());
                performSearch({search_mode: newMode, advanced_filters: null, page_size: defaultPageSize(newMode), sort_by: null, sort_order: null});
            }}
            sx={{
                flexShrink: 0,
                minWidth: 128,
                '& .MuiSelect-select': {
                    py: 1,
                    pl: 1.5,
                    pr: '28px !important',
                    fontWeight: 600,
                    fontSize: '0.9rem',
                },
            }}
        >
            {SEARCH_MODES.map(m => (
                <MenuItem key={m.key} value={m.key}>{m.label}</MenuItem>
            ))}
        </Select>
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

    const submitSearch = () => {
        searchHistory?.addSearch(query.search_mode, typedSearchTerm);
        performSearch();
    };

    const syntaxHelpButton = (
        <Tooltip title="Boolean search syntax" arrow disableInteractive>
            <IconButton
                size="small"
                href="https://dev.mysql.com/doc/refman/8.4/en/fulltext-boolean.html"
                target="_blank"
                rel="noopener"
                aria-label="Boolean search syntax help"
                sx={{color: 'text.disabled'}}
            >
                <QuestionMarkIcon sx={{fontSize: '1rem'}}/>
            </IconButton>
        </Tooltip>
    );

    // Submit affordance lives inside the input's trailing edge: a compact icon on mobile,
    // a labelled primary action (with the syntax helper alongside) on desktop.
    const searchEndAdornment = isMobile ? (
        <IconButton color="primary" onClick={submitSearch} aria-label="Search" sx={{p: '4px'}}>
            <SearchIcon/>
        </IconButton>
    ) : (
        <Stack direction="row" alignItems="center" gap={0.5} sx={{pl: 0.5}}>
            {syntaxHelpButton}
            <Button
                variant="contained"
                disableElevation
                startIcon={<SearchIcon/>}
                onClick={submitSearch}
                sx={{textTransform: 'none', borderRadius: 1.5, boxShadow: 'none', flexShrink: 0, px: 2}}
            >
                Search
            </Button>
        </Stack>
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
            sx={{flex: 1, minWidth: 0}}
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
                    placeholder="Search…"
                    size="small"
                    fullWidth
                    sx={{'& .MuiOutlinedInput-notchedOutline': {border: 'none'}}}
                    endAdornment={searchEndAdornment}
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
            placeholder="Search…"
            size="small"
            fullWidth
            sx={{flex: 1, minWidth: 0, '& .MuiOutlinedInput-notchedOutline': {border: 'none'}}}
            endAdornment={searchEndAdornment}
        />
    );

    // Image-search affordance. The drop zone never opens the file dialog on click — that would steal
    // focus and block pasting. The dialog opens only from the explicit Upload button (a MUI
    // `Button component="label"`); paste works anywhere (document listener above); drag-drop lands on
    // the zone, which highlights while a file hovers.
    const imageSearchInput = (
        <Box
            onDragOver={(e: React.DragEvent) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e: React.DragEvent) => {
                e.preventDefault();
                setDragActive(false);
                handleImageFiles(e.dataTransfer.files);
            }}
            sx={{
                flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 1,
                pl: 1.5, pr: 0.5, py: 0.5, borderRadius: 1.5,
                bgcolor: dragActive ? 'action.hover' : 'transparent',
                transition: 'background-color .15s ease',
            }}
        >
            <ImageSearchIcon fontSize="small" sx={{color: 'text.secondary', flexShrink: 0}}/>
            <Typography variant="body2" color="text.secondary" noWrap sx={{flex: 1, minWidth: 0}}>
                {dragActive
                    ? 'Drop to search'
                    : (isMobile ? 'Search by image' : 'Drop or paste an image to search')}
            </Typography>
            <Button
                component="label"
                size="small"
                variant="outlined"
                startIcon={<UploadFileIcon/>}
                sx={{flexShrink: 0, textTransform: 'none', borderRadius: 1.5}}
            >
                Upload
                <input type="file" accept="image/*" hidden
                       onChange={e => { handleImageFiles(e.target.files); e.target.value = ''; }}/>
            </Button>
        </Box>
    );

    // The mode selector, query field, and submit action read as one control: a single
    // bordered pill that lights up on focus. The mode selector leads (scope first), the
    // query fills the middle, the submit action caps the trailing edge. In image-search mode the
    // query field is replaced by the upload affordance.
    const searchBar = (
        <Box
            sx={{
                display: 'flex',
                alignItems: 'center',
                flex: 1,
                minWidth: 0,
                pr: 0.5,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 2,
                bgcolor: 'background.paper',
                transition: 'border-color .15s ease, box-shadow .15s ease',
                '&:focus-within': {
                    borderColor: 'primary.main',
                    boxShadow: theme => `0 0 0 1px ${theme.palette.primary.main}`,
                },
            }}
        >
            {!isMobile && modeSelector && (
                <>
                    {modeSelector}
                    <Divider orientation="vertical" flexItem sx={{my: 1}}/>
                </>
            )}
            {isImageMode ? imageSearchInput : searchBarInput}
        </Box>
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
                    <Stack direction="row" spacing={1.5} alignItems="center" sx={{width: '100%', minWidth: 0}}>
                        {searchBar}
                        {showAdvancedFiltersFeature && !isMobile && !isImageMode && (
                            <Tooltip title="Advanced filtering" arrow disableInteractive>
                                <ToggleButton
                                    value="check"
                                    selected={showFiltersPanel}
                                    color="primary" sx={{borderRadius: 2, p: '8px'}}
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
                            {showAdvancedFiltersFeature && !isImageMode && (
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

                {/* Image-search preview + match summary */}
                {isImageMode && (imagePreview || imageError) && (
                    <Stack direction="row" spacing={1.5} alignItems="center"
                           sx={{px: isMobile ? '1em' : 0}}>
                        {imagePreview && (
                            <Box component="img" src={imagePreview} alt="query"
                                 sx={{width: 56, height: 56, objectFit: 'cover', borderRadius: 1,
                                      border: '1px solid', borderColor: 'divider', flexShrink: 0}}/>
                        )}
                        <Typography variant="body2" color={imageError ? 'error' : 'text.secondary'}>
                            {imageError
                                ? imageError
                                : isLoading
                                    ? 'Searching…'
                                    : results.length === 0
                                        ? 'No matches found'
                                        : `${results.length} match${results.length === 1 ? '' : 'es'}, best first`}
                        </Typography>
                    </Stack>
                )}

                {/* Tag filter — always visible directly under the search bar */}
                {query.search_mode !== 'archive_sessions' && !isImageMode && (
                    <Box sx={{margin: isMobile ? '0 1em' : 0}}>
                        <TagFilterBar
                            tagIds={query.tag_ids || []}
                            tagFilterMode={query.tag_filter_mode || 'any'}
                            selectedTagObjects={tagFilterObjects}
                            tagScopes={resolveScopes(query.tag_scopes, SEARCH_MODE_TO_ENTITY[query.search_mode])}
                            entity={SEARCH_MODE_TO_ENTITY[query.search_mode]}
                            onChange={(tagIds, mode, tagObjects, scopes) => {
                                tagObjects.forEach(t => tagObjectCache.current.set(t.id, t));
                                setTagFilterObjects(tagObjects);
                                performSearch({tag_ids: tagIds, tag_filter_mode: mode, tag_scopes: scopes});
                            }}
                        />
                    </Box>
                )}

                {/* Advanced filters */}
                {showAdvancedFiltersFeature && !isImageMode && (
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
                {!isImageMode && (SearchShortcuts || sortSelector || (showTaggingMode && SEARCH_MODE_TO_ENTITY[query.search_mode])) && (
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
                            largeIcons={largeIcons}
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
