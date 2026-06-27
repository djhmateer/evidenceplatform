import React, {useState, useRef, useEffect} from 'react';
import {Box, Button, Checkbox, Chip, Collapse, Fade, Stack, Typography, useMediaQuery} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import dayjs from 'dayjs';
import {SearchResult} from '../../services/DataFetcher';
import {ITagWithType} from '../../types/tags';
import {anchor_local_static_files} from '../../services/server';
import {SearchResultsProps} from './types';

const MediaHoverOverlay = React.forwardRef<HTMLDivElement, {
    accountName: string | null;
    pubDate: string | null;
    tags: ITagWithType[];
}>(function MediaHoverOverlay({accountName, pubDate, tags}, ref) {
    return (
        <Box
            ref={ref}
            sx={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                width: '100%',
                boxSizing: 'border-box',
                backgroundColor: 'rgba(0,0,0,0.7)',
                color: '#fff',
                p: 1,
                zIndex: 1,
            }}
        >
            {accountName && (
                <Typography variant="caption" display="block" noWrap>
                    {accountName}
                </Typography>
            )}
            {pubDate && (
                <Typography variant="caption" display="block" noWrap>
                    {pubDate}
                </Typography>
            )}
            {tags.length > 0 && (
                <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{mt: 0.5}}>
                    {tags.map(t => (
                        <Chip
                            key={t.id}
                            label={t.name}
                            size="small"
                            variant="outlined"
                            sx={{
                                fontSize: '0.65rem', height: 18, color: '#fff',
                                borderColor: 'rgba(255,255,255,0.5)',
                                '& .MuiChip-label': {px: 0.75},
                            }}
                        />
                    ))}
                </Stack>
            )}
        </Box>
    );
});

interface CellProps {
    result: SearchResult;
    tags: ITagWithType[];
    selected: boolean;
    onToggleSelected?: (id: number) => void;
    largeIcons?: boolean;
}

