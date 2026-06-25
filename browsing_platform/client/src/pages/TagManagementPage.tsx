import React, {useEffect, useState} from 'react';
import {useNavigate, useSearchParams} from 'react-router';
import {
    Badge,
    Box,
    Button,
    Checkbox,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    FormControl,
    FormControlLabel,
    IconButton,
    InputLabel,
    List,
    ListItemButton,
    ListItemText,
    MenuItem,
    OutlinedInput,
    Select,
    Stack,
    Tab,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Tabs,
    TextField,
    Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import AddIcon from "@mui/icons-material/Add";
import TopNavBar from "../UIComponents/TopNavBar/TopNavBar";
import {ITagDetail, ITagType} from "../types/tags";
import {
    createTag,
    createTagType,
    deleteTag,
    deleteTagType,
    fetchTags,
    fetchTagTypeCounts,
    fetchTagTypes,
    updateTag,
    updateTagType,
} from "../services/TagManagementService";
import {toast} from "material-react-toastify";
import ImportTagsTab from "./TagManagement/ImportTagsTab";
import ImportAnnotationsTab from "./TagManagement/ImportAnnotationsTab";

const ENTITY_AFFINITY_OPTIONS = ["account", "post", "media"];

/* ── Tab 1: Tag Types ───────────────────────────────────────────────────────── */

function TagTypesTab() {
    const [tagTypes, setTagTypes] = useState<ITagType[]>([]);
    const [loading, setLoading] = useState(true);
    const [editTarget, setEditTarget] = useState<ITagType | null>(null);
    const [formOpen, setFormOpen] = useState(false);
    const [form, setForm] = useState<Omit<ITagType, "id">>({name: "", description: null, notes: null, entity_affinity: null, quick_access: false});

    const load = () => {
        setLoading(true);
        fetchTagTypes().then(data => { setTagTypes(data); setLoading(false); });
    };
    useEffect(load, []);

    const openCreate = () => {
        setEditTarget(null);
        setForm({name: "", description: null, notes: null, entity_affinity: null});
        setFormOpen(true);
    };

    const openEdit = (tt: ITagType) => {
        setEditTarget(tt);
        setForm({name: tt.name, description: tt.description ?? null, notes: tt.notes ?? null, entity_affinity: tt.entity_affinity ?? null, quick_access: tt.quick_access ?? false});
        setFormOpen(true);
    };

    const handleSave = async () => {
        try {
            if (editTarget?.id) {
                await updateTagType(editTarget.id, form);
            } else {
                await createTagType(form);
            }
            setFormOpen(false);
            load();
        } catch (e: any) {
            toast.error(e?.message || "Error saving tag type");
        }
    };

    const handleDelete = async (tt: ITagType) => {
        if (!tt.id) return;
        try {
            await deleteTagType(tt.id);
            load();
        } catch (e: any) {
            toast.error(e?.message || "Cannot delete tag type");
        }
    };

    if (loading) return <CircularProgress/>;

    return <Stack gap={2}>
        <Box>
            <Button variant="contained" startIcon={<AddIcon/>} onClick={openCreate}>New Tag Type</Button>
        </Box>
        <Table size="small">
            <TableHead>
                <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Entity Affinity</TableCell>
                    <TableCell/>
                </TableRow>
            </TableHead>
            <TableBody>
                {tagTypes.map(tt => (
                    <TableRow key={tt.id}>
                        <TableCell>{tt.name}</TableCell>
                        <TableCell>{tt.description}</TableCell>
                        <TableCell>
                            <Stack direction="row" gap={0.5} flexWrap="wrap">
                                {tt.entity_affinity?.map(e => <Chip key={e} label={e} size="small"/>)}
                            </Stack>
                        </TableCell>
                        <TableCell>
                            <IconButton size="small" onClick={() => openEdit(tt)}><EditIcon fontSize="small"/></IconButton>
                            <IconButton size="small" color="error" onClick={() => handleDelete(tt)}><DeleteIcon fontSize="small"/></IconButton>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>

        <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
            <DialogTitle>{editTarget ? "Edit Tag Type" : "New Tag Type"}</DialogTitle>
            <DialogContent>
                <Stack gap={2} sx={{mt: 1}}>
                    <TextField label="Name" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} required/>
                    <TextField label="Description" value={form.description ?? ""} onChange={e => setForm(f => ({...f, description: e.target.value || null}))}/>
                    <TextField label="Notes" multiline value={form.notes ?? ""} onChange={e => setForm(f => ({...f, notes: e.target.value || null}))}/>
                    <FormControl>
                        <InputLabel>Entity Affinity</InputLabel>
                        <Select
                            multiple
                            value={form.entity_affinity ?? []}
                            onChange={e => setForm(f => ({...f, entity_affinity: e.target.value as string[] || null}))}
                            input={<OutlinedInput label="Entity Affinity"/>}
                            renderValue={(sel) => (
                                <Stack direction="row" gap={0.5} flexWrap="wrap">
                                    {(sel as string[]).map(v => <Chip key={v} label={v} size="small"/>)}
                                </Stack>
                            )}
                        >
                            {ENTITY_AFFINITY_OPTIONS.map(o => <MenuItem key={o} value={o}>{o}</MenuItem>)}
                        </Select>
                    </FormControl>
                    <FormControlLabel
                        control={<Checkbox checked={form.quick_access ?? false} onChange={e => setForm(f => ({...f, quick_access: e.target.checked}))}/>}
                        label="Quick access (show dropdown of this type's tags in annotator)"
                    />
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={() => setFormOpen(false)}>Cancel</Button>
                <Button variant="contained" onClick={handleSave}>Save</Button>
            </DialogActions>
        </Dialog>
    </Stack>;
}

/* ── Tab 2: Tags ────────────────────────────────────────────────────────────── */

function TagsTab() {
    const [params, setParams] = useSearchParams();
    const navigate = useNavigate();
    const selectedTypeId = params.get('type') ? Number(params.get('type')) : null;
    const setSelectedTypeId = (id: number | null) => {
        setPage(1);
        setParams(p => {
            const next = new URLSearchParams(p);
            if (id == null) next.delete('type'); else next.set('type', String(id));
            return next;
        });
    };

    const [tagTypes, setTagTypes] = useState<ITagType[]>([]);
    const [typeCounts, setTypeCounts] = useState<Record<string, number>>({});
    const [tags, setTags] = useState<ITagDetail[]>([]);
    const [search, setSearch] = useState("");
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);
    const PAGE_SIZE = 50;
    const [formOpen, setFormOpen] = useState(false);
    const [form, setForm] = useState<{name: string; description: string; tag_type_id: number | null; quick_access: boolean; omit_from_tag_type_dropdown: boolean; notes_recommended: boolean}>({
        name: "", description: "", tag_type_id: null, quick_access: false, omit_from_tag_type_dropdown: false, notes_recommended: true
    });

    const loadTypes = () => {
        fetchTagTypes().then(setTagTypes);
        fetchTagTypeCounts().then(setTypeCounts).catch(() => {});
    };
    const loadTags = () => {
        setLoading(true);
        fetchTags({tag_type_id: selectedTypeId ?? undefined, q: search || undefined, page, page_size: PAGE_SIZE}).then(data => {
            setTags(data);
            setLoading(false);
        });
    };

    useEffect(() => { loadTypes(); }, []);
    useEffect(() => { loadTags(); }, [selectedTypeId, search, page]);

    const openCreate = () => {
        setForm({name: "", description: "", tag_type_id: selectedTypeId, quick_access: false, omit_from_tag_type_dropdown: false, notes_recommended: true});
        setFormOpen(true);
    };

    const handleSave = async () => {
        try {
            await createTag({name: form.name, description: form.description || null, tag_type_id: form.tag_type_id, quick_access: form.quick_access, omit_from_tag_type_dropdown: form.omit_from_tag_type_dropdown, notes_recommended: form.notes_recommended});
            setFormOpen(false);
            loadTags();
        } catch (e: any) {
            toast.error(e?.message || "Error saving tag");
        }
    };

    const handleDelete = async (t: ITagDetail) => {
        if (!t.id) return;
        try {
            await deleteTag(t.id);
            loadTags();
        } catch (e: any) {
            toast.error(e?.message || "Cannot delete tag");
        }
    };

    const handleToggleQuickAccess = async (t: ITagDetail) => {
        if (!t.id) return;
        const newValue = !t.quick_access;
        setTags(prev => prev.map(tag => tag.id === t.id ? {...tag, quick_access: newValue} : tag));
        try {
            await updateTag(t.id, {name: t.name, description: t.description ?? null, tag_type_id: t.tag_type_id ?? null, quick_access: newValue, omit_from_tag_type_dropdown: t.omit_from_tag_type_dropdown ?? false, notes_recommended: t.notes_recommended ?? true});
        } catch (e: any) {
            setTags(prev => prev.map(tag => tag.id === t.id ? {...tag, quick_access: !newValue} : tag));
            toast.error(e?.message || "Error updating quick access");
        }
    };

    const totalCount = Object.values(typeCounts).reduce((a, b) => a + b, 0);

    return <Stack direction="row" gap={2} sx={{minHeight: 400}}>
        {/* Left sidebar: tag type filter */}
        <Stack sx={{width: 190, borderRight: '1px solid #e0e0e0', pr: 1, flexShrink: 0}}>
            <Typography variant="caption" sx={{mb: 0.5, color: 'text.secondary', fontWeight: 600, pl: 1}}>Filter by type</Typography>
            <List dense disablePadding>
                <ListItemButton
                    selected={selectedTypeId === null}
                    onClick={() => setSelectedTypeId(null)}
                    sx={{borderRadius: 1}}
                >
                    <ListItemText primary="All" primaryTypographyProps={{variant: 'body2'}}/>
                    <Badge badgeContent={totalCount} color="default" max={9999}
                           sx={{'& .MuiBadge-badge': {position: 'static', transform: 'none', ml: 1}}}/>
                </ListItemButton>
                {tagTypes.map(tt => (
                    <ListItemButton
                        key={tt.id}
                        selected={selectedTypeId === tt.id}
                        onClick={() => setSelectedTypeId(tt.id ?? null)}
                        sx={{borderRadius: 1}}
                    >
                        <ListItemText primary={tt.name} primaryTypographyProps={{variant: 'body2'}}/>
                        <Badge
                            badgeContent={typeCounts[String(tt.id)] ?? 0}
                            color="primary" max={9999}
                            sx={{'& .MuiBadge-badge': {position: 'static', transform: 'none', ml: 1}}}
                        />
                    </ListItemButton>
                ))}
                {typeCounts['null'] > 0 && (
                    <ListItemButton
                        selected={false}
                        disabled
                        sx={{borderRadius: 1}}
                    >
                        <ListItemText primary="(untyped)" primaryTypographyProps={{variant: 'body2', color: 'text.secondary'}}/>
                        <Badge badgeContent={typeCounts['null']} color="default" max={9999}
                               sx={{'& .MuiBadge-badge': {position: 'static', transform: 'none', ml: 1}}}/>
                    </ListItemButton>
                )}
            </List>
        </Stack>
        {/* Right: tag table */}
        <Stack gap={1} sx={{flex: 1}}>
            <Stack direction="row" gap={1}>
                <TextField size="small" placeholder="Search tags…" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} sx={{flex: 1}}/>
                <Button variant="contained" startIcon={<AddIcon/>} onClick={openCreate}>New Tag</Button>
            </Stack>
            {loading ? <CircularProgress/> : (
                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Name</TableCell>
                            <TableCell>Type</TableCell>
                            <TableCell>Description</TableCell>
                            <TableCell>Parents</TableCell>
                            <TableCell>Quick Access</TableCell>
                            <TableCell/>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {tags.map(t => (
                            <TableRow key={t.id}>
                                <TableCell>{t.name}</TableCell>
                                <TableCell>{t.tag_type_name && <Chip label={t.tag_type_name} size="small"/>}</TableCell>
                                <TableCell>{t.description}</TableCell>
                                <TableCell>
                                    <Stack direction="row" gap={0.5} flexWrap="wrap">
                                        {t.parents?.map(p => <Chip key={p.id} label={p.name} size="small" variant="outlined"/>)}
                                    </Stack>
                                </TableCell>
                                <TableCell padding="checkbox">
                                    <Checkbox
                                        checked={!!t.quick_access}
                                        size="small"
                                        onChange={() => handleToggleQuickAccess(t)}
                                    />
                                </TableCell>
                                <TableCell>
                                    <IconButton size="small" onClick={() => navigate(`/tags/${t.id}`)}><EditIcon fontSize="small"/></IconButton>
                                    <IconButton size="small" color="error" onClick={() => handleDelete(t)}><DeleteIcon fontSize="small"/></IconButton>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}
            <Stack direction="row" justifyContent="center" alignItems="center" gap={2}>
                <Button size="small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <Typography variant="caption">Page {page}</Typography>
                <Button size="small" disabled={tags.length < PAGE_SIZE} onClick={() => setPage(p => p + 1)}>Next</Button>
            </Stack>
        </Stack>

        <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
            <DialogTitle>New Tag</DialogTitle>
            <DialogContent>
                <Stack gap={2} sx={{mt: 1}}>
                    <TextField
                        label="Name"
                        value={form.name}
                        onChange={e => setForm(f => ({...f, name: e.target.value}))}
                        error={form.name.includes(',')}
                        helperText={form.name.includes(',') ? 'Tag name cannot contain commas' : undefined}
                        required
                    />
                    <TextField label="Description" value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))}/>
                    <FormControl size="small">
                        <InputLabel>Tag Type</InputLabel>
                        <Select
                            value={form.tag_type_id ?? ""}
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
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button onClick={() => setFormOpen(false)}>Cancel</Button>
                <Button variant="contained" onClick={handleSave} disabled={form.name.includes(',') || !form.name.trim()}>Save</Button>
            </DialogActions>
        </Dialog>
    </Stack>;
}

/* ── Main Page ──────────────────────────────────────────────────────────────── */

const TAB_KEYS = ['types', 'tags', 'import-tags', 'import-annotations'];

export default function TagManagementPage() {
    const [params, setParams] = useSearchParams();
    const tab = Math.max(0, TAB_KEYS.indexOf(params.get('tab') ?? 'types'));

    const setTab = (v: number) => setParams(p => {
        const next = new URLSearchParams(p);
        next.set('tab', TAB_KEYS[v]);
        if (TAB_KEYS[v] !== 'tags') next.delete('type');
        return next;
    });

    useEffect(() => {
        document.title = "Tags | Browsing Platform";
    }, []);

    return <div className="page-wrap">
        <TopNavBar>Tags</TopNavBar>
        <div className="page-content content-wrap">
            <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{mb: 2}}>
                <Tab label="Tag Types"/>
                <Tab label="Tags"/>
                <Tab label="Import Tags"/>
                <Tab label="Import Annotations"/>
            </Tabs>
            <Divider sx={{mb: 2}}/>
            {tab === 0 && <TagTypesTab/>}
            {tab === 1 && <TagsTab/>}
            {tab === 2 && <ImportTagsTab/>}
            {tab === 3 && <ImportAnnotationsTab/>}
        </div>
    </div>;
}
