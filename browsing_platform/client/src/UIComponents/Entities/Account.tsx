import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
    IAccountAndAssociatedEntities,
    IAccountAuxiliaryCounts,
    IAccountInteractions,
    IAccountRelation,
    IAccountRelationsResponse,
    IPostAndAssociatedEntities
} from "../../types/entities";
import {ITagStat, ITagWithType} from "../../types/tags";
import {
    Box,
    CircularProgress,
    Collapse,
    IconButton,
    Link,
    List,
    ListItem,
    Paper,
    Stack,
    Tab,
    Tabs,
    Tooltip,
    Typography
} from "@mui/material";
import HistoryIcon from '@mui/icons-material/History';
import Post from "./Post";
import ReactJson from "react-json-view";
import {
    fetchAccountAuxiliaryCounts,
    fetchAccountData,
    fetchAccountInteractions,
    fetchAccountRelations,
    fetchRelatedTagStats
} from "../../services/DataFetcher";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import EntityAnnotator from "./Annotator";
import AccountRelation from "./AccountRelation";
import AccountComment from "./AccountComment";
import AccountLike from "./AccountLike";
import AccountTaggedInPost from "./AccountTaggedInPost";
import RelatedTagDistributionTable from "../Tags/RelatedTagDistributionTable";

import {getShareTokenFromHref, SHARE_URL_PARAM} from "../../services/linkSharing";
import {AddReaction, DataObject, LocalOffer, People} from "@mui/icons-material";

function parseCssDimension(value: string | number | undefined, viewportPx: number): number {
    if (value == null) return 0;
    if (typeof value === 'number') return value;
    if (value.endsWith('vh')) return (parseFloat(value) / 100) * viewportPx;
    if (value.endsWith('px')) return parseFloat(value);
    return 0;
}

function estimatePostHeight(
    post: IPostAndAssociatedEntities,
    mediaStyle: React.CSSProperties | undefined,
): number {
    const vh = typeof window !== 'undefined' ? window.innerHeight : 900;
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1200;

    // Fixed structure: paper padding (32) + URL (22) + date (20) + annotator (40)
    //   + tab bar (40) + 2 Stack gaps at 4px each
    //   + ~6 Stack gaps at 4px each
    const FIXED = 32 + 22 + 20 + 40 + 3 * 40 + 6 * 4;

    // Caption (body2, ~80 chars/line, 24px line-height)
    const captionLines = post.caption ? Math.ceil(post.caption.length / 80) : 0;
    const captionHeight = captionLines * 24;

    // Tagged accounts row
    const taggedHeight = (post.post_tagged_accounts?.length ?? 0) > 0 ? 36 : 0;

    // Media section (wrapping flex row, width ≈ height rule of thumb)
    const numMedia = post.post_media?.length ?? 0;
    let mediaHeight = 0;
    if (numMedia > 0 && mediaStyle) {
        const maxH = parseCssDimension(mediaStyle.maxHeight, vh);
        const minH = parseCssDimension(mediaStyle.minHeight, vh);
        const itemH = Math.max(minH || 0, maxH || 300);
        const itemW = itemH;
        const containerW = vw - 128;
        const gap = 8;
        const itemsPerRow = Math.max(1, Math.floor((containerW + gap) / (itemW + gap)));
        const rows = Math.ceil(numMedia / itemsPerRow);
        mediaHeight = rows * itemH + (rows - 1) * gap;
    }

    return FIXED + captionHeight + taggedHeight + mediaHeight;
}

const HIGHLIGHT_STYLE: React.CSSProperties = {
    backgroundColor: '#fff8dc',
    borderRadius: 4,
    padding: '2px 4px',
    marginLeft: -4,
};

