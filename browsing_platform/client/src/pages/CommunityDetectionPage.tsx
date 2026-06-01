import React, {useMemo, useRef, useState} from 'react';
import {useSearchParams} from 'react-router';
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Chip,
    CircularProgress,
    Collapse,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    FormControlLabel,
    IconButton,
    Link,
    Paper,
    Snackbar,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CloseIcon from '@mui/icons-material/Close';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import AutoModeIcon from '@mui/icons-material/AutoMode';
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined';
import FileUploadOutlinedIcon from '@mui/icons-material/FileUploadOutlined';
import UndoIcon from '@mui/icons-material/Undo';
import TopNavBar from '../UIComponents/TopNavBar/TopNavBar';
import {SearchResultThumbnails} from '../UIComponents/SearchResults/SearchResultParts';
import NumberField from '../UIComponents/MUINumberField/NumberField';
import SearchPanel from '../UIComponents/Search/SearchPanel';
import QuickAccessTypeDropdown from '../UIComponents/Tags/QuickAccessTypeDropdown';
import TagSelector from '../UIComponents/Tags/TagSelector';
import {
    batchAnnotate,
    CandidateAccount,
    CommunityCandidatesResponse,
    DEFAULT_TIE_WEIGHTS,
    fetchCommunityCandidates,
    fetchRelatedTagStats,
    fetchTagKernelAccounts,
    fetchTagsForSearchResults,
    ISearchQuery,
    removeAccountTag,
    SearchResult,
    TagKernelAccount,
    TagKernelResponse,
    Thumbnail,
    TieWeights,
} from '../services/DataFetcher';
import {IQuickAccessTypeDropdown, ITagStat, ITagWithType} from '../types/tags';
import RelatedTagDistributionTable from '../UIComponents/Tags/RelatedTagDistributionTable';
import {downloadTextFile} from '../services/utils';

const EMPTY_ID_SET = new Set<number>();
const COMMUNITY_TAG_PLACEHOLDER = 'Assign Community Tag';
const BASE_TITLE = 'Community Detection | Browsing Platform';
const COMMUNITY_TAG_PARAM = 'communityTag';
const stripThumbnails = <T extends { thumbnails?: Thumbnail[] }>(obj: T): T => ({...obj, thumbnails: []});

// ── Serialisable state (export / import) ──────────────────────────────────────

interface CommunityStateExport {
    version: 1;
    community_tag: ITagWithType | null;
    community_dropdown: IQuickAccessTypeDropdown | null;
    kernel: Array<{ account: SearchResult; manuallyAdded: boolean; tagSources: ITagWithType[] }>;
    weights: TieWeights;
    excluded: CandidateAccount[];
}

function isCommunityStateExport(v: unknown): v is CommunityStateExport {
    if (!v || typeof v !== 'object') return false;
    const s = v as Record<string, unknown>;
    return s.version === 1
        && Array.isArray(s.kernel)
        && s.weights !== null && typeof s.weights === 'object'
        && Array.isArray(s.excluded);
}

// ── Kernel entry type ─────────────────────────────────────────────────────────

interface KernelEntry {
    account: SearchResult;
    manuallyAdded: boolean;
    tagSources: ITagWithType[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function candidateTitle(c: Pick<CandidateAccount, 'id' | 'url_suffix' | 'display_name'>): string {
    return c.display_name
        ? `${c.url_suffix} (${c.display_name})`
        : (c.url_suffix ?? `Account ${c.id}`);
}

function tagKernelAccountToSearchResult(a: TagKernelAccount): SearchResult {
    return {
        id: a.id,
        page: 'account',
        title: candidateTitle(a),
        details: a.bio ?? undefined,
        thumbnails: a.thumbnails,
        metadata: {media_count: a.media_count, url_suffix: a.url_suffix, display_name: a.display_name},
    };
}

// ── Step badge ────────────────────────────────────────────────────────────────

function StepBadge({n, active}: { n: number; active?: boolean }) {
    return (
        <Box sx={{
            width: 24, height: 24, borderRadius: '50%',
            border: '2px solid',
            borderColor: active ? 'primary.main' : 'divider',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
            bgcolor: active ? 'primary.main' : 'transparent',
            transition: 'all 0.2s',
        }}>
            <Typography sx={{
                fontSize: '0.7rem', fontWeight: 700, lineHeight: 1,
                color: active ? 'primary.contrastText' : 'text.disabled',
            }}>
                {n}
            </Typography>
        </Box>
    );
}

// ── Section header ────────────────────────────────────────────────────────────

interface SectionHeaderProps {
    step: number;
    title: string;
    active?: boolean;
    action?: React.ReactNode;
}

function SectionHeader({step, title, active, action}: SectionHeaderProps) {
    return (
        <Stack direction="row" alignItems="center" gap={1.25} sx={{mb: 1.5}}>
            <StepBadge n={step} active={active}/>
            <Typography variant="subtitle1" sx={{fontWeight: 600, flex: 1, letterSpacing: '-0.01em'}}>
                {title}
            </Typography>
            {action}
        </Stack>
    );
}

// ── Kernel account pill ───────────────────────────────────────────────────────

interface KernelAccountPillProps {
    entry: KernelEntry;
    communityDropdown: IQuickAccessTypeDropdown | null;
    onRemove: () => void;
    onTagToggle: (tag: ITagWithType) => void;
}

function KernelAccountPill({entry, communityDropdown, onRemove, onTagToggle}: KernelAccountPillProps) {
    const assignedTagIds = useMemo(
        () => new Set(entry.tagSources.map(t => t.id!)),
        [entry.tagSources],
    );

    return (
        <Box sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 0.5,
            border: '1px solid',
            borderColor: 'primary.light',
            borderRadius: 4,
            px: 1, py: 0.25,
            bgcolor: 'background.paper',
            flexWrap: 'wrap',
            '&:hover': {borderColor: 'primary.main'},
            transition: 'border-color 0.15s',
        }}>
            <Link href={`/account/${entry.account.id}`} target="_blank" rel="noopener noreferrer"
                  underline="hover" color="primary.main"
                  sx={{fontSize: '0.8125rem', lineHeight: 1.5, fontWeight: 500}}>
                {entry.account.title}
            </Link>

            {/* Tag membership indicator / control */}
            {communityDropdown && (
                <QuickAccessTypeDropdown
                    dropdown={communityDropdown}
                    assignedTagIds={assignedTagIds}
                    onSelect={onTagToggle}
                    placeholder={COMMUNITY_TAG_PLACEHOLDER}
                />
            )}

            {/* Manual indicator: shown when in tag mode but no tag sources */}
            {communityDropdown && entry.tagSources.length === 0 && entry.manuallyAdded && (
                <Chip
                    label="Manual"
                    size="small"
                    variant="outlined"
                    sx={{height: 18, fontSize: '0.6rem', '& .MuiChip-label': {px: 0.75}}}
                />
            )}

            <IconButton size="small" onClick={onRemove}
                        sx={{p: 0.25, ml: 0.25, color: 'primary.light', '&:hover': {color: 'error.main'}}}
                        aria-label={`Remove ${entry.account.title} from kernel`}>
                <CloseIcon sx={{fontSize: '0.8rem'}}/>
            </IconButton>
        </Box>
    );
}

