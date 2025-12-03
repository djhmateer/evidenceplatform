import React from 'react';
import withRouter, {IRouterProps} from "../services/withRouter";
import {
    Box,
    Button,
    Card,
    CardMedia,
    CircularProgress,
    Collapse,
    Divider,
    Fab,
    FormControl,
    IconButton,
    MenuItem,
    OutlinedInput,
    Select,
    Stack,
    Tooltip,
    Typography
} from "@mui/material";
import SearchIcon from '@mui/icons-material/Search';
import QuestionMarkIcon from '@mui/icons-material/QuestionMark';
import FilterListIcon from '@mui/icons-material/FilterList';
import {
    ADVANCED_FILTERS_CONFIG,
    ISearchQuery,
    SEARCH_MODES,
    searchData,
    SearchResult,
    T_Search_Mode
} from "../services/DataFetcher";
import TopNavBar from "../UIComponents/TopNavBar/TopNavBar";
import {
    Builder,
    BuilderProps,
    ImmutableTree,
    JsonLogicFunction,
    MuiConfig,
    Query,
    Utils as QbUtils,
    Utils
} from '@react-awesome-query-builder/mui'; // for TS example
import '@react-awesome-query-builder/mui/css/styles.css';
import rison from "rison";
import {removeUndefinedValues} from "../services/utils";
import {anchor_local_static_files} from "../services/server";

const InitialConfig = MuiConfig;

type IProps = {} & IRouterProps;


interface IState {
    typedSearchTerm?: string;
    query: ISearchQuery;
    queryPromise: AbortController | null;
    showAdvancedFilters: boolean;
    results: SearchResult[];
    advancedFiltersTree: ImmutableTree;
}

const getEmptyTree = (search_mode: T_Search_Mode): ImmutableTree => {
    return QbUtils.loadTree({
        id: QbUtils.uuid(),
        type: "group",
        children1: [
            {
                type: "rule",
                id: QbUtils.uuid(),
                properties: {
                    fieldSrc: "field",
                    field: Object.keys(ADVANCED_FILTERS_CONFIG[search_mode])?.[0],
                    operator: null,
                    value: [""],
                    valueSrc: ["value"]
                }
            }
        ]
    })
}

class SearchPage extends React.Component<IProps, IState> {
    constructor(props: IProps) {
        super(props);
        const query = this.extractQueryFromParams();
        this.state = {
            showAdvancedFilters: !!query.advanced_filters,
            query,
            typedSearchTerm: query.search_term || "",
            advancedFiltersTree: query.advanced_filters ?
                Utils.Import.loadFromJsonLogic(
                    query.advanced_filters,
                    {
                        ...InitialConfig,
                        fields: ADVANCED_FILTERS_CONFIG[query.search_mode as T_Search_Mode]
                    }
                ) || getEmptyTree(query.search_mode) : getEmptyTree(query.search_mode),
            results: [],
            queryPromise: null,
        };
    }

    async componentDidMount() {
        this.props.setPageTitle(`Search`);
        await Promise.all([
            this.fetchData(),
        ])
    }

    componentDidUpdate(prevProps: IProps) {
        const newQuery = this.extractQueryFromParams();
        const prevQuery = this.extractQueryFromParams(prevProps.searchParams);
        if (
            JSON.stringify(newQuery) !== JSON.stringify(prevQuery)
        ) {
            this.setState((curr) => ({
                ...curr,
                query: newQuery,
                typedSearchTerm: newQuery.search_term,
                advancedFiltersTree: newQuery.advanced_filters ?
                    Utils.Import.loadFromJsonLogic(
                        newQuery.advanced_filters,
                        {
                            ...InitialConfig,
                            fields: ADVANCED_FILTERS_CONFIG[newQuery.search_mode as T_Search_Mode]
                        }
                    ) || getEmptyTree(newQuery.search_mode) : getEmptyTree(newQuery.search_mode)
            }), async () => {
                await this.fetchData();
            })
        }
    }

    encodeQueryToParams = (query: ISearchQuery) => {
        const params = new URLSearchParams();
        if (query.search_term) {
            params.append("s", query.search_term);
        }
        const defaultFilters = QbUtils.Export.jsonLogicFormat(getEmptyTree(query.search_mode), {
            ...InitialConfig,
            fields: ADVANCED_FILTERS_CONFIG[query.search_mode]
        }).logic;
        const currentFilters = query.advanced_filters || null;
        if (
            currentFilters &&
            JSON.stringify(currentFilters) !== JSON.stringify(defaultFilters)
        ) {
            params.append("f", rison.encode(removeUndefinedValues(currentFilters)));
        }
        if (query.page_number && query.page_number > 1) {
            params.append("p", query.page_number.toString());
        }
        if (query.page_size && query.page_size !== 20) {
            params.append("ps", query.page_size.toString());
        }
        if (query.search_mode && query.search_mode !== "accounts") {
            params.append("sm", query.search_mode);
        }
        this.props.navigate({
            pathname: this.props.location.pathname,
            search: params.toString()
                .replaceAll("%28", "(")
                .replaceAll("%29", ")")
                .replaceAll("%27", "'")
                .replaceAll("%3A", ":")
                .replaceAll("%3D", "=")
                .replaceAll("%21", "!")
                .replaceAll("%2C", ",")
                .replaceAll("%3C", "<")
                .replaceAll("%3E", ">")
        }, {replace: true});
    }

