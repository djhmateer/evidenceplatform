import React, {useState} from 'react';
import {Badge, Box, Button, Popover, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography} from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import NumberField from '../MUINumberField/NumberField';

// Display-only filters for the community-detection account lists. These visually
// hide non-matching entries (they never remove items). A single value drives the
// controls shown in both the kernel and candidates section headers.

export interface DisplayFilters {
    relationsMode: 'all' | 'over' | 'under';
    relationsThreshold: number;
    postsMode: 'all' | 'has' | 'none';
}

export const DEFAULT_DISPLAY_FILTERS: DisplayFilters = {
    relationsMode: 'all',
    relationsThreshold: 0,
    postsMode: 'all',
};

export function isDisplayFilterActive(f: DisplayFilters): boolean {
    return f.relationsMode !== 'all' || f.postsMode !== 'all';
}

interface AccountDisplayFiltersProps {
    value: DisplayFilters;
    onChange: (next: DisplayFilters) => void;
}

export default function AccountDisplayFilters({value, onChange}: AccountDisplayFiltersProps) {
    const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
    const active = isDisplayFilterActive(value);

    return (
        <>
            <Tooltip title="Filter visible accounts by scraping state">
                <Badge color="primary" variant="dot" invisible={!active} overlap="circular">
                    <Button
                        size="small"
                        variant={active ? 'contained' : 'outlined'}
                        startIcon={<FilterListIcon/>}
                        onClick={e => setAnchorEl(e.currentTarget)}
                        sx={{flexShrink: 0}}
                    >
                        Filters
                    </Button>
                </Badge>
            </Tooltip>
            <Popover
                open={anchorEl !== null}
                anchorEl={anchorEl}
                onClose={() => setAnchorEl(null)}
                anchorOrigin={{vertical: 'bottom', horizontal: 'right'}}
                transformOrigin={{vertical: 'top', horizontal: 'right'}}
            >
                <Stack gap={2} sx={{p: 2, minWidth: 280}}>
                    {/* Account relations (followers + following) */}
                    <Box>
                        <Typography variant="caption" sx={{
                            color: 'text.disabled', fontSize: '0.65rem',
                            letterSpacing: '0.08em', textTransform: 'uppercase',
                        }}>
                            Account relations (followers + following)
                        </Typography>
                        <Stack direction="row" gap={1} alignItems="center" sx={{mt: 0.75}}>
                            <ToggleButtonGroup
                                size="small"
                                exclusive
                                value={value.relationsMode}
                                onChange={(_, v) => {
                                    if (v !== null) onChange({...value, relationsMode: v});
                                }}
                            >
                                <ToggleButton value="all">All</ToggleButton>
                                <ToggleButton value="over">&gt; N</ToggleButton>
                                <ToggleButton value="under">&lt; N</ToggleButton>
                            </ToggleButtonGroup>
                            <NumberField
                                label="N"
                                size="small"
                                min={0}
                                step={1}
                                value={value.relationsThreshold}
                                disabled={value.relationsMode === 'all'}
                                onValueChange={v => onChange({...value, relationsThreshold: v ?? 0})}
                                sx={{width: 90}}
                            />
                        </Stack>
                    </Box>

                    {/* Posts */}
                    <Box>
                        <Typography variant="caption" sx={{
                            color: 'text.disabled', fontSize: '0.65rem',
                            letterSpacing: '0.08em', textTransform: 'uppercase',
                        }}>
                            Posts
                        </Typography>
                        <Box sx={{mt: 0.75}}>
                            <ToggleButtonGroup
                                size="small"
                                exclusive
                                value={value.postsMode}
                                onChange={(_, v) => {
                                    if (v !== null) onChange({...value, postsMode: v});
                                }}
                            >
                                <ToggleButton value="all">All</ToggleButton>
                                <ToggleButton value="has">Has posts</ToggleButton>
                                <ToggleButton value="none">No posts</ToggleButton>
                            </ToggleButtonGroup>
                        </Box>
                    </Box>

                    {active && (
                        <Button size="small" onClick={() => onChange(DEFAULT_DISPLAY_FILTERS)}>
                            Clear filters
                        </Button>
                    )}
                </Stack>
            </Popover>
        </>
    );
}
