import React from 'react';
import {Box, Chip, CircularProgress, Stack, Tooltip, Typography} from '@mui/material';
import PeopleAltOutlinedIcon from '@mui/icons-material/PeopleAltOutlined';
import ArticleOutlinedIcon from '@mui/icons-material/ArticleOutlined';
import {SearchResultThumbnails} from '../SearchResults/SearchResultParts';
import RelatedTagDistributionTable from '../Tags/RelatedTagDistributionTable';
import {Thumbnail} from '../../services/DataFetcher';
import {ITagStat} from '../../types/tags';

// Rich rectangular account block shared by the Community Detection page's
// candidates list and the kernel "expanded view". It renders a score column
// (with a lazily-loaded tag-distribution tooltip), a content column (title,
// verified chip, bio, media thumbnails) and a caller-supplied actions column.

export interface AccountBlockProps {
    id: number;
    title: string;
    bio?: string | null;
    isVerified?: boolean | null;
    thumbnails: Thumbnail[];
    mediaCount: number;
    followerCount: number;
    followingCount: number;
    postCount: number;
    score: number;
    tagDistribution?: ITagStat[];
    tagDistributionLoading: boolean;
    onTagDistributionOpen: () => void;
    actions: React.ReactNode;
}

export default function AccountBlock({
                                         id,
                                         title,
                                         bio,
                                         isVerified,
                                         thumbnails,
                                         mediaCount,
                                         followerCount,
                                         followingCount,
                                         postCount,
                                         score,
                                         tagDistribution,
                                         tagDistributionLoading,
                                         onTagDistributionOpen,
                                         actions,
                                     }: AccountBlockProps) {
    const scoreLabel = score % 1 === 0 ? score.toString() : score.toFixed(2);
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
                        {scoreLabel}
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
                    <a href={`/account/${id}`} target="_blank" rel="noopener noreferrer"
                       style={{textDecoration: 'none', color: 'inherit'}}>
                        <Typography variant="subtitle1" sx={{
                            fontWeight: 600,
                            wordBreak: 'break-word',
                            '&:hover': {textDecoration: 'underline'}
                        }}>
                            {title}
                        </Typography>
                    </a>
                    {isVerified && (
                        <Chip label="Verified" size="small" color="info" variant="outlined"
                              sx={{height: 18, '& .MuiChip-label': {px: 0.75, fontSize: '0.6rem'}}}/>
                    )}
                </Stack>
                {/* Scraping-state indicator: scraped relations (real follows only) and post count */}
                <Tooltip
                    arrow
                    placement="top-start"
                    title="Scraped followers / following (excludes suggested) · posts"
                >
                    <Stack direction="row" gap={1.5} alignItems="center" sx={{mt: 0.5, cursor: 'help'}}>
                        <Stack direction="row" gap={0.5} alignItems="center" sx={{color: 'text.secondary'}}>
                            <PeopleAltOutlinedIcon sx={{fontSize: '0.95rem'}}/>
                            <Typography variant="caption" sx={{fontSize: '0.7rem', lineHeight: 1}}>
                                {followerCount.toLocaleString()} / {followingCount.toLocaleString()}
                            </Typography>
                        </Stack>
                        <Stack direction="row" gap={0.5} alignItems="center" sx={{color: 'text.secondary'}}>
                            <ArticleOutlinedIcon sx={{fontSize: '0.95rem'}}/>
                            <Typography variant="caption" sx={{fontSize: '0.7rem', lineHeight: 1}}>
                                {postCount.toLocaleString()} post{postCount === 1 ? '' : 's'}
                            </Typography>
                        </Stack>
                    </Stack>
                </Tooltip>
                {bio && (
                    <Typography variant="body2" color="text.secondary" sx={{mt: 0.25, fontSize: '0.8125rem'}}>
                        {bio}
                    </Typography>
                )}
                <SearchResultThumbnails thumbnails={thumbnails} totalCount={mediaCount}/>
            </Box>

            {/* Actions */}
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
                {actions}
            </Box>
        </Stack>
    );
}