    extractQueryFromParams = (searchParams?: URLSearchParams): ISearchQuery => {
        searchParams = searchParams || this.props.searchParams;
        const search_term = searchParams.get("s") || ""
        let search_mode = searchParams.get("sm") || "accounts";
        if (!SEARCH_MODES.map(m => m.key).includes(search_mode)) {
            search_mode = "accounts";
        }
        const advanced_filters_rison = searchParams.get("f") || null;
        let advanced_filters: JsonLogicFunction | null = null;
        if (advanced_filters_rison) {
            try {
                advanced_filters = rison.decode(advanced_filters_rison);
            } catch (e) {
                advanced_filters = null;
            }
        }
        let page_number = parseInt(searchParams.get("p") || "1");
        page_number = isNaN(page_number) || page_number < 1 ? 1 : page_number;
        let page_size = parseInt(searchParams.get("ps") || "20");
        page_size = isNaN(page_size) || page_size < 20 ? 20 : page_size;
        return {
            search_term,
            advanced_filters,
            page_number,
            page_size,
            search_mode: search_mode as T_Search_Mode,
        }
    }

    performSearch = () => {
        this.setState((curr) => ({
                ...curr,
                query: {
                    ...curr.query,
                    search_term: curr.typedSearchTerm || "",
                    advanced_filters: QbUtils.Export.jsonLogicFormat(this.state.advancedFiltersTree, {
                        ...InitialConfig,
                        fields: ADVANCED_FILTERS_CONFIG[curr.query.search_mode]
                    }).logic ?? null
                }
            }),
            () => {
                this.encodeQueryToParams(this.state.query);
            }
        )
    }

    fetchData = async () => {
        if (this.state.queryPromise) {
            // Cancel previous search if possible (requires AbortController in searchData)
            this.state.queryPromise.abort?.();
        }
        const controller = new AbortController();
        const queryPromise = searchData(this.state.query, {signal: controller.signal});
        this.setState((curr) => ({...curr, queryPromise: controller}), async () => {
            try {
                const results = await queryPromise;
                this.setState((curr) => ({...curr, results, loadingData: false, queryPromise: null}));
            } catch (e: any) {
                if (e.name !== "AbortError") {
                    this.setState((curr) => ({...curr, loadingData: false, queryPromise: null}));
                }
            }
        });
    }

    // Add this method to handle changes:
    onAdvancedFiltersChange = (immutableTree: ImmutableTree) => {
        this.setState({advancedFiltersTree: immutableTree});
        const jsonTree = QbUtils.getTree(immutableTree);
        console.log(jsonTree);
    };

    // Add this method to render the builder:
    renderAdvancedFiltersBuilder = (props: BuilderProps) => (
        <div className="query-builder-container" style={{padding: "10px"}}>
            <div className="query-builder qb-lite">
                <Builder {...props} />
            </div>
        </div>
    );

