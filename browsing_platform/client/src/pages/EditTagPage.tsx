import React, {useEffect, useMemo, useState} from 'react';
import {useNavigate, useParams} from 'react-router';
import {
    Autocomplete,
    Box,
    Button,
    Checkbox,
    Chip,
    CircularProgress,
    Divider,
    FormControl,
    FormControlLabel,
    IconButton,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import AddIcon from '@mui/icons-material/Add';
import TopNavBar from '../UIComponents/TopNavBar/TopNavBar';
import TagUsageTabs from '../UIComponents/TagUsageTabs/TagUsageTabs';
import {ITagHierarchyEntry, ITagType, ITagUsage, ITagWithType} from '../types/tags';
import {E_ENTITY_TYPES} from '../types/entities';
import {
    addHierarchy,
    createTag,
    fetchTag,
    fetchTagChildren,
    fetchTagParents,
    fetchTagTypes,
    fetchTagUsage,
    removeHierarchy,
    updateHierarchyNotes,
    updateTag,
} from '../services/TagManagementService';
import {lookupTags} from '../services/DataFetcher';
import {toast} from 'material-react-toastify';

/* ── Hierarchy section ────────────────────────────────────────────────────── */

type CreateOption = {inputValue: string; __create: true};
type AddAutocompleteOption = ITagWithType | CreateOption;

const isCreateOption = (o: AddAutocompleteOption | string | null): o is CreateOption =>
    !!o && typeof o === 'object' && (o as CreateOption).__create === true;

// Whether typed text should offer a "create new tag" action: non-empty, comma-free, and not an existing option.
const canOfferCreate = (raw: string, options: ITagWithType[]): boolean => {
    const t = raw.trim().toLowerCase();
    return t.length > 0 && !t.includes(',') && !options.some(o => o.name.toLowerCase() === t);
};

function HierarchyTagSection({
    label,
    entries,
    getEntryId,
    getEntryTagName,
    editingNote,
    setEditingNote,
    onRemove,
    onNoteUpdate,
    setEntries,
    addTag,
    setAddTag,
    addOptions,
    setAddOptions,
    onAdd,
    addLabel,
    onCreateAndAdd,
}: {
    label: string;
    entries: ITagHierarchyEntry[];
    getEntryId: (e: ITagHierarchyEntry) => number;
    getEntryTagName: (e: ITagHierarchyEntry) => string | null | undefined;
    editingNote: {super_id: number; sub_id: number; notes: string} | null;
    setEditingNote: React.Dispatch<React.SetStateAction<{super_id: number; sub_id: number; notes: string} | null>>;
    onRemove: (e: ITagHierarchyEntry) => void;
    onNoteUpdate: (notes: string | null) => Promise<void>;
    setEntries: React.Dispatch<React.SetStateAction<ITagHierarchyEntry[]>>;
    addTag: ITagWithType | null;
    setAddTag: React.Dispatch<React.SetStateAction<ITagWithType | null>>;
    addOptions: ITagWithType[];
    setAddOptions: React.Dispatch<React.SetStateAction<ITagWithType[]>>;
    onAdd: (tag: ITagWithType) => Promise<void>;
    addLabel: string;
    onCreateAndAdd?: (name: string) => Promise<void>;
}) {
    const [inputValue, setInputValue] = useState('');
    const trimmed = inputValue.trim();
    const hasComma = inputValue.includes(',');
    const canCreate = !!onCreateAndAdd && canOfferCreate(inputValue, addOptions);

    const activeEditingNote = editingNote && entries.some(e => e.super_tag_id === editingNote.super_id && e.sub_tag_id === editingNote.sub_id)
        ? editingNote : null;

    const commitNote = async () => {
        if (!activeEditingNote) return;
        await onNoteUpdate(activeEditingNote.notes || null);
        setEntries(prev => prev.map(p =>
            p.super_tag_id === activeEditingNote.super_id && p.sub_tag_id === activeEditingNote.sub_id
                ? {...p, notes: activeEditingNote.notes || null}
                : p
        ));
        setEditingNote(null);
    };

    // Commit a selected/typed value: create a new tag, link an existing tag, or commit free text.
    const commit = async (value: AddAutocompleteOption | string | null) => {
        if (isCreateOption(value)) {
            await onCreateAndAdd!(value.inputValue.trim());
            setInputValue('');
            return;
        }
        if (typeof value === 'string') {
            const name = value.trim();
            if (onCreateAndAdd && name && !name.includes(',')) {
                await onCreateAndAdd(name);
                setInputValue('');
            }
            return;
        }
        if (value) {
            await onAdd(value);
            setAddTag(null);
            setInputValue('');
        }
    };

    // The "Add" button commits the current selection, or the typed name when creation is enabled.
    const handleButton = () => commit(addTag ?? (canCreate ? {inputValue: trimmed, __create: true} : null));

    return (
        <Stack gap={0.5}>
            <Typography variant="caption" color="text.secondary">{label}</Typography>
            <Stack direction="row" gap={0.5} flexWrap="wrap" alignItems="center">
                {entries.map(e => (
                    <Stack key={getEntryId(e)} direction="row" alignItems="center" gap={0.25}>
                        <Tooltip title={e.notes || ''} arrow disableInteractive>
                            <Chip label={getEntryTagName(e)} size="small" onDelete={() => onRemove(e)}/>
                        </Tooltip>
                        <Tooltip title="Edit note" arrow disableInteractive>
                            <IconButton size="small" sx={{p: 0.25}} onClick={() => setEditingNote({super_id: e.super_tag_id, sub_id: e.sub_tag_id, notes: e.notes ?? ''})}>
                                <EditIcon sx={{fontSize: '0.8rem'}}/>
                            </IconButton>
                        </Tooltip>
                    </Stack>
                ))}
                {entries.length === 0 && <Typography variant="caption" color="text.secondary">None</Typography>}
            </Stack>
            {activeEditingNote && (
                <Stack direction="row" gap={1} alignItems="center">
                    <TextField
                        size="small"
                        label="Note"
                        value={activeEditingNote.notes}
                        onChange={e => setEditingNote(n => n ? {...n, notes: e.target.value} : null)}
                        onKeyDown={async e => {
                            if (e.key === 'Enter') { await commitNote(); }
                            else if (e.key === 'Escape') { setEditingNote(null); }
                        }}
                        onBlur={commitNote}
                        autoFocus
                        sx={{flex: 1}}
                    />
                </Stack>
            )}
            <Stack direction="row" gap={1} alignItems="flex-start">
                <Autocomplete<AddAutocompleteOption, false, false, boolean>
                    sx={{flex: 1}}
                    size="small"
                    freeSolo={!!onCreateAndAdd}
                    selectOnFocus
                    handleHomeEndKeys
                    blurOnSelect={false}
                    value={addTag}
                    inputValue={inputValue}
                    onInputChange={async (_, v, reason) => {
                        if (reason !== 'reset') setInputValue(v);
                        if (v) setAddOptions(await lookupTags(v));
                    }}
                    onChange={(_, v) => {
                        // Child section (creation enabled) commits on select for rapid entry;
                        // parent section keeps its select-then-click-Add flow.
                        if (onCreateAndAdd) { void commit(v); }
                        else { setAddTag(v as ITagWithType | null); }
                    }}
                    options={addOptions}
                    filterOptions={(opts, state) => {
                        const tl = state.inputValue.trim().toLowerCase();
                        const filtered = opts.filter(o => !isCreateOption(o) && o.name.toLowerCase().includes(tl));
                        if (onCreateAndAdd && canOfferCreate(state.inputValue, opts.filter((o): o is ITagWithType => !isCreateOption(o)))) {
                            filtered.unshift({inputValue: state.inputValue.trim(), __create: true});
                        }
                        return filtered;
                    }}
                    getOptionLabel={o => (typeof o === 'string' ? o : isCreateOption(o) ? o.inputValue : o.name)}
                    isOptionEqualToValue={(a, b) =>
                        isCreateOption(a) || isCreateOption(b)
                            ? isCreateOption(a) && isCreateOption(b) && a.inputValue === b.inputValue
                            : a.id === b.id}
                    renderOption={(props, o) => (
                        <li {...props} key={isCreateOption(o) ? `__create:${o.inputValue}` : o.id}>
                            {isCreateOption(o) ? (
                                <Stack direction="row" alignItems="center" gap={0.5} sx={{color: 'primary.main'}}>
                                    <AddIcon fontSize="small"/>
                                    <span>Create new subtag "{o.inputValue}"</span>
                                </Stack>
                            ) : o.name}
                        </li>
                    )}
                    renderInput={params => (
                        <TextField
                            {...params}
                            label={addLabel}
                            size="small"
                            error={hasComma}
                            helperText={hasComma ? 'Tag name cannot contain commas' : undefined}
                        />
                    )}
                />
                <Button size="small" variant="outlined" onClick={handleButton} disabled={!addTag && !canCreate}>Add</Button>
            </Stack>
        </Stack>
    );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function EditTagPage() {
    const {tag_id} = useParams<{tag_id: string}>();
    const navigate = useNavigate();
    const tagId = Number(tag_id);

    const [loading, setLoading] = useState(true);
    const [notFound, setNotFound] = useState(false);
    const [tagTypes, setTagTypes] = useState<ITagType[]>([]);
    const [form, setForm] = useState<{name: string; description: string; tag_type_id: number | null; quick_access: boolean; omit_from_tag_type_dropdown: boolean; notes_recommended: boolean}>({
        name: '', description: '', tag_type_id: null, quick_access: false, omit_from_tag_type_dropdown: false, notes_recommended: true,
    });
    const [usage, setUsage] = useState<ITagUsage | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);
    const [hierarchyParents, setHierarchyParents] = useState<ITagHierarchyEntry[]>([]);
    const [hierarchyChildren, setHierarchyChildren] = useState<ITagHierarchyEntry[]>([]);
    const [addParentTag, setAddParentTag] = useState<ITagWithType | null>(null);
    const [addParentOptions, setAddParentOptions] = useState<ITagWithType[]>([]);
    const [addChildTag, setAddChildTag] = useState<ITagWithType | null>(null);
    const [addChildOptions, setAddChildOptions] = useState<ITagWithType[]>([]);
    const [editingNote, setEditingNote] = useState<{super_id: number; sub_id: number; notes: string} | null>(null);

    const entityAffinity = useMemo<E_ENTITY_TYPES[] | null>(() => {
        if (!form.tag_type_id) return null;
        return (tagTypes.find(tt => tt.id === form.tag_type_id)?.entity_affinity ?? null) as E_ENTITY_TYPES[] | null;
    }, [form.tag_type_id, tagTypes]);

    useEffect(() => {
        if (!tagId) return;
        setLoading(true);
        Promise.all([
            fetchTag(tagId),
            fetchTagTypes(),
            fetchTagParents(tagId),
            fetchTagChildren(tagId),
            fetchTagUsage(tagId),
        ]).then(([tag, types, parents, children, tagUsage]) => {
            setTagTypes(types);
            setForm({
                name: tag.name,
                description: tag.description ?? '',
                tag_type_id: tag.tag_type_id ?? null,
                quick_access: tag.quick_access ?? false,
                omit_from_tag_type_dropdown: tag.omit_from_tag_type_dropdown ?? false,
                notes_recommended: tag.notes_recommended ?? true,
            });
            setHierarchyParents(parents);
            setHierarchyChildren(children);
            setUsage(tagUsage);
            setLoading(false);
        }).catch((e: any) => {
            if (e?.status === 404) {
                setNotFound(true);
            } else {
                toast.error(e?.message || 'Failed to load tag');
            }
            setLoading(false);
        });
        document.title = 'Edit Tag | Browsing Platform';
    }, [tagId]);

    const loadHierarchy = async () => {
        try {
            const [parents, children, tagUsage] = await Promise.all([
                fetchTagParents(tagId),
                fetchTagChildren(tagId),
                fetchTagUsage(tagId),
            ]);
            setHierarchyParents(parents);
            setHierarchyChildren(children);
            setUsage(tagUsage);
            setRefreshKey(k => k + 1);
        } catch (e: any) {
            toast.error(e?.message || 'Failed to refresh hierarchy');
        }
    };

    const handleSave = async () => {
        try {
            await updateTag(tagId, {
                name: form.name,
                description: form.description || null,
                tag_type_id: form.tag_type_id,
                quick_access: form.quick_access,
                omit_from_tag_type_dropdown: form.omit_from_tag_type_dropdown,
                notes_recommended: form.notes_recommended,
            });
            navigate('/tags?tab=tags');
        } catch (e: any) {
            toast.error(e?.message || 'Error saving tag');
        }
    };

    const handleAddParent = async (tag: ITagWithType) => {
        try {
            await addHierarchy({super_tag_id: tag.id, sub_tag_id: tagId, notes: null});
            setAddParentTag(null);
            await loadHierarchy();
        } catch (e: any) {
            toast.error(e?.message || 'Cannot add parent (may create a cycle)');
        }
    };

    const handleAddChild = async (tag: ITagWithType) => {
        try {
            await addHierarchy({super_tag_id: tagId, sub_tag_id: tag.id, notes: null});
            setAddChildTag(null);
            await loadHierarchy();
        } catch (e: any) {
            toast.error(e?.message || 'Cannot add child (may create a cycle)');
        }
    };

    const handleCreateChild = async (name: string) => {
        try {
            const created = await createTag({
                name,
                description: null,
                tag_type_id: form.tag_type_id,
                quick_access: form.quick_access,
                omit_from_tag_type_dropdown: form.omit_from_tag_type_dropdown,
                notes_recommended: form.notes_recommended,
            });
            await addHierarchy({super_tag_id: tagId, sub_tag_id: created.id!, notes: null});
            await loadHierarchy();
        } catch (e: any) {
            toast.error(e?.message || 'Could not create subtag');
        }
    };

    const handleRemoveParent = async (entry: ITagHierarchyEntry) => {
        try {
            await removeHierarchy(entry.super_tag_id, entry.sub_tag_id);
            await loadHierarchy();
        } catch (e: any) {
            toast.error(e?.message || 'Cannot remove parent');
        }
    };

    const handleRemoveChild = async (entry: ITagHierarchyEntry) => {
        try {
            await removeHierarchy(entry.super_tag_id, entry.sub_tag_id);
            await loadHierarchy();
        } catch (e: any) {
            toast.error(e?.message || 'Cannot remove child');
        }
    };

    if (loading) return (
        <div className="page-wrap">
            <TopNavBar>Edit Tag</TopNavBar>
            <div className="page-content content-wrap">
                <CircularProgress/>
            </div>
        </div>
    );

    if (notFound) return (
        <div className="page-wrap">
            <TopNavBar>Edit Tag</TopNavBar>
            <div className="page-content content-wrap">
                <Typography>Tag not found.</Typography>
                <Button onClick={() => navigate('/tags?tab=tags')}>Back to Tags</Button>
            </div>
        </div>
    );

    return (
        <div className="page-wrap">
            <TopNavBar>Edit Tag: {form.name}</TopNavBar>
            <div className="page-content content-wrap">
                <Stack gap={2}>
                    <Stack gap={2} sx={{maxWidth: 600}}>
                        <TextField
                            label="Name"
                            value={form.name}
                            onChange={e => setForm(f => ({...f, name: e.target.value}))}
                            error={form.name.includes(',')}
                            helperText={form.name.includes(',') ? 'Tag name cannot contain commas' : undefined}
                            required
                        />
                        <TextField
                            label="Description"
                            value={form.description}
                            onChange={e => setForm(f => ({...f, description: e.target.value}))}
                        />
                        <FormControl size="small">
                            <InputLabel>Tag Type</InputLabel>
                            <Select
                                value={form.tag_type_id ?? ''}
                                label="Tag Type"
                                onChange={e => setForm(f => ({...f, tag_type_id: e.target.value ? Number(e.target.value) : null}))}
                            >
                                <MenuItem value=""><em>None</em></MenuItem>
                                {tagTypes.map(tt => <MenuItem key={tt.id} value={tt.id}>{tt.name}</MenuItem>)}
                            </Select>
                        </FormControl>
                        <FormControlLabel
                            control={<Checkbox checked={form.quick_access} onChange={e => setForm(f => ({...f, quick_access: e.target.checked}))}/>}
                            label="Quick access (show as shortcut button in annotator)"
                        />
                        <FormControlLabel
                            control={<Checkbox checked={form.notes_recommended} onChange={e => setForm(f => ({...f, notes_recommended: e.target.checked}))}/>}
                            label="Prompt for notes on quick-assign"
                        />
                        <FormControlLabel
                            control={<Checkbox checked={form.omit_from_tag_type_dropdown} onChange={e => setForm(f => ({...f, omit_from_tag_type_dropdown: e.target.checked}))}/>}
                            label="Exclude from type dropdown (when type has quick access)"
                        />

                        <Divider/>
                        <Typography variant="subtitle2">Hierarchy</Typography>
                        <HierarchyTagSection
                            label="Parents (supertags)"
                            entries={hierarchyParents}
                            getEntryId={e => e.super_tag_id}
                            getEntryTagName={e => e.super_tag_name}
                            editingNote={editingNote}
                            setEditingNote={setEditingNote}
                            onRemove={handleRemoveParent}
                            onNoteUpdate={notes => updateHierarchyNotes(editingNote!.super_id, editingNote!.sub_id, notes)}
                            setEntries={setHierarchyParents}
                            addTag={addParentTag}
                            setAddTag={setAddParentTag}
                            addOptions={addParentOptions}
                            setAddOptions={setAddParentOptions}
                            onAdd={handleAddParent}
                            addLabel="Add parent"
                        />
                        <HierarchyTagSection
                            label="Children (subtags)"
                            entries={hierarchyChildren}
                            getEntryId={e => e.sub_tag_id}
                            getEntryTagName={e => e.sub_tag_name}
                            editingNote={editingNote}
                            setEditingNote={setEditingNote}
                            onRemove={handleRemoveChild}
                            onNoteUpdate={notes => updateHierarchyNotes(editingNote!.super_id, editingNote!.sub_id, notes)}
                            setEntries={setHierarchyChildren}
                            addTag={addChildTag}
                            setAddTag={setAddChildTag}
                            addOptions={addChildOptions}
                            setAddOptions={setAddChildOptions}
                            onAdd={handleAddChild}
                            addLabel="Add child"
                            onCreateAndAdd={handleCreateChild}
                        />

                        <Box sx={{display: 'flex', gap: 1, pt: 1}}>
                            <Button variant="outlined" onClick={() => navigate('/tags?tab=tags')}>Cancel</Button>
                            <Button
                                variant="contained"
                                onClick={handleSave}
                                disabled={form.name.includes(',') || !form.name.trim()}
                            >
                                Save
                            </Button>
                        </Box>
                    </Stack>

                    <Divider/>

                    <TagUsageTabs
                        tagId={tagId}
                        usage={usage}
                        entityAffinity={entityAffinity}
                        refreshKey={refreshKey}
                    />
                </Stack>
            </div>
        </div>
    );
}