function AccountRelationsPanel({loadingRelations, relations, highlightRelationId, relationRefs, contextAccountId, accountTagsMap}: {
    loadingRelations: boolean;
    relations: IAccountRelation[] | null;
    highlightRelationId?: number;
    relationRefs: React.MutableRefObject<Map<number, HTMLElement>>;
    contextAccountId?: number;
    accountTagsMap: Record<number, ITagWithType[]>;
}) {
    return (
        <>
            {loadingRelations && <CircularProgress size={16}/>}
            {relations && relations.length === 0 && (
                <Typography variant="caption" color="text.secondary">No relations found</Typography>
            )}
            {relations && relations.length > 0 && (
                <Stack gap={0.5}>
                    {relations.map((r, i) => (
                        <div
                            key={i}
                            ref={r.id != null ? el => {
                                if (el) relationRefs.current.set(r.id!, el);
                            } : undefined}
                            style={r.id != null && r.id === highlightRelationId ? HIGHLIGHT_STYLE : undefined}
                        >
                            <AccountRelation relation={r} contextAccountId={contextAccountId} accountTagsMap={accountTagsMap}/>
                        </div>
                    ))}
                </Stack>
            )}
        </>
    );
}

function AccountInteractionsPanel({loadingInteractions, interactions}: {
    loadingInteractions: boolean;
    interactions: IAccountInteractions | null;
}) {
    return (
        <>
            {loadingInteractions && <CircularProgress size={16}/>}
            {interactions && (
                <Stack gap={1}>
                    {interactions.comments.length > 0 && (
                        <Stack gap={0.5}>
                            <Typography variant="caption" color="text.secondary">
                                Comments ({interactions.comments.length})
                            </Typography>
                            {interactions.comments.map((c, i) => <AccountComment key={i} comment={c}/>)}
                        </Stack>
                    )}
                    {interactions.likes.length > 0 && (
                        <Stack gap={0.5}>
                            <Typography variant="caption" color="text.secondary">
                                Likes ({interactions.likes.length})
                            </Typography>
                            {interactions.likes.map((l, i) => <AccountLike key={i} like={l}/>)}
                        </Stack>
                    )}
                    {interactions.tagged_in.length > 0 && (
                        <Stack gap={0.5}>
                            <Typography variant="caption" color="text.secondary">
                                Tagged in ({interactions.tagged_in.length})
                            </Typography>
                            <Stack gap={0.5}>
                                {interactions.tagged_in.map((ta, i) => (
                                    <AccountTaggedInPost key={i} taggedAccount={ta}/>
                                ))}
                            </Stack>
                        </Stack>
                    )}
                    {interactions.comments.length === 0 && interactions.likes.length === 0 && interactions.tagged_in.length === 0 && (
                        <Typography variant="caption" color="text.secondary">No interactions found</Typography>
                    )}
                </Stack>
            )}
        </>
    );
}

interface IProps {
    account: IAccountAndAssociatedEntities
    viewerConfig?: EntityViewerConfig
    highlightCommentId?: number
    highlightLikeId?: number
    highlightRelationId?: number
    initialAccountTagsMap?: Record<number, ITagWithType[]>
}

const usernameFromUrl = (url?: string): string | null => {
    if (!url) {
        return null
    }
    const urlParts = url.trim().split("/").filter(x => x.length);
    return urlParts[urlParts.length - 1]
}