    render() {
        return <div className={"page-wrap"}>
            <TopNavBar>
                Search Archives
            </TopNavBar>
            <div className={"page-content content-wrap"}>
                <Stack gap={2} sx={{width: '100%'}} divider={<Divider orientation="horizontal" flexItem/>}>
                    {/* Search Bar */}
                    <Box sx={{mb: 2}}>
                        <Stack direction="row" spacing={2}>
                            <OutlinedInput
                                value={
                                    this.state.typedSearchTerm || ""
                                }
                                onChange={e => this.setState((curr) => ({
                                    ...curr,
                                    typedSearchTerm: e.target.value
                                }))}
                                onKeyDown={async e => {
                                    if (e.key === 'Enter') {
                                        this.performSearch();
                                    }
                                }}
                                placeholder="Search..."
                                sx={{
                                    flex: 1,
                                    width: '100%',
                                    '& .MuiOutlinedInput-input': {
                                        width: 'calc(100% - 200px)',
                                    }
                                }}
                                size="small"
                                endAdornment={
                                    <Stack
                                        direction="row"
                                        gap={2}
                                        alignItems="center"
                                    >
                                        <Tooltip title={"Boolean Search Syntax Explainer"} arrow disableInteractive>
                                            <Fab
                                                color={"info"}
                                                href={"https://dev.mysql.com/doc/refman/8.4/en/fulltext-boolean.html"}
                                                size={"small"}
                                                target={"_blank"}
                                                sx={{
                                                    width: 24,
                                                    height: 24,
                                                    minHeight: 24,
                                                }}
                                            >
                                                <QuestionMarkIcon fontSize="small" sx={{fontSize: "1em"}}/>
                                            </Fab>
                                        </Tooltip>
                                        <FormControl
                                            variant="standard"
                                            sx={{width: "200px"}}
                                        >
                                            <Select
                                                value={this.state.query.search_mode}
                                                onChange={(e) => {
                                                    this.setState((curr) => ({
                                                        ...curr,
                                                        query: {
                                                            ...curr.query,
                                                            search_mode: e.target.value as T_Search_Mode
                                                        },
                                                        advancedFiltersTree: getEmptyTree(e.target.value as T_Search_Mode)
                                                    }), async () => {
                                                        this.performSearch()
                                                    })
                                                }}
                                                sx={{
                                                    width: "100%",
                                                    '& .MuiSelect-select': {
                                                        paddingLeft: '8px',
                                                    },
                                                    '::before': {borderBottom: 'none !important'}
                                                }}
                                            >
                                                {
                                                    SEARCH_MODES.map((mode) => (
                                                        <MenuItem
                                                            key={mode.key}
                                                            value={mode.key}
                                                        >
                                                            {mode.label}
                                                        </MenuItem>
                                                    ))
                                                }
                                            </Select>
                                        </FormControl>
                                    </Stack>
                                }
                            />
                            <IconButton
                                color="primary"
                                sx={{padding: '8px'}}
                                onClick={() => this.performSearch()}
                            >
                                <SearchIcon/>
                            </IconButton>
                            <IconButton
                                color="primary"
                                sx={{padding: '8px'}}
                                onClick={() => this.setState((curr) => ({
                                    ...curr,
                                    showAdvancedFilters: !curr.showAdvancedFilters
                                }))}
                            >
                                <FilterListIcon/>
                            </IconButton>
                        </Stack>
                    </Box>
                    <Collapse in={this.state.showAdvancedFilters} timeout="auto" unmountOnExit>
                        <Stack direction={"column"} gap={1} sx={{width: "100%"}}>
                            <Box onKeyDown={(e: React.KeyboardEvent) => {
                                if (e.key === "Enter") {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    this.performSearch();
                                }
                            }}>
                                <Query
                                    {
                                        ...InitialConfig
                                    }
                                    fields={ADVANCED_FILTERS_CONFIG[this.state.query.search_mode]}
                                    value={this.state.advancedFiltersTree}
                                    onChange={this.onAdvancedFiltersChange}
                                    renderBuilder={this.renderAdvancedFiltersBuilder}
                                />
                            </Box>
                            <Button variant={"contained"} onClick={() => this.performSearch()}>Apply Filters</Button>
                        </Stack>
                    </Collapse>
                    {/* Search Results */}
                    <Box sx={{minHeight: 200}}>
                        {this.state.queryPromise !== null ? (
                            <Box sx={{display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200}}>
                                <CircularProgress/>
                            </Box>
                        ) : (
                            <Stack
                                spacing={2}
                                divider={<Divider orientation={"horizontal"} flexItem/>}
                            >
                                {this.state.results.length === 0 ? (
                                    <Box>No results found.</Box>
                                ) : (
                                    this.state.results.map((result, idx) => (
                                        <a
                                            key={idx}
                                            href={`/${result.page}/${result.id}`}
                                            style={{
                                                textDecoration: 'none',
                                            }}
                                        >
                                            <Card variant="elevation" elevation={0}>
                                                <Typography variant={"h6"}>
                                                    {result.title}
                                                </Typography>
                                                {result.details && (
                                                    <Typography variant={"body2"}>
                                                        {result.details}
                                                    </Typography>
                                                )}
                                                <CardMedia>
                                                    {
                                                        <Stack direction="row" gap={1}>
                                                            {result.thumbnails?.map((tn, i) => {
                                                                return <img
                                                                    key={i}
                                                                    src={anchor_local_static_files(tn) || undefined}
                                                                    alt={`Thumbnail ${i + 1}`}
                                                                    style={{
                                                                        maxWidth: '100px',
                                                                        maxHeight: '100px',
                                                                    }}
                                                                />
                                                            })}
                                                        </Stack>
                                                    }
                                                </CardMedia>
                                            </Card>
                                        </a>
                                    ))
                                )}
                            </Stack>
                        )}
                    </Box>
                    {/* Pagination */}
                    <Stack direction="row" spacing={2} justifyContent={'center'} alignItems={'center'}>
                        <Button
                            variant={"text"}
                            disabled={this.state.query.page_number <= 1}
                            onClick={() => {
                                this.setState((curr) => ({
                                    ...curr,
                                    query: {...curr.query, page_number: curr.query.page_number - 1}
                                }), this.fetchData);
                            }}
                        >
                            Previous
                        </Button>
                        <Box>Page {this.state.query.page_number}</Box>
                        <Button
                            variant={"text"}
                            onClick={() => {
                                this.setState((curr) => ({
                                    ...curr,
                                    query: {...curr.query, page_number: curr.query.page_number + 1}
                                }), this.fetchData);
                            }}
                        >
                            Next
                        </Button>
                    </Stack>
                </Stack>
            </div>
        </div>
    }
}

export default withRouter(SearchPage);