import React, {useState, useRef, useEffect} from 'react';
import {Box, Checkbox, Chip, Fade, Stack, Typography, useMediaQuery} from '@mui/material';
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
            <a href={`/${result.page}/${result.id}`} style={{textDecoration: 'none'}}>
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
                    {thumbnail && (
                        <img
                            src={anchor_local_static_files(thumbnail.src) || undefined}
                            alt=""
                            style={{width: '100%', height: '100%', objectFit: 'cover', display: 'block'}}
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

export default function MediaSearchResults({results, tagsMap, selectedIds, onToggleSelected, largeIcons}: SearchResultsProps) {
    if (results.length === 0) {
        return <Box>No results found.</Box>;
    }
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
                    key={result.id}
                    result={result}
                    tags={tagsMap?.[result.id] ?? []}
                    selected={selectedIds?.has(result.id) ?? false}
                    onToggleSelected={onToggleSelected}
                    largeIcons={largeIcons}
                />
            ))}
        </Box>
    );
}