// ── Candidate card ────────────────────────────────────────────────────────────

interface CandidateCardProps {
    candidate: CandidateAccount;
    communityDropdown: IQuickAccessTypeDropdown | null;
    assignedCommunityTagIds: Set<number>;
    onAddToKernel: () => void;
    onExclude: () => void;
    onTagToggle: (tag: ITagWithType) => void;
    tagDistribution?: ITagStat[];
    tagDistributionLoading: boolean;
    onTagDistributionOpen: () => void;
}

function CandidateCard({
                           candidate,
                           communityDropdown,
                           assignedCommunityTagIds,
                           onAddToKernel,
                           onExclude,
                           onTagToggle,
                           tagDistribution,
                           tagDistributionLoading,
                           onTagDistributionOpen,
                       }: CandidateCardProps) {
    const title = candidateTitle(candidate);
    const score = candidate.score % 1 === 0
        ? candidate.score.toString()
        : candidate.score.toFixed(2);
    return (
        <Stack direction="row" gap={2} alignItems="flex-start" sx={{py: 0.5}}>
            {/* Score column */}
            <Tooltip
                arrow
                placement="right"
                enterDelay={100}
                leaveDelay={100}
                onOpen={onTagDistributionOpen}
                slotProps={{
                    tooltip: {
                        sx: {
                            bgcolor: 'background.paper',
                            color: 'text.primary',
                            border: '1px solid',
                            borderColor: 'divider',
                            boxShadow: 3,
                            maxWidth: 'none',
                        },
                    },
                    arrow: {
                        sx: {
                            color: 'background.paper',
                            '&::before': {
                                border: '1px solid',
                                borderColor: 'divider',
                                boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
                            },
                        },
                    },
                }}
                title={
                    tagDistributionLoading
                        ? <CircularProgress size={16}/>
                        : <RelatedTagDistributionTable stats={tagDistribution ?? []}/>
                }
            >
                <Box sx={{
                    flexShrink: 0, width: 56, textAlign: 'center',
                    pt: 0.5, borderRight: '1px solid', borderColor: 'divider', pr: 2,
                    cursor: 'help',
                }}>
                    <Typography variant="h5"
                                sx={{fontWeight: 700, lineHeight: 1, color: 'primary.main', fontSize: '1.5rem'}}>
                        {score}
                    </Typography>
                    <Typography variant="caption" sx={{
                        color: 'text.disabled',
                        display: 'block',
                        mt: 0.25,
                        letterSpacing: '0.05em',
                        textTransform: 'uppercase',
                        fontSize: '0.6rem'
                    }}>
                        score
                    </Typography>
                </Box>
            </Tooltip>

            {/* Content */}
            <Box sx={{flex: 1, minWidth: 0}}>
                <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
                    <a href={`/account/${candidate.id}`} target="_blank" rel="noopener noreferrer"
                       style={{textDecoration: 'none', color: 'inherit'}}>
                        <Typography variant="subtitle1" sx={{
                            fontWeight: 600,
                            wordBreak: 'break-word',
                            '&:hover': {textDecoration: 'underline'}
                        }}>
                            {title}
                        </Typography>
                    </a>
                    {candidate.is_verified && (
                        <Chip label="Verified" size="small" color="info" variant="outlined"
                              sx={{height: 18, '& .MuiChip-label': {px: 0.75, fontSize: '0.6rem'}}}/>
                    )}
                </Stack>
                {candidate.bio && (
                    <Typography variant="body2" color="text.secondary" sx={{mt: 0.25, fontSize: '0.8125rem'}}>
                        {candidate.bio}
                    </Typography>
                )}
                <SearchResultThumbnails thumbnails={candidate.thumbnails} totalCount={candidate.media_count}/>
            </Box>

            {/* Decision panel */}
            <Box
                sx={{
                    flexShrink: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'stretch',
                    gap: 0.5,
                    borderLeft: '1px solid',
                    borderColor: 'divider',
                    pl: 1.5,
                    minWidth: 148,
                }}
            >
                {communityDropdown && (
                    <>
                        <Typography
                            variant="caption"
                            sx={{
                                color: 'text.disabled',
                                fontSize: '0.6rem',
                                letterSpacing: '0.08em',
                                textTransform: 'uppercase',
                                lineHeight: 1,
                            }}
                        >
                            Tag &amp; add to kernel
                        </Typography>
                        <QuickAccessTypeDropdown
                            dropdown={communityDropdown}
                            assignedTagIds={assignedCommunityTagIds}
                            onSelect={onTagToggle}
                            placeholder={COMMUNITY_TAG_PLACEHOLDER}
                        />
                        <Divider flexItem sx={{my: 0.25}}>
                            <Typography variant="caption" color="text.disabled" sx={{fontSize: '0.65rem'}}>
                                or
                            </Typography>
                        </Divider>
                    </>
                )}
                <Button
                    size="small" variant="outlined" color={"success"}
                    onClick={onAddToKernel}
                    sx={{whiteSpace: 'nowrap', fontSize: '0.75rem'}}
                >
                    {communityDropdown ? 'Add to kernel without attaching tag' : 'Add to kernel'}
                </Button>
                <Button
                    size="small" variant="outlined" color="error"
                    onClick={onExclude}
                    sx={{fontSize: '0.75rem'}}
                >
                    Remove from Candidates List
                </Button>
            </Box>
        </Stack>
    );
}

