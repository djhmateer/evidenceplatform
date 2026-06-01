import React, {useEffect, useMemo, useState} from 'react';
import {
    Badge, Box, Checkbox, Chip, IconButton, ListItemText, Menu, MenuItem, Stack, ToggleButton,
    ToggleButtonGroup, Tooltip, Typography
} from "@mui/material";
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import {IQuickAccessData, ITagWithType} from "../../types/tags";
import {lookupTags} from "../../services/DataFetcher";
import {fetchQuickAccessData} from "../../services/TagManagementService";
import {E_ENTITY_TYPES} from "../../types/entities";
import {SCOPE_OPTIONS, resolveScopes} from "../../lib/tagScopes";
import Autocomplete from "@mui/material/Autocomplete";
import TextField from "@mui/material/TextField";
import QuickAccessBar from "./QuickAccessBar";

// Human label for each scope, phrased relative to the searched entity.
const SCOPE_LABELS: Partial<Record<E_ENTITY_TYPES, Partial<Record<E_ENTITY_TYPES, string>>>> = {
    media:   {media: "This media", post: "Parent post", account: "Account", media_part: "Media parts / clips"},
    post:    {post: "This post", media: "Media in post", account: "Account", media_part: "Media parts / clips"},
    account: {account: "This account", post: "Posts", media: "Media", media_part: "Media parts / clips"},
};

interface IProps {
    tagIds: number[];
    tagFilterMode: "any" | "all";
    selectedTagObjects: ITagWithType[];
    tagScopes: E_ENTITY_TYPES[];
    onChange: (tagIds: number[], mode: "any" | "all", tagObjects: ITagWithType[], scopes: E_ENTITY_TYPES[]) => void;
    entity?: E_ENTITY_TYPES;
}