export default function Account({
                                    account: accountProp,
                                    viewerConfig,
                                    highlightCommentId,
                                    highlightLikeId,
                                    highlightRelationId,
                                    initialAccountTagsMap,
                                }: IProps) {
    const [account, setAccount] = useState(accountProp);
    const [awaitingDetailsFetch, setAwaitingDetailsFetch] = useState(false);
    const [accountTagsMap, setAccountTagsMap] = useState<Record<number, ITagWithType[]>>(initialAccountTagsMap ?? {});
    const [renderedIndices, setRenderedIndices] = useState<Set<number>>(() => {
        const pSize = viewerConfig?.account?.postsPageSize;
        if (!pSize) return new Set<number>(); // export mode: irrelevant, all posts render via !pageSize check
        return new Set(Array.from({length: pSize}, (_, i) => i));
    });

    const [relations, setRelations] = useState<IAccountRelation[] | null>(null);
    const [loadingRelations, setLoadingRelations] = useState(false);

    const [interactions, setInteractions] = useState<IAccountInteractions | null>(null);
    const [loadingInteractions, setLoadingInteractions] = useState(false);

    const [relatedTags, setRelatedTags] = useState<ITagStat[] | null>(null);
    const [loadingRelatedTags, setLoadingRelatedTags] = useState(false);

    const mergeAccountTags = (newTags: Record<number, ITagWithType[]> | undefined) => {
        if (newTags && Object.keys(newTags).length > 0) {
            setAccountTagsMap(prev => ({...prev, ...newTags}));
        }
    };

    const [activeTab, setActiveTab] = useState<'relations' | 'interactions' | 'tagDistribution' | 'raw' | null>(
        highlightRelationId ? 'relations' : null
    );
    const handleTabToggle = (tab: 'relations' | 'interactions' | 'tagDistribution' | 'raw') => () => {
        if (activeTab === tab) setActiveTab(null);
    };

    const [auxiliaryCounts, setAuxiliaryCounts] = useState<IAccountAuxiliaryCounts | null>(null);

    const relationRefs = useRef<Map<number, HTMLElement>>(new Map());
    const observerRef = useRef<IntersectionObserver | null>(null);

    const fetchAccountDetails = async () => {
        const itemId = account.id;
        if (awaitingDetailsFetch || itemId === undefined || itemId === null) return;
        setAwaitingDetailsFetch(true);
        const data = await fetchAccountData(itemId);
        setAccount(curr => ({...curr, data}));
        setAwaitingDetailsFetch(false);
    };

    const loadRelations = useCallback(async () => {
        if (loadingRelations || relations !== null || account.id == null) return;
        setLoadingRelations(true);
        const fetched: IAccountRelationsResponse | null = await fetchAccountRelations(account.id);
        setRelations(fetched?.relations ?? null);
        mergeAccountTags(fetched?.account_tags);
        setLoadingRelations(false);
    }, [loadingRelations, relations, account.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const loadInteractions = useCallback(async () => {
        if (loadingInteractions || interactions !== null || account.id == null) return;
        setLoadingInteractions(true);
        const fetched = await fetchAccountInteractions(account.id);
        setInteractions(fetched);
        mergeAccountTags(fetched?.account_tags);
        setLoadingInteractions(false);
    }, [loadingInteractions, interactions, account.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const loadRelatedTags = useCallback(async () => {
        if (loadingRelatedTags || relatedTags !== null || account.id == null) return;
        setLoadingRelatedTags(true);
        const fetched = await fetchRelatedTagStats(account.id);
        setRelatedTags(fetched);
        setLoadingRelatedTags(false);
    }, [loadingRelatedTags, relatedTags, account.id]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (activeTab === 'relations') loadRelations();
        if (activeTab === 'interactions') loadInteractions();
        if (activeTab === 'tagDistribution') loadRelatedTags();
        if (activeTab === 'raw') fetchAccountDetails();
    }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

    const sortedPosts = useMemo(() =>
        [...account.account_posts].sort((a, b) =>
            (new Date(b.publication_date || 0).getTime()) - (new Date(a.publication_date || 0).getTime())
        ), [account.account_posts]);

    const compactMode = viewerConfig?.post?.compactMode ?? false;

    const effectiveConfig = useMemo(() => {
        if (!compactMode) return viewerConfig;
        return {
            ...viewerConfig,
            post: {...viewerConfig?.post, compactMode: true},
            media: {
                ...viewerConfig?.media,
                style: {
                    width: '100%',
                    aspectRatio: '1 / 1',
                    overflow: 'hidden',
                    objectFit: 'cover' as const,
                },
            },
        };
    }, [compactMode, viewerConfig]);

    const pageSize = viewerConfig?.account?.postsPageSize ?? null;
    const mediaStyle = viewerConfig?.media?.style;
    const estimatedHeights = useMemo(
        () => sortedPosts.map(p => estimatePostHeight(p, mediaStyle)),
        [sortedPosts, mediaStyle]
    );

    // Returns the shared IntersectionObserver, creating it on first use.
    // Using a getter instead of an effect avoids timing issues between ref callbacks and effects.
    const getObserver = useCallback((): IntersectionObserver | null => {
        if (!pageSize) return null;
        if (!observerRef.current) {
            observerRef.current = new IntersectionObserver(
                (entries) => {
                    const newIndices = entries
                        .filter(e => e.isIntersecting)
                        .map(e => parseInt((e.target as HTMLElement).dataset.postIndex!))
                        .filter(i => !isNaN(i));
                    if (newIndices.length > 0) {
                        setRenderedIndices(prev => {
                            const toAdd = newIndices.filter(i => !prev.has(i));
                            if (toAdd.length === 0) return prev;
                            const next = new Set(prev);
                            toAdd.forEach(i => next.add(i));
                            return next;
                        });
                        const maxNewIndex = Math.max(...newIndices);
                        setTimeout(() => {
                            setRenderedIndices(prev => {
                                const preloadIndices = [maxNewIndex + 1, maxNewIndex + 2];
                                const toAdd = preloadIndices.filter(i => !prev.has(i));
                                if (toAdd.length === 0) return prev;
                                const next = new Set(prev);
                                toAdd.forEach(i => next.add(i));
                                return next;
                            });
                        }, 0);
                    }
                },
                {root: null, rootMargin: '0px 0px 400px 0px', threshold: 0}
            );
        }
        return observerRef.current;
    }, [pageSize]);

    // Disconnect observer on unmount
    useEffect(() => {
        return () => {
            observerRef.current?.disconnect();
        };
    }, []);

    useEffect(() => {
        if (account.id == null) return;
        fetchAccountAuxiliaryCounts(account.id)
            .then(counts => setAuxiliaryCounts(counts))
            .catch(() => {
            });
    }, [account.id]); // eslint-disable-line react-hooks/exhaustive-deps

    // Scroll to highlighted relation after load
    useEffect(() => {
        if (highlightRelationId && relations) {
            const el = relationRefs.current.get(highlightRelationId);
            el?.scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    }, [relations, highlightRelationId]);

    const relationsLabel = auxiliaryCounts != null
        ? `Related Accounts (${auxiliaryCounts.relations_count})`
        : "Related Accounts";

    const interactionsLabel = (() => {
        if (auxiliaryCounts == null) return "Interactions";
        const ic = auxiliaryCounts.interaction_counts;
        const total = ic.comments_count + ic.likes_count + ic.tagged_in_count;
        if (total === 0) return "Interactions (0)";
        const parts: string[] = [];
        if (ic.comments_count > 0) parts.push(`comments: ${ic.comments_count}`);
        if (ic.likes_count > 0) parts.push(`likes: ${ic.likes_count}`);
        if (ic.tagged_in_count > 0) parts.push(`tagged: ${ic.tagged_in_count}`);
        return `Interactions (${parts.join(", ")})`;
    })();

    const urls = (account.identifiers || []).filter(x => x.startsWith("url_")).map(x => x.split("url_")[1]);
    const shareToken = getShareTokenFromHref();
    const accountHref = "/account/" + account.id + (shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : "");
    const disableAccountLink = viewerConfig?.all?.hideInnerLinks;

    return <Paper sx={{padding: '1em'}}>
        <Stack gap={0.5} sx={{height: "100%"}}>
            <Stack gap={1} direction={"row"} alignItems={"center"}>
                <Typography variant={"subtitle2"} sx={{userSelect: "all"}}
                            color={"textSecondary"}>{account.url}</Typography>
                {
                    urls.length > 1 ? <Tooltip
                        title={
                            <List>
                                {urls.map((url, i) => <ListItem key={i}>{url}</ListItem>)}
                            </List>
                        }
                        arrow
                    >
                        <span>
                            <IconButton size="small" color={"info"}>
                                <HistoryIcon/>
                            </IconButton>
                        </span>
                    </Tooltip> : null
                }
            </Stack>
            {disableAccountLink
                ? <Typography variant="h5" sx={{alignSelf: 'flex-start'}}>
                    {account.display_name ? account.display_name : usernameFromUrl(account.url) || account.url}
                </Typography>
                : <Link href={accountHref} color={"primary"} sx={{alignSelf: 'flex-start'}}>
                    <Typography variant="h5">
                        {account.display_name ? account.display_name : usernameFromUrl(account.url) || account.url}
                    </Typography>
                </Link>
            }
            <Typography variant="caption">{account.bio}</Typography>
            {
                viewerConfig?.account?.annotator !== "hide" && <Stack gap={1}>
                    <EntityAnnotator
                        entity={account}
                        entityType={"account"}
                        readonly={viewerConfig?.account?.annotator === "disable"}
                    />
                </Stack>
            }

            {/* Relations / Interactions / Raw Data — tab-toggle panel */}
            <Box>
                <Tabs
                    value={activeTab ?? false}
                    onChange={(_, val) => setActiveTab(val)}
                    variant="scrollable"
                    scrollButtons="auto"
                    sx={{minHeight: 32, '& .MuiTab-root': {minHeight: 32, py: 0.5, textTransform: 'none'}}}
                >
                    {viewerConfig?.accountRelation?.display !== 'hide' && account.id != null && (
                        <Tab
                            value="relations"
                            label={relationsLabel}
                            icon={<People/>} iconPosition="start"
                            onClick={handleTabToggle('relations')}
                        />
                    )}
                    {account.id != null && (
                        <Tab
                            value="interactions"
                            label={interactionsLabel}
                            icon={<AddReaction/>} iconPosition="start"
                            onClick={handleTabToggle('interactions')}
                        />
                    )}
                    {account.id != null && (
                        <Tab
                            value="tagDistribution"
                            label="Tag Distribution"
                            icon={<LocalOffer/>} iconPosition="start"
                            onClick={handleTabToggle('tagDistribution')}
                        />
                    )}
                    <Tab
                        value="raw"
                        label="Raw Data"
                        icon={<DataObject/>} iconPosition="start"
                        onClick={handleTabToggle('raw')}
                    />
                </Tabs>

                <Collapse in={activeTab !== null}>
                    <Box sx={{mt: 1}}>
                        {activeTab === 'relations' && (
                            <AccountRelationsPanel
                                loadingRelations={loadingRelations}
                                relations={relations}
                                highlightRelationId={highlightRelationId}
                                relationRefs={relationRefs}
                                contextAccountId={account.id}
                                accountTagsMap={accountTagsMap}
                            />
                        )}
                        {activeTab === 'interactions' && (
                            <AccountInteractionsPanel
                                loadingInteractions={loadingInteractions}
                                interactions={interactions}
                            />
                        )}
                        {activeTab === 'tagDistribution' && (
                            loadingRelatedTags
                                ? <CircularProgress size={16}/>
                                : <RelatedTagDistributionTable stats={relatedTags ?? []}/>
                        )}
                        {activeTab === 'raw' && (
                            <>
                                {awaitingDetailsFetch && <CircularProgress size={16}/>}
                                {account.data && (
                                    <ReactJson src={account.data} enableClipboard={false}
                                               style={{wordBreak: 'break-word'}}/>
                                )}
                            </>
                        )}
                    </Box>
                </Collapse>
            </Box>

            {/* Posts section */}
            <Box sx={compactMode
                ? {display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 1, width: '100%'}
                : {display: 'flex', flexDirection: 'column', gap: 1, width: '100%', flexGrow: 1}
            }>
                {sortedPosts.map((p, i) => {
                    if (compactMode || !pageSize || renderedIndices.has(i)) {
                        return (
                            <Post
                                key={p.id ?? i}
                                post={p}
                                viewerConfig={effectiveConfig as EntityViewerConfig}
                                highlightCommentId={highlightCommentId}
                                highlightLikeId={highlightLikeId}
                                initialAccountTagsMap={accountTagsMap}
                            />
                        );
                    }
                    // Placeholder for unrendered post — registers with shared observer on mount
                    return (
                        <div
                            key={p.id ?? i}
                            ref={(el) => {
                                if (el) getObserver()?.observe(el);
                            }}
                            data-post-index={String(i)}
                            style={{height: estimatedHeights[i], width: '100%', boxSizing: 'border-box'}}
                            aria-hidden="true"
                        />
                    );
                })}
            </Box>
        </Stack>
    </Paper>
}