function MediaSearchResultCell({result, tags, selected, onToggleSelected, largeIcons}: CellProps) {
    const isMobile = useMediaQuery('(max-width: 768px)');
    // Mobile, and desktop large-icon mode, load full-res assets automatically on scroll.
    const autoLoadFullRes = isMobile || !!largeIcons;
    const [hovered, setHovered] = useState(false);
    const [everHovered, setEverHovered] = useState(false);
    const videoRef = useRef<HTMLVideoElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const thumbnail = result.thumbnails?.[0];
    const fullRes = result.thumbnails?.[1];
    const isVideo = result.metadata?.media_type === 'video';
    // A media-part result links back to its parent media page with ?part_id=…, which opens the
    // focus modal. Its thumbnail is already cropped, so show it whole (contain) rather than re-cropping.
    const partId = result.metadata?.part_id as number | undefined;
    const href = partId != null
        ? `/media/${result.id}?part_id=${partId}`
        : `/${result.page}/${result.id}`;

    const pubDate = result.metadata?.publication_date
        ? dayjs(result.metadata.publication_date).format('YYYY-MM-DD')
        : null;
    const accountName = result.metadata?.account_display_name
        || (result.metadata?.account_url
            ? result.metadata.account_url.replace(/\/$/, '').split('/').pop()
            : null);

    const fullResSrc = fullRes ? anchor_local_static_files(fullRes.src) || undefined : undefined;

    useEffect(() => {
        if (!videoRef.current) return;
        if (hovered) {
            videoRef.current.play().catch(() => {});
        } else {
            videoRef.current.pause();
        }
    }, [hovered]);

    useEffect(() => {
        if (!autoLoadFullRes) return;
        const el = containerRef.current;
        if (!el) return;
        const observer = new IntersectionObserver(
            ([entry]) => { if (entry.isIntersecting) { setEverHovered(true); observer.disconnect(); } },
            {threshold: 0.1},
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [autoLoadFullRes]);

    return (
        <Box
            ref={containerRef}
            sx={{position: 'relative', cursor: onToggleSelected ? 'pointer' : undefined}}
            onClick={onToggleSelected ? (e) => { e.preventDefault(); onToggleSelected(result.id); } : undefined}
        >
            {onToggleSelected && <>
                <Box sx={{
                    position: 'absolute', top: '12px', left: '12px', zIndex: 1,
                    width: '12px', height: '12px', borderRadius: '2px',
                    backgroundColor: 'rgba(0,0,0,0.55)', pointerEvents: 'none',
                }} />
                <Checkbox
                    checked={selected}
                    onClick={e => {
                        e.preventDefault();
                        e.stopPropagation();
                        onToggleSelected(result.id);
                    }}
                    sx={{
                        position: 'absolute', top: 4, left: 4, zIndex: 2,
                        color: 'white', p: 0.5,
                        '&.Mui-checked': {color: 'white'},
                    }}
                    size="small"
                />
            </>}
            <a href={href} style={{textDecoration: 'none'}}>
                <Box
                    sx={{
                        position: 'relative',
                        aspectRatio: '1',
                        backgroundColor: '#111',
                        overflow: 'hidden',
                        cursor: 'pointer',
                    }}
                    onMouseEnter={() => { setHovered(true); setEverHovered(true); }}
                    onMouseLeave={() => setHovered(false)}
                >
                    {partId != null && (
                        <Chip
                            label="Segment"
                            size="small"
                            sx={{
                                position: 'absolute', top: 6, right: 6, zIndex: 2,
                                height: 18, fontSize: '0.62rem', color: '#fff',
                                backgroundColor: 'rgba(0,0,0,0.65)',
                                '& .MuiChip-label': {px: 0.75},
                            }}
                        />
                    )}
                    {thumbnail && (
                        <img
                            src={anchor_local_static_files(thumbnail.src) || undefined}
                            alt=""
                            style={{width: '100%', height: '100%', objectFit: partId != null ? 'contain' : 'cover', display: 'block'}}
                        />
                    )}
                    {everHovered && fullResSrc && (
                        isVideo ? (
                            <video
                                ref={videoRef}
                                src={fullResSrc}
                                muted
                                loop
                                playsInline
                                style={{
                                    position: 'absolute', inset: 0,
                                    width: '100%', height: '100%', objectFit: 'cover',
                                }}
                            />
                        ) : (
                            <img
                                src={fullResSrc}
                                alt=""
                                style={{
                                    position: 'absolute', inset: 0,
                                    width: '100%', height: '100%', objectFit: 'cover',
                                }}
                            />
                        )
                    )}
                    <Fade in={hovered} timeout={300}>
                        <MediaHoverOverlay accountName={accountName} pubDate={pubDate} tags={tags}/>
                    </Fade>
                </Box>
            </a>
        </Box>
    );
}

// Reverse-image-search results carry a Hamming `match_distance` (0..64, lower = better). pHash
// survives recompression/resize/labels at small distances, while the server's generous 18-bit cut
// also lets weaker, degraded matches through. We split at the doc's near-duplicate boundary
// (01-perceptual-hash-search.md): <=10 is a "good" match shown by default; 11..18 is the weak band,
// collapsed under an expander so it doesn't bury the strong hits.
const GOOD_MATCH_MAX_DISTANCE = 15;

function MediaResultsGrid({results, tagsMap, selectedIds, onToggleSelected, largeIcons}: SearchResultsProps) {
    return (
        <Box
            sx={{
                display: 'grid',
                gridTemplateColumns: `repeat(auto-fill, minmax(${largeIcons ? 350 : 150}px, 1fr))`,
                gap: 1,
            }}
        >
            {results.map((result) => (
                <MediaSearchResultCell
                    key={`${result.id}-${result.metadata?.part_id ?? 'm'}`}
                    result={result}
                    // tagsMap is keyed by parent media id; a segment's own tags aren't here, so don't
                    // mislabel the parent media's tags as the segment's (the focus modal shows them).
                    tags={result.metadata?.part_id != null ? [] : (tagsMap?.[result.id] ?? [])}
                    selected={selectedIds?.has(result.id) ?? false}
                    onToggleSelected={onToggleSelected}
                    largeIcons={largeIcons}
                />
            ))}
        </Box>
    );
}

export default function MediaSearchResults(props: SearchResultsProps) {
    const {results} = props;
    const [showAdditional, setShowAdditional] = useState(false);

    // Reset the expander whenever a new result set arrives (e.g. a fresh image search), so a previous
    // expansion doesn't carry over and reveal a different query's weak matches by default.
    const resultsKey = results.map(r => r.id).join(',');
    useEffect(() => { setShowAdditional(false); }, [resultsKey]);

    if (results.length === 0) {
        return <Box>No results found.</Box>;
    }

    // Only reverse-image-search results carry match_distance; plain media search renders unsegmented.
    const isImageSearch = results.some(r => typeof r.metadata?.match_distance === 'number');
    if (!isImageSearch) {
        return <MediaResultsGrid {...props} />;
    }

    const distOf = (r: typeof results[number]) =>
        typeof r.metadata?.match_distance === 'number' ? r.metadata.match_distance : Infinity;
    const good = results.filter(r => distOf(r) <= GOOD_MATCH_MAX_DISTANCE);
    const additional = results.filter(r => distOf(r) > GOOD_MATCH_MAX_DISTANCE);

    // No strong matches: surface the weak band directly (no point hiding everything behind an
    // expander when there's nothing else to show), with a note that the matches are low-similarity.
    if (good.length === 0) {
        return (
            <Stack gap={1}>
                <Typography variant="body2" color="text.secondary">
                    No strong matches — showing {additional.length} lower-similarity{' '}
                    {additional.length === 1 ? 'match' : 'matches'}.
                </Typography>
                <MediaResultsGrid {...props} results={additional} />
            </Stack>
        );
    }

    return (
        <Stack gap={1}>
            <MediaResultsGrid {...props} results={good} />
            {additional.length > 0 && (
                <>
                    <Button
                        onClick={() => setShowAdditional(s => !s)}
                        startIcon={showAdditional ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                        sx={{alignSelf: 'flex-start', textTransform: 'none', mt: 0.5}}
                        color="inherit"
                    >
                        {showAdditional
                            ? 'Hide lower-similarity matches'
                            : `Show ${additional.length} more lower-similarity ${additional.length === 1 ? 'match' : 'matches'}`}
                    </Button>
                    <Collapse in={showAdditional} timeout="auto" unmountOnExit>
                        <MediaResultsGrid {...props} results={additional} />
                    </Collapse>
                </>
            )}
        </Stack>
    );
}