export default function TagFilterBar({tagIds, tagFilterMode, selectedTagObjects, tagScopes, onChange, entity}: IProps) {
    const [inputValue, setInputValue] = useState('');
    const [options, setOptions] = useState<ITagWithType[]>([]);
    const [fetching, setFetching] = useState(false);
    const [quickAccessData, setQuickAccessData] = useState<IQuickAccessData>({individual_tags: [], type_dropdowns: []});
    const [scopeMenuAnchor, setScopeMenuAnchor] = useState<null | HTMLElement>(null);

    useEffect(() => {
        let cancelled = false;
        fetchQuickAccessData(entity).then(data => { if (!cancelled) setQuickAccessData(data); }).catch(() => {});
        return () => { cancelled = true; };
    }, [entity]);

    const selectedTagIds = useMemo(() => new Set(selectedTagObjects.map(t => t.id)), [selectedTagObjects]);

    const fetchOptions = async (value: string) => {
        setFetching(true);
        const results = await lookupTags(value, entity);
        setOptions(results);
        setFetching(false);
    };

    const handleTagsChange = (newTags: ITagWithType[]) => {
        onChange(newTags.map(t => t.id), tagFilterMode, newTags, tagScopes);
    };

    const handleModeChange = (_: React.MouseEvent, newMode: "any" | "all" | null) => {
        if (newMode) onChange(tagIds, newMode, selectedTagObjects, tagScopes);
    };

    const handleQuickAccessSelect = (tag: ITagWithType) => {
        const newTags = selectedTagIds.has(tag.id)
            ? selectedTagObjects.filter(t => t.id !== tag.id)
            : [...selectedTagObjects, tag];
        onChange(newTags.map(t => t.id), tagFilterMode, newTags, tagScopes);
    };

    // Scope picker: which related-entity types' tags the filter consults. The entity's own scope
    // is always on and cannot be unchecked (filtering by "no scope" is meaningless).
    const applicableScopes = (entity && SCOPE_OPTIONS[entity]) || [];
    const selfScope = entity;
    const selectedScopes = useMemo(
        () => new Set(resolveScopes(tagScopes, selfScope)),
        [tagScopes, selfScope]
    );
    const isBroadened = selfScope ? (selectedScopes.size > 1 || !selectedScopes.has(selfScope)) : false;

    const toggleScope = (scope: E_ENTITY_TYPES) => {
        if (scope === selfScope) return; // self scope is locked on
        const next = new Set(selectedScopes);
        if (next.has(scope)) next.delete(scope); else next.add(scope);
        // Emit in the canonical whitelist order for stable URLs, always keeping the self scope
        // present (it can't be unchecked, and must survive even if it's not in applicableScopes).
        const ordered = applicableScopes.filter(s => next.has(s));
        const finalScopes = selfScope && !ordered.includes(selfScope) ? [selfScope, ...ordered] : ordered;
        onChange(tagIds, tagFilterMode, selectedTagObjects, finalScopes);
    };

    const hasQuickAccess = quickAccessData.individual_tags.length > 0 || quickAccessData.type_dropdowns.length > 0;

    return (
        <Stack direction="column" gap={1}>
            <Stack direction="row" gap={2} alignItems="center" flexWrap="wrap">
                <Typography variant="body2" sx={{color: 'text.secondary', whiteSpace: 'nowrap'}}>
                    Filter by tag:
                </Typography>
                <Box sx={{minWidth: 260, flex: 1}}>
                    <Autocomplete
                        multiple
                        size="small"
                        value={selectedTagObjects}
                        onChange={(_, newValue) => handleTagsChange(newValue)}
                        inputValue={inputValue}
                        onInputChange={async (_, newInputValue) => {
                            setInputValue(newInputValue);
                            if (newInputValue) await fetchOptions(newInputValue);
                        }}
                        isOptionEqualToValue={(opt, val) => opt.id === val.id}
                        getOptionLabel={(opt) => opt.tag_type_name ? `${opt.tag_type_name} / ${opt.name}` : opt.name}
                        options={options}
                        loading={fetching}
                        noOptionsText={fetching ? 'Loading…' : (inputValue ? 'No tags found' : 'Type to search tags')}
                        renderTags={(value, getItemProps) =>
                            value.map((tag, index) => {
                                const {key, ...itemProps} = getItemProps({index});
                                return <Chip key={key} label={tag.name} size="small" {...itemProps} />;
                            })
                        }
                        renderInput={(params) => (
                            <TextField
                                {...params}
                                variant="outlined"
                                placeholder="Search tags…"
                                InputProps={{
                                    ...params.InputProps,
                                    endAdornment: (
                                        <>
                                            {applicableScopes.length > 1 && (
                                                <Tooltip title="Which entities' tags to filter by" arrow>
                                                    <IconButton
                                                        size="small"
                                                        onClick={(e) => setScopeMenuAnchor(e.currentTarget)}
                                                        edge="end"
                                                    >
                                                        <Badge color="primary" variant="dot" invisible={!isBroadened}>
                                                            <AccountTreeIcon fontSize="small"/>
                                                        </Badge>
                                                    </IconButton>
                                                </Tooltip>
                                            )}
                                            {params.InputProps.endAdornment}
                                        </>
                                    ),
                                }}
                            />
                        )}
                    />
                    <Menu
                        anchorEl={scopeMenuAnchor}
                        open={Boolean(scopeMenuAnchor)}
                        onClose={() => setScopeMenuAnchor(null)}
                    >
                        <Typography variant="caption" sx={{px: 2, py: 0.5, color: 'text.secondary', display: 'block'}}>
                            Filter by tags on…
                        </Typography>
                        {applicableScopes.map(scope => {
                            const label = (entity && SCOPE_LABELS[entity]?.[scope]) || scope;
                            const isSelf = scope === selfScope;
                            return (
                                <MenuItem key={scope} dense onClick={() => toggleScope(scope)} disabled={isSelf}>
                                    <Checkbox
                                        size="small"
                                        edge="start"
                                        checked={selectedScopes.has(scope)}
                                        disableRipple
                                        sx={{py: 0}}
                                    />
                                    <ListItemText primary={label}/>
                                </MenuItem>
                            );
                        })}
                    </Menu>
                </Box>
                {selectedTagObjects.length > 1 && (
                    <ToggleButtonGroup
                        size="small"
                        exclusive
                        value={tagFilterMode}
                        onChange={handleModeChange}
                    >
                        <ToggleButton value="any">Match Any</ToggleButton>
                        <ToggleButton value="all">Match All</ToggleButton>
                    </ToggleButtonGroup>
                )}
            </Stack>
            {hasQuickAccess && (
                <QuickAccessBar
                    quickAccessData={quickAccessData}
                    selectedTagIds={selectedTagIds}
                    onSelect={handleQuickAccessSelect}
                    variant="filter"
                />
            )}
        </Stack>
    );
}