// ── Tie weight labels ─────────────────────────────────────────────────────────

const TIE_LABELS: Record<keyof TieWeights, string> = {
    follow: 'Follow', suggested: 'Suggested', like: 'Like', comment: 'Comment', tag: 'Tag',
};

const KERNEL_SEARCH_QUERY: ISearchQuery = {
    search_mode: 'accounts',
    search_term: '',
    page_number: 1,
    page_size: 20,
    advanced_filters: null,
    tag_ids: [],
    tag_filter_mode: 'any',
};

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CommunityDetectionPage() {
    // Kernel
    const [kernelEntries, setKernelEntries] = useState<KernelEntry[]>([]);
    const [kernelModalOpen, setKernelModalOpen] = useState(false);

    // Community tag / tag mode
    const [communityTag, setCommunityTag] = useState<ITagWithType | null>(null);
    const [communityDropdown, setCommunityDropdown] = useState<IQuickAccessTypeDropdown | null>(null);

    // Tag transition modal (when user picks a community tag while kernel is non-empty)
    const [tagTransitionPending, setTagTransitionPending] = useState<{
        tag: ITagWithType;
        tagKernelAccounts: TagKernelAccount[];
        dropdown: IQuickAccessTypeDropdown;
    } | null>(null);
    const [tagTransitionApplyToExisting, setTagTransitionApplyToExisting] = useState(false);
    const [tagTransitionLoading, setTagTransitionLoading] = useState(false);

    // Confirmation for removing an untagged kernel account after a tag is unassigned
    const [pendingKernelRemoval, setPendingKernelRemoval] = useState<KernelEntry | null>(null);

    // Evidence prompt before committing a single-account community tag assignment
    const [pendingTagAssignment, setPendingTagAssignment] = useState<{
        accountTitle: string;
        tagName: string;
        onConfirm: (evidence: string) => Promise<void>;
    } | null>(null);
    const [evidenceText, setEvidenceText] = useState('');

    // Weights
    const [weights, setWeights] = useState<TieWeights>({...DEFAULT_TIE_WEIGHTS});

    // Candidates
    const [candidates, setCandidates] = useState<CandidateAccount[]>([]);
    const [candidateAllTags, setCandidateAllTags] = useState<Record<number, ITagWithType[]>>({});
    const [isComputing, setIsComputing] = useState(false);
    const [hasRun, setHasRun] = useState(false);

    // Lazy-loaded, cached tag distribution shown in each candidate's score tooltip.
    // Cleared whenever a new analysis is run (see runAnalysis).
    const [candidateTagDistributions, setCandidateTagDistributions] = useState<Record<number, ITagStat[]>>({});
    const [loadingTagDistributions, setLoadingTagDistributions] = useState<Record<number, boolean>>({});

    const loadCandidateTagDistribution = (candidateId: number) => {
        if (candidateTagDistributions[candidateId] || loadingTagDistributions[candidateId]) return;
        setLoadingTagDistributions(prev => ({...prev, [candidateId]: true}));
        fetchRelatedTagStats(candidateId).then(stats => {
            setCandidateTagDistributions(prev => ({...prev, [candidateId]: stats}));
            setLoadingTagDistributions(prev => ({...prev, [candidateId]: false}));
        });
    };

    // Excluded accounts
    const [excludedAccounts, setExcludedAccounts] = useState<CandidateAccount[]>([]);
    const [excludedOpen, setExcludedOpen] = useState(false);

    // Export / import
    const [importError, setImportError] = useState<string | null>(null);
    const [copyFeedback, setCopyFeedback] = useState<{ severity: 'success' | 'error'; message: string } | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // URL state: the selected community tag id is reflected in the `communityTag`
    // search param (absent when no tag is selected).
    const [searchParams, setSearchParams] = useSearchParams();
    const initializedFromUrl = useRef(false);

    // Initialize the community tag from the URL on first load. With no param the
    // tag stays null; with a valid id we resolve the full tag from the tag-kernel
    // dropdown (which always contains the tag itself) and seed the kernel from it.
    React.useEffect(() => {
        const raw = searchParams.get(COMMUNITY_TAG_PARAM);
        const tagId = raw !== null ? parseInt(raw, 10) : NaN;
        if (Number.isNaN(tagId)) {
            initializedFromUrl.current = true;
            return;
        }
        let cancelled = false;
        (async () => {
            setTagTransitionLoading(true);
            try {
                const resp: TagKernelResponse = await fetchTagKernelAccounts(tagId);
                if (cancelled) return;
                const tag = resp.dropdown.tags.find(t => t.id === tagId) ?? null;
                if (tag) {
                    setCommunityTag(tag);
                    setCommunityDropdown(resp.dropdown);
                    setKernelEntries(resp.accounts.map(a => ({
                        account: tagKernelAccountToSearchResult(a),
                        manuallyAdded: false,
                        tagSources: a.applied_tags,
                    })));
                }
            } finally {
                if (!cancelled) {
                    setTagTransitionLoading(false);
                    initializedFromUrl.current = true;
                }
            }
        })();
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Keep the URL search param and document title in sync with the selected tag.
    // Guarded so it does not clobber the param before initialization has read it.
    React.useEffect(() => {
        document.title = communityTag ? `${communityTag.name} | ${BASE_TITLE}` : BASE_TITLE;
        if (!initializedFromUrl.current) return;
        setSearchParams(prev => {
            const next = new URLSearchParams(prev);
            if (communityTag?.id != null) {
                next.set(COMMUNITY_TAG_PARAM, String(communityTag.id));
            } else {
                next.delete(COMMUNITY_TAG_PARAM);
            }
            return next;
        }, {replace: true});
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [communityTag]);

    // ── Derived ───────────────────────────────────────────────────────────────

    const kernelIds = useMemo(() => kernelEntries.map(e => e.account.id), [kernelEntries]);
    const kernelIdSet = useMemo(() => new Set(kernelIds), [kernelIds]);
    const excludedIds = useMemo(() => excludedAccounts.map(a => a.id), [excludedAccounts]);
    const excludedIdSet = useMemo(() => new Set(excludedIds), [excludedIds]);
    const visibleCandidates = useMemo(() => candidates.filter(c => !excludedIdSet.has(c.id)), [candidates, excludedIdSet]);
    const hasVerifiedVisible = useMemo(() => visibleCandidates.some(c => c.is_verified === true), [visibleCandidates]);

    const communityTagIds = useMemo(
        () => communityDropdown ? new Set(communityDropdown.tags.map(t => t.id!)) : new Set<number>(),
        [communityDropdown],
    );

    const candidateCommunityTags = useMemo(() => {
        if (!communityTagIds.size) return {} as Record<number, ITagWithType[]>;
        return Object.fromEntries(
            Object.entries(candidateAllTags).map(([id, tags]) =>
                [id, tags.filter(t => communityTagIds.has(t.id!))]
            )
        ) as Record<number, ITagWithType[]>;
    }, [candidateAllTags, communityTagIds]);

    const candidateCommunityTagIdSets = useMemo(() =>
            Object.fromEntries(
                Object.entries(candidateCommunityTags).map(([id, tags]) =>
                    [id, new Set(tags.map(t => t.id!))]
                )
            ) as Record<number, Set<number>>,
        [candidateCommunityTags],
    );

    // ── Community tag selection ───────────────────────────────────────────────

    const handleCommunityTagChange = async (tag: ITagWithType | null) => {
        if (!tag) {
            // Clear tag mode: keep kernel entries but clear tagSources indicators
            setCommunityTag(null);
            setCommunityDropdown(null);
            return;
        }

        setTagTransitionLoading(true);
        try {
            const resp: TagKernelResponse = await fetchTagKernelAccounts(tag.id!);
            if (kernelEntries.length === 0) {
                // No existing kernel — set directly without warning
                setCommunityTag(tag);
                setCommunityDropdown(resp.dropdown);
                const newEntries: KernelEntry[] = resp.accounts.map(a => ({
                    account: tagKernelAccountToSearchResult(a),
                    manuallyAdded: false,
                    tagSources: a.applied_tags,
                }));
                setKernelEntries(newEntries);
            } else {
                // Kernel already populated — ask for confirmation
                setTagTransitionPending({
                    tag,
                    tagKernelAccounts: resp.accounts,
                    dropdown: resp.dropdown,
                });
                setTagTransitionApplyToExisting(false);
            }
        } finally {
            setTagTransitionLoading(false);
        }
    };

    const confirmTagTransition = async () => {
        if (!tagTransitionPending) return;
        const {tag, tagKernelAccounts, dropdown} = tagTransitionPending;

        // Optionally attach the tag to all accounts currently in the kernel
        if (tagTransitionApplyToExisting && kernelIds.length > 0) {
            await batchAnnotate('account', kernelIds, [{id: tag.id!}]);
            // Update tagSources for existing kernel entries
            setKernelEntries(prev => prev.map(e => ({
                ...e,
                tagSources: e.tagSources.some(t => t.id === tag.id)
                    ? e.tagSources
                    : [...e.tagSources, tag],
            })));
        }

        // Add tag-based accounts not already in kernel
        const newEntries: KernelEntry[] = tagKernelAccounts
            .filter(a => !kernelIdSet.has(a.id))
            .map(a => ({
                account: tagKernelAccountToSearchResult(a),
                manuallyAdded: false,
                tagSources: a.applied_tags,
            }));
        setKernelEntries(prev => [...prev, ...newEntries]);

        setCommunityTag(tag);
        setCommunityDropdown(dropdown);
        setTagTransitionPending(null);
    };

    // ── Kernel management ─────────────────────────────────────────────────────

    const addToKernel = (result: SearchResult) => {
        if (kernelIdSet.has(result.id)) return;
        const urlSuffix = result.metadata?.url_suffix as string | null | undefined;
        const displayName = result.metadata?.display_name as string | null | undefined;
        const title = displayName
            ? `${urlSuffix} (${displayName})`
            : (urlSuffix ?? result.title);
        setKernelEntries(prev => [...prev, {
            account: {...result, title},
            manuallyAdded: true,
            tagSources: [],
        }]);
    };

    const removeFromKernel = (id: number) => {
        setKernelEntries(prev => prev.filter(e => e.account.id !== id));
    };

    // Toggle a community tag on a kernel entry
    const handleKernelTagToggle = async (entry: KernelEntry, tag: ITagWithType) => {
        const isAssigned = entry.tagSources.some(t => t.id === tag.id);
        if (isAssigned) {
            // Remove tag from account
            await removeAccountTag(entry.account.id, tag.id!);
            const newSources = entry.tagSources.filter(t => t.id !== tag.id);
            setKernelEntries(prev => prev.map(e =>
                e.account.id === entry.account.id ? {...e, tagSources: newSources} : e
            ));
            if (newSources.length === 0 && !entry.manuallyAdded) {
                setPendingKernelRemoval(entry);
            }
        } else {
            setPendingTagAssignment({
                accountTitle: entry.account.title,
                tagName: tag.name,
                onConfirm: async (evidence) => {
                    const notes = evidence.trim() ? `Evidence in support of assignment: ${evidence.trim()}` : null;
                    await batchAnnotate('account', [entry.account.id], [{id: tag.id!, notes}]);
                    setKernelEntries(prev => prev.map(e => {
                        if (e.account.id !== entry.account.id) return e;
                        return {...e, tagSources: [...e.tagSources, tag]};
                    }));
                },
            });
            setEvidenceText('');
        }
    };

    // ── Candidates ────────────────────────────────────────────────────────────

    const runAnalysis = async () => {
        setIsComputing(true);
        // Invalidate cached tag distributions — scores (and thus the relevant
        // candidates) may have changed for this new run.
        setCandidateTagDistributions({});
        setLoadingTagDistributions({});
        try {
            const resp: CommunityCandidatesResponse = await fetchCommunityCandidates(
                kernelIds, excludedIds, weights
            );
            setCandidates(resp.candidates);
            setHasRun(true);

            // In tag mode, bulk-fetch community tags for all returned candidates
            if (communityTag && resp.candidates.length > 0) {
                const allTags = await fetchTagsForSearchResults('accounts', resp.candidates.map(c => c.id));
                setCandidateAllTags(allTags);
            } else {
                setCandidateAllTags({});
            }
        } finally {
            setIsComputing(false);
        }
    };

    const addCandidateToKernel = (candidate: CandidateAccount) => {
        if (kernelIdSet.has(candidate.id)) return;
        const tagSources: ITagWithType[] = [];
        setKernelEntries(prev => [...prev, {
            account: {
                id: candidate.id,
                page: 'account',
                title: candidateTitle(candidate),
                details: candidate.bio ?? undefined,
                thumbnails: candidate.thumbnails,
                metadata: {media_count: candidate.media_count, url_suffix: candidate.url_suffix, display_name: candidate.display_name},
            },
            manuallyAdded: true,
            tagSources,
        }]);
        setCandidates(prev => prev.filter(c => c.id !== candidate.id));
    };

    // Toggle a community tag on a candidate account
    const handleCandidateTagToggle = async (candidate: CandidateAccount, tag: ITagWithType) => {
        const currentTags = candidateAllTags[candidate.id] ?? [];
        const isAssigned = currentTags.some(t => t.id === tag.id);

        if (isAssigned) {
            await removeAccountTag(candidate.id, tag.id!);
            setCandidateAllTags(prev => ({
                ...prev,
                [candidate.id]: (prev[candidate.id] ?? []).filter(t => t.id !== tag.id),
            }));
        } else {
            const newTagEntry = communityDropdown?.tags.find(t => t.id === tag.id) ?? tag;
            setPendingTagAssignment({
                accountTitle: candidateTitle(candidate),
                tagName: tag.name,
                onConfirm: async (evidence) => {
                    const notes = evidence.trim() ? `Evidence in support of assignment: ${evidence.trim()}` : null;
                    await batchAnnotate('account', [candidate.id], [{id: tag.id!, notes}]);
                    setCandidateAllTags(prev => ({
                        ...prev,
                        [candidate.id]: [...(prev[candidate.id] ?? []), newTagEntry],
                    }));
                    const tagSources = [newTagEntry, ...(candidateCommunityTags[candidate.id] ?? []).filter(t => t.id !== tag.id)];
                    if (!kernelIdSet.has(candidate.id)) {
                        setKernelEntries(prev => [...prev, {
                            account: {
                                id: candidate.id,
                                page: 'account',
                                title: candidateTitle(candidate),
                                details: candidate.bio ?? undefined,
                                thumbnails: candidate.thumbnails,
                                metadata: {media_count: candidate.media_count, url_suffix: candidate.url_suffix, display_name: candidate.display_name},
                            },
                            manuallyAdded: false,
                            tagSources,
                        }]);
                        setCandidates(prev => prev.filter(c => c.id !== candidate.id));
                    }
                },
            });
            setEvidenceText('');
        }
    };

    const excludeCandidate = (candidate: CandidateAccount) => {
        setExcludedAccounts(prev => [...prev, candidate]);
    };

    const restoreCandidate = (id: number) => {
        setExcludedAccounts(prev => prev.filter(a => a.id !== id));
    };

    const autoRemoveVerified = () => {
        setExcludedAccounts(prev => [...prev, ...visibleCandidates.filter(c => c.is_verified === true)]);
    };

    // ── Export / import ───────────────────────────────────────────────────────

    const copyKernelAsCsv = async () => {
        const escapeCell = (v: string) =>
            /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
        const rows: string[] = ['url,tags'];
        let skipped = 0;
        for (const entry of kernelEntries) {
            const suffix = entry.account.metadata?.url_suffix as string | null | undefined;
            if (!suffix) {
                skipped++;
                continue;
            }
            const url = `https://www.instagram.com/${suffix}/`;
            const tags = entry.tagSources.map(t => t.name).join(';');
            rows.push(`${escapeCell(url)},${escapeCell(tags)}`);
        }
        const csv = rows.join('\n');
        try {
            await navigator.clipboard.writeText(csv);
            const copied = rows.length - 1;
            const suffix = skipped > 0 ? ` (${skipped} skipped — no url_suffix)` : '';
            setCopyFeedback({
                severity: 'success',
                message: `Copied ${copied} row${copied === 1 ? '' : 's'} to clipboard${suffix}`,
            });
        } catch (err) {
            setCopyFeedback({
                severity: 'error',
                message: `Failed to copy: ${err instanceof Error ? err.message : String(err)}`,
            });
        }
    };

    const exportState = () => {
        const state: CommunityStateExport = {
            version: 1,
            community_tag: communityTag,
            community_dropdown: communityDropdown,
            kernel: kernelEntries.map(({account, manuallyAdded, tagSources}) => ({
                account: stripThumbnails(account),
                manuallyAdded,
                tagSources,
            })),
            weights,
            excluded: excludedAccounts.map(stripThumbnails),
        };
        const datePart = new Date().toISOString().slice(0, 10);
        // Sanitize the tag name into a filesystem-safe slug (drop punctuation
        // like . and , that would produce an illegal/misleading filename).
        const tagSlug = communityTag
            ? communityTag.name
                .replace(/[^a-zA-Z0-9-_ ]/g, '')
                .trim()
                .replace(/\s+/g, '-')
            : '';
        const fileName = tagSlug
            ? `community-${tagSlug}-${datePart}.json`
            : `community-${datePart}.json`;
        downloadTextFile(
            JSON.stringify(state, null, 2),
            fileName,
            'application/json',
        );
    };

    const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        e.target.value = '';
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                const parsed = JSON.parse(ev.target?.result as string);
                if (!isCommunityStateExport(parsed)) {
                    setImportError('Invalid state file — missing required fields or wrong version.');
                    return;
                }
                setCommunityTag(parsed.community_tag);
                setCommunityDropdown(parsed.community_dropdown);
                setKernelEntries(parsed.kernel.map(e => ({
                    account: stripThumbnails(e.account),
                    manuallyAdded: e.manuallyAdded,
                    tagSources: e.tagSources,
                })));
                setWeights({...DEFAULT_TIE_WEIGHTS, ...parsed.weights});
                setExcludedAccounts(parsed.excluded.map(stripThumbnails));
                setCandidates([]);
                setCandidateAllTags({});
                setHasRun(false);
            } catch {
                setImportError('Could not parse file — make sure it is a valid JSON export.');
            }
        };
        reader.readAsText(file);
    };

    // ── Community tag selector label ──────────────────────────────────────────

    const communityTagLabel = communityTag
        ? `Community Tag: ${communityTag.name}`
        : kernelEntries.length === 0
            ? 'Base community on a tag (optional)'
            : 'Attach a tag to this community';

    // ── Render ────────────────────────────────────────────────────────────────

    return (
        <div className="page-wrap">
            <TopNavBar>Community Detection</TopNavBar>
            <div className="page-content content-wrap">

                {/* ── Hidden file input for import ─────────────────────────── */}
                <input
                    type="file"
                    accept=".json"
                    style={{display: 'none'}}
                    ref={fileInputRef}
                    onChange={handleImportFile}
                />

                {/* ── Export / import bar ───────────────────────────────────── */}
                <Stack direction="row" justifyContent="flex-end" gap={1} sx={{mb: 1.5}}>
                    <Tooltip title="Load a previously exported state file">
                        <Button
                            size="small"
                            variant="outlined"
                            startIcon={<FileUploadOutlinedIcon/>}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            Import state
                        </Button>
                    </Tooltip>
                    <Tooltip title="Save current kernel, weights and exclusions to a JSON file">
                        <Button
                            size="small"
                            variant="outlined"
                            startIcon={<FileDownloadOutlinedIcon/>}
                            onClick={exportState}
                        >
                            Export state
                        </Button>
                    </Tooltip>
                </Stack>

                {/* ── Import error snackbar ─────────────────────────────────── */}
                <Snackbar
                    open={importError !== null}
                    autoHideDuration={5000}
                    onClose={() => setImportError(null)}
                    anchorOrigin={{vertical: 'bottom', horizontal: 'center'}}
                >
                    <Alert severity="error" onClose={() => setImportError(null)} variant="filled">
                        {importError}
                    </Alert>
                </Snackbar>

                {/* ── Clipboard feedback snackbar ───────────────────────────── */}
                <Snackbar
                    open={copyFeedback !== null}
                    autoHideDuration={3000}
                    onClose={() => setCopyFeedback(null)}
                    anchorOrigin={{vertical: 'bottom', horizontal: 'center'}}
                >
                    <Alert
                        severity={copyFeedback?.severity ?? 'success'}
                        onClose={() => setCopyFeedback(null)}
                        variant="filled"
                    >
                        {copyFeedback?.message}
                    </Alert>
                </Snackbar>

                {/* ── Kernel modal ─────────────────────────────────────────── */}
                <Dialog open={kernelModalOpen} onClose={() => setKernelModalOpen(false)}
                        maxWidth="sm" fullWidth>
                    <DialogTitle sx={{pr: 6}}>
                        Add Accounts to Kernel
                        <IconButton onClick={() => setKernelModalOpen(false)} size="small"
                                    sx={{position: 'absolute', right: 8, top: 8}}>
                            <CloseIcon/>
                        </IconButton>
                    </DialogTitle>
                    <DialogContent dividers sx={{p: 2}}>
                        <SearchPanel
                            query={KERNEL_SEARCH_QUERY}
                            onSearch={() => {
                            }}
                            autoSearch={300}
                            showModeSelector={false}
                            showAdvancedFilters={false}
                            showTaggingMode={false}
                            checkedIds={kernelIdSet}
                            onToggleChecked={(result) => {
                                if (kernelIdSet.has(result.id)) removeFromKernel(result.id);
                                else addToKernel(result);
                            }}
                        />
                    </DialogContent>
                    <DialogActions>
                        <Typography variant="body2" color="text.secondary" sx={{flex: 1, pl: 1}}>
                            {kernelEntries.length} account{kernelEntries.length !== 1 ? 's' : ''} in kernel
                        </Typography>
                        <Button variant="contained" onClick={() => setKernelModalOpen(false)}>Done</Button>
                    </DialogActions>
                </Dialog>

                {/* ── Evidence prompt for single-account tag assignment ─────── */}
                <Dialog
                    open={pendingTagAssignment !== null}
                    onClose={() => setPendingTagAssignment(null)}
                    maxWidth="sm"
                    fullWidth
                >
                    <DialogTitle>Assign Tag</DialogTitle>
                    <DialogContent dividers>
                        <Stack gap={1.5}>
                            <Typography variant="body2">
                                Assigning <strong>{pendingTagAssignment?.tagName}</strong> to{' '}
                                <strong>{pendingTagAssignment?.accountTitle}</strong>.
                            </Typography>
                            <TextField
                                label="Evidence (explanation / link to evidence)"
                                multiline
                                minRows={2}
                                fullWidth
                                autoFocus
                                value={evidenceText}
                                onChange={e => setEvidenceText(e.target.value)}
                                placeholder="Optional — paste a URL, describe a connection, or leave blank"
                            />
                        </Stack>
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setPendingTagAssignment(null)}>Cancel</Button>
                        <Button
                            variant="contained"
                            onClick={async () => {
                                if (!pendingTagAssignment) return;
                                await pendingTagAssignment.onConfirm(evidenceText);
                                setPendingTagAssignment(null);
                                setEvidenceText('');
                            }}
                        >
                            Assign
                        </Button>
                    </DialogActions>
                </Dialog>

                {/* ── Untagged kernel account removal modal ─────────────────── */}
                <Dialog
                    open={pendingKernelRemoval !== null}
                    onClose={() => setPendingKernelRemoval(null)}
                    maxWidth="sm"
                    fullWidth
                >
                    <DialogTitle>Keep Account in Kernel?</DialogTitle>
                    <DialogContent dividers>
                        <Typography variant="body2">
                            After removing this tag, <strong>{pendingKernelRemoval?.account.title}</strong> will
                            have no community tag justifying its inclusion in the kernel. Should it be removed
                            from the kernel, or kept for analysis?
                        </Typography>
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setPendingKernelRemoval(null)}>Keep in kernel</Button>
                        <Button
                            variant="contained"
                            color="error"
                            onClick={() => {
                                if (!pendingKernelRemoval) return;
                                removeFromKernel(pendingKernelRemoval.account.id);
                                setPendingKernelRemoval(null);
                            }}
                        >
                            Remove from kernel
                        </Button>
                    </DialogActions>
                </Dialog>

                {/* ── Tag transition confirmation modal ─────────────────────── */}
                <Dialog
                    open={tagTransitionPending !== null}
                    onClose={() => setTagTransitionPending(null)}
                    maxWidth="sm"
                    fullWidth
                >
                    <DialogTitle>Switch to Tag Mode?</DialogTitle>
                    <DialogContent dividers>
                        <Stack gap={1.5}>
                            <Typography variant="body2">
                                You selected <strong>{tagTransitionPending?.tag.name}</strong> as the community tag.
                                The following changes will take effect:
                            </Typography>
                            <Box component="ul" sx={{pl: 2.5, m: 0}}>
                                <li>
                                    <Typography variant="body2">
                                        <strong>{tagTransitionPending?.tagKernelAccounts.filter(a => !kernelIdSet.has(a.id)).length ?? 0}</strong> account(s)
                                        tagged with <em>{tagTransitionPending?.tag.name}</em> (or its subtags) will be
                                        added to the kernel.
                                    </Typography>
                                </li>
                            </Box>
                            <FormControlLabel
                                control={
                                    <Checkbox
                                        checked={tagTransitionApplyToExisting}
                                        onChange={e => setTagTransitionApplyToExisting(e.target.checked)}
                                        size="small"
                                    />
                                }
                                label={
                                    <Typography variant="body2">
                                        Also attach the <strong>{tagTransitionPending?.tag.name}</strong> tag
                                        to the {kernelEntries.length} account(s) already in the kernel
                                    </Typography>
                                }
                            />
                        </Stack>
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setTagTransitionPending(null)}>Cancel</Button>
                        <Button variant="contained" onClick={confirmTagTransition}>Confirm</Button>
                    </DialogActions>
                </Dialog>

                <Stack gap={0}>

                    {/* ── Community tag selector ───────────────────────────── */}
                    <Paper variant="outlined" sx={{p: 2.5, borderRadius: 2}}>
                        <Stack direction="row" alignItems="center" gap={1.5}>
                            <Box sx={{flex: 1}}>
                                <TagSelector
                                    selectedTags={communityTag ? [communityTag] : []}
                                    label={communityTagLabel}
                                    onChange={(tags) => handleCommunityTagChange(tags[0] ?? null)}
                                    readOnly={tagTransitionLoading}
                                    single
                                    entity="account"
                                />
                            </Box>
                            {tagTransitionLoading && <CircularProgress size={20}/>}
                            {communityTag && (
                                <Tooltip title="Clear community tag (switch to ad-hoc mode)">
                                    <IconButton
                                        size="small"
                                        onClick={() => handleCommunityTagChange(null)}
                                        sx={{flexShrink: 0}}
                                    >
                                        <CloseIcon fontSize="small"/>
                                    </IconButton>
                                </Tooltip>
                            )}
                        </Stack>
                        {communityTag && (
                            <Typography variant="caption" color="text.secondary" sx={{mt: 0.75, display: 'block'}}>
                                Tag mode active — kernel seeded from accounts tagged
                                with <strong>{communityTag.name}</strong> (and its subtags).
                                Tag assignments are saved to the database.
                            </Typography>
                        )}
                    </Paper>

                    <Box sx={{width: 2, height: 16, bgcolor: 'divider', mx: 'auto'}}/>

                    {/* ── Step 1: Kernel ───────────────────────────────────── */}
                    <Paper variant="outlined" sx={{p: 2.5, borderRadius: 2}}>
                        <SectionHeader
                            step={1}
                            title="Kernel — Seed Accounts"
                            active={kernelEntries.length > 0}
                            action={
                                <Stack direction="row" spacing={1}>
                                    <Tooltip title="Copy kernel as CSV (url, tags)">
                                        <span>
                                            <Button
                                                size="small"
                                                variant="outlined"
                                                startIcon={<ContentCopyIcon/>}
                                                onClick={copyKernelAsCsv}
                                                disabled={kernelEntries.length === 0}
                                                sx={{flexShrink: 0}}
                                            >
                                                Copy to clipboard
                                            </Button>
                                        </span>
                                    </Tooltip>
                                    <Tooltip title="Search and add accounts manually">
                                        <Button
                                            size="small"
                                            variant="contained"
                                            startIcon={<AddIcon/>}
                                            onClick={() => setKernelModalOpen(true)}
                                            sx={{flexShrink: 0}}
                                        >
                                            Add accounts
                                        </Button>
                                    </Tooltip>
                                </Stack>
                            }
                        />

                        {kernelEntries.length > 0 ? (
                            <Stack direction="row" flexWrap="wrap" gap={1}>
                                {kernelEntries.map(entry => (
                                    <KernelAccountPill
                                        key={entry.account.id}
                                        entry={entry}
                                        communityDropdown={communityDropdown}
                                        onRemove={() => removeFromKernel(entry.account.id)}
                                        onTagToggle={(tag) => handleKernelTagToggle(entry, tag)}
                                    />
                                ))}
                            </Stack>
                        ) : (
                            <Box
                                onClick={() => setKernelModalOpen(true)}
                                sx={{
                                    border: '1.5px dashed',
                                    borderColor: 'divider',
                                    borderRadius: 1.5,
                                    p: 2,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 1.5,
                                    cursor: 'pointer',
                                    color: 'text.secondary',
                                    '&:hover': {
                                        borderColor: 'primary.main',
                                        color: 'primary.main',
                                        bgcolor: 'action.hover'
                                    },
                                    transition: 'all 0.15s',
                                }}
                            >
                                <AddIcon sx={{fontSize: '1.1rem', flexShrink: 0}}/>
                                <Typography variant="body2">
                                    Add seed accounts manually, or select a community tag above to seed from a tag
                                </Typography>
                            </Box>
                        )}
                    </Paper>

                    <Box sx={{width: 2, height: 16, bgcolor: 'divider', mx: 'auto'}}/>

                    {/* ── Step 2: Weights ──────────────────────────────────── */}
                    <Paper variant="outlined" sx={{p: 2.5, borderRadius: 2}}>
                        <SectionHeader
                            step={2}
                            title="Tie Weights"
                        />
                        <Stack direction="column" gap={1}>
                            <Typography variant="body2" color="text.secondary" sx={{mt: -0.5}}>
                                Adjust how different interaction types influence the strength of relation between
                                accounts:
                            </Typography>
                            <Stack direction="row" flexWrap="wrap" gap={2} sx={{mt: 0.5}}>
                                {(Object.keys(TIE_LABELS) as (keyof TieWeights)[]).map(tie => (
                                    <NumberField
                                        key={tie}
                                        label={TIE_LABELS[tie]}
                                        value={weights[tie]}
                                        min={0}
                                        step={0.1}
                                        size="small"
                                        onValueChange={v => setWeights(prev => ({...prev, [tie]: v ?? 0}))}
                                        sx={{width: 130}}
                                    />
                                ))}
                            </Stack>
                        </Stack>
                    </Paper>

                    <Box sx={{width: 2, height: 16, bgcolor: 'divider', mx: 'auto'}}/>

                    {/* ── Step 3: Run ──────────────────────────────────────── */}
                    <Paper variant="outlined" sx={{p: 2.5, borderRadius: 2}}>
                        <SectionHeader step={3} title="Run Analysis"/>
                        <Tooltip
                            title={kernelIds.length === 0 ? 'Add at least one account to the kernel first' : ''}
                            disableHoverListener={kernelIds.length > 0}
                        >
                            <span>
                                <Button
                                    variant="contained"
                                    size="large"
                                    disabled={kernelIds.length === 0 || isComputing}
                                    onClick={runAnalysis}
                                    startIcon={
                                        isComputing ?
                                            <CircularProgress size={18} color="inherit"/> :
                                            hasRun ? <AutoModeIcon/> : <AutoAwesomeIcon/>
                                    }
                                    sx={{minWidth: 220}}
                                >
                                    {isComputing ? 'Analyzing…' : (hasRun ? 'Re-run Detection' : 'Run Community Detection')}
                                </Button>
                            </span>
                        </Tooltip>
                    </Paper>

                    {/* ── Candidates ───────────────────────────────────────── */}
                    {hasRun && (
                        <>
                            <Box sx={{display: 'flex', justifyContent: 'center'}}>
                                <Box sx={{width: '2px', height: 16, bgcolor: 'divider'}}/>
                            </Box>
                            <Paper variant="outlined" sx={{p: 2.5, borderRadius: 2}}>
                                <Stack direction="row" justifyContent="space-between" alignItems="center"
                                       sx={{mb: 1.5}}>
                                    <Typography variant="subtitle1" sx={{fontWeight: 600}}>
                                        Top Candidates
                                        {visibleCandidates.length > 0 && (
                                            <Typography component="span" variant="body2" color="text.secondary"
                                                        sx={{ml: 1}}>
                                                {visibleCandidates.length} result{visibleCandidates.length !== 1 ? 's' : ''}
                                            </Typography>
                                        )}
                                    </Typography>
                                    <Tooltip
                                        title={hasVerifiedVisible ? 'Remove all verified accounts from candidates list to screen out celebs and brands' : 'No verified accounts in current results'}>
                                        <span>
                                            <Button variant="outlined" size="small" disabled={!hasVerifiedVisible}
                                                    onClick={autoRemoveVerified} sx={{flexShrink: 0}}>
                                                Remove Verified
                                            </Button>
                                        </span>
                                    </Tooltip>
                                </Stack>

                                {visibleCandidates.length === 0 ? (
                                    <Typography color="text.secondary" variant="body2">
                                        {candidates.length > 0
                                            ? 'All candidates have been excluded.'
                                            : 'No candidates found. Try expanding the kernel or adjusting weights.'}
                                    </Typography>
                                ) : (
                                    <Stack spacing={0} divider={<Divider/>}>
                                        {visibleCandidates.map(candidate => (
                                            <CandidateCard
                                                key={candidate.id}
                                                candidate={candidate}
                                                communityDropdown={communityDropdown}
                                                assignedCommunityTagIds={candidateCommunityTagIdSets[candidate.id] ?? EMPTY_ID_SET}
                                                onAddToKernel={() => addCandidateToKernel(candidate)}
                                                onExclude={() => excludeCandidate(candidate)}
                                                onTagToggle={(tag) => handleCandidateTagToggle(candidate, tag)}
                                                tagDistribution={candidateTagDistributions[candidate.id]}
                                                tagDistributionLoading={!!loadingTagDistributions[candidate.id]}
                                                onTagDistributionOpen={() => loadCandidateTagDistribution(candidate.id)}
                                            />
                                        ))}
                                    </Stack>
                                )}
                            </Paper>
                        </>
                    )}

                    {/* ── Excluded accounts ────────────────────────────────── */}
                    {excludedAccounts.length > 0 && (
                        <>
                            <Box sx={{height: 8}}/>
                            <Box>
                                <Button
                                    variant="text" size="small"
                                    onClick={() => setExcludedOpen(p => !p)}
                                    endIcon={<ExpandMoreIcon sx={{
                                        transform: excludedOpen ? 'rotate(180deg)' : 'none',
                                        transition: 'transform 0.2s'
                                    }}/>}
                                    sx={{color: 'text.secondary'}}
                                >
                                    Excluded ({excludedAccounts.length})
                                </Button>
                                <Collapse in={excludedOpen} unmountOnExit>
                                    <Box sx={{display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 0.5, pl: 0.5}}>
                                        {excludedAccounts.map(acct => (
                                            <Chip
                                                key={acct.id}
                                                component="a"
                                                label={candidateTitle(acct)}
                                                onDelete={() => restoreCandidate(acct.id)}
                                                deleteIcon={<Tooltip title="Restore"><UndoIcon/></Tooltip>}
                                                clickable
                                                sx={{fontSize: '0.75rem'}}
                                            />
                                        ))}
                                    </Box>
                                </Collapse>
                            </Box>
                        </>
                    )}

                </Stack>
            </div>
        </div>
    );
}
