import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    FormControlLabel,
    FormLabel,
    MenuItem,
    Paper,
    Radio,
    RadioGroup,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from '@mui/material';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import TopNavBar from '../UIComponents/TopNavBar/TopNavBar';
import server from '../services/server';
import config from '../services/config';
import cookie from 'js-cookie';

interface Job {
    id: number;
    started_at: string;
    completed_at: string | null;
    status: 'running' | 'completed' | 'failed';
    triggered_by_user_id: number | null;
    triggered_by_ip: string | null;
    error_message: string | null;
}

interface LogLine {
    type: string;
    text?: string;
    level?: string;
    status?: string;
    error?: string;
}

const STATUS_COLOR: Record<string, 'default' | 'success' | 'error' | 'warning' | 'info'> = {
    running: 'info',
    completed: 'success',
    failed: 'error',
};

const LOG_LEVEL_COLOR: Record<string, string> = {
    ERROR: '#ff6b6b',
    WARNING: '#ffa94d',
    INFO: '#74c0fc',
    DEBUG: '#868e96',
};

const WS_URL = (() => {
    const base = config.serverPath.replace(/\/$/, '').replace(/^http/, 'ws');
    return `${base}/api/incorporate/ws`;
})();

export default function IncorporatePage() {
    const [running, setRunning] = useState(false);
    const [starting, setStarting] = useState(false);
    const [stopping, setStopping] = useState(false);
    // Optional test scope (overrides server-side env defaults for a single run).
    const [mode, setMode] = useState<'register' | 'rerun'>('register');
    const [limit, setLimit] = useState('');
    const [filter, setFilter] = useState('');
    const [history, setHistory] = useState<Job[]>([]);
    const [logs, setLogs] = useState<LogLine[]>([]);
    const [wsConnected, setWsConnected] = useState(false);
    const logBoxRef = useRef<HTMLDivElement>(null);
    const wsRef = useRef<WebSocket | null>(null);

    // ---- Reset incorporation status modal ----
    const RESET_CONFIRMATION = 'I am sure!';
    const [resetOpen, setResetOpen] = useState(false);
    const [resetTarget, setResetTarget] = useState<'pending' | 'parsed'>('pending');
    const [resetIdMin, setResetIdMin] = useState('');
    const [resetIdMax, setResetIdMax] = useState('');
    const [resetFrom, setResetFrom] = useState('');
    const [resetTo, setResetTo] = useState('');
    const [resetConfirmText, setResetConfirmText] = useState('');
    const [resetPreviewCount, setResetPreviewCount] = useState<number | null>(null);
    const [resetBusy, setResetBusy] = useState(false);
    const [resetError, setResetError] = useState<string | null>(null);
    const [resetSuccess, setResetSuccess] = useState<string | null>(null);

    const resetPayload = useCallback(() => {
        const payload: Record<string, any> = {target_status: resetTarget};
        if (resetIdMin.trim() !== '') payload.id_min = Number(resetIdMin.trim());
        if (resetIdMax.trim() !== '') payload.id_max = Number(resetIdMax.trim());
        // datetime-local yields e.g. "2026-01-02T15:04"; normalize the 'T' to a space
        // for unambiguous MySQL DATETIME comparison.
        if (resetFrom.trim() !== '') payload.archiving_from = resetFrom.trim().replace('T', ' ');
        if (resetTo.trim() !== '') payload.archiving_to = resetTo.trim().replace('T', ' ');
        return payload;
    }, [resetTarget, resetIdMin, resetIdMax, resetFrom, resetTo]);

    const openResetModal = () => {
        setResetTarget('pending');
        setResetIdMin('');
        setResetIdMax('');
        setResetFrom('');
        setResetTo('');
        setResetConfirmText('');
        setResetPreviewCount(null);
        setResetError(null);
        setResetSuccess(null);
        setResetOpen(true);
    };

    // Any change to the range/target invalidates a prior preview so the confirm
    // can never act on a stale count. The typed confirmation is also cleared so the
    // gate must be satisfied again for the new preview (it can't be re-armed silently).
    const invalidatePreview = () => {
        setResetPreviewCount(null);
        setResetConfirmText('');
        setResetSuccess(null);
    };

    const handlePreview = async () => {
        setResetBusy(true);
        setResetError(null);
        setResetSuccess(null);
        try {
            const data = await server.post('incorporate/reset-status', {...resetPayload(), dry_run: true});
            setResetPreviewCount(data?.count ?? 0);
        } catch (e: any) {
            setResetError(e?.message ?? 'Preview failed');
            setResetPreviewCount(null);
        } finally {
            setResetBusy(false);
        }
    };

    const handleReset = async () => {
        setResetBusy(true);
        setResetError(null);
        try {
            const data = await server.post('incorporate/reset-status', {
                ...resetPayload(),
                dry_run: false,
                confirmation: RESET_CONFIRMATION,
            });
            setResetSuccess(`Reset ${data?.updated ?? 0} session(s) to "${resetTarget}".`);
            setResetPreviewCount(null);
            setResetConfirmText('');
            setResetOpen(false);
        } catch (e: any) {
            // Force a fresh preview + re-typed confirmation before any retry.
            setResetError(e?.message ?? 'Reset failed');
            setResetPreviewCount(null);
            setResetConfirmText('');
        } finally {
            setResetBusy(false);
        }
    };

    useEffect(() => {
        document.title = 'Incorporate | Browsing Platform';
    }, []);

    // -----------------------------------------------------------------------
    // Fetch initial status and history
    // -----------------------------------------------------------------------

    const fetchStatus = useCallback(async () => {
        const data = await server.get('incorporate/status');
        if (data) setRunning(data.running);
    }, []);

    const fetchHistory = useCallback(async () => {
        const data = await server.get('incorporate/history');
        if (data?.jobs) setHistory(data.jobs);
    }, []);

    useEffect(() => {
        fetchStatus();
        fetchHistory();
    }, [fetchStatus, fetchHistory]);

    // -----------------------------------------------------------------------
    // WebSocket connection
    // -----------------------------------------------------------------------

    useEffect(() => {
        const token = cookie.get('token') ?? '';
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        // Send the auth token as the first message rather than in the URL,
        // which would expose it in server logs and browser history.
        ws.onopen = () => {
            ws.send(JSON.stringify({token}));
            setWsConnected(true);
        };
        ws.onclose = () => setWsConnected(false);
        ws.onerror = () => setWsConnected(false);

        ws.onmessage = (event) => {
            try {
                const msg: LogLine = JSON.parse(event.data);
                if (msg.type === 'ping') return;
                if (msg.type === 'done') {
                    setRunning(false);
                    setStarting(false);
                    setStopping(false);
                    fetchHistory();
                }
                if (msg.type === 'status' || msg.type === 'log' || msg.type === 'done') {
                    setLogs(prev => [...prev, msg]);
                }
            } catch {
                // ignore malformed messages
            }
        };

        return () => {
            ws.close();
        };
    }, [fetchHistory]);

    // Auto-scroll log panel to bottom on new entries, but only if it was already
    // scrolled to the bottom — preserve the user's position if they scrolled up.
    useEffect(() => {
        const el = logBoxRef.current;
        if (!el) return;
        const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
        if (isAtBottom) el.scrollTop = el.scrollHeight;
    }, [logs]);

    // -----------------------------------------------------------------------
    // Start incorporation
    // -----------------------------------------------------------------------

    const handleStart = async () => {
        setStarting(true);
        setLogs([]);
        const params = new URLSearchParams();
        if (mode !== 'register') params.set('mode', mode);
        if (limit.trim() !== '') params.set('limit', limit.trim());
        if (filter.trim() !== '') params.set('filter', filter.trim());
        const qs = params.toString();
        const data = await server.post(`incorporate/start${qs ? `?${qs}` : ''}`, {});
        if (data?.status === 'started') {
            setRunning(true);
        } else {
            setStarting(false);
        }
    };

    const handleStop = async () => {
        setStopping(true);
        await server.post('incorporate/stop', {});
    };

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    const logLineColor = (line: LogLine): string => {
        if (line.type === 'done') return line.status === 'completed' ? '#69db7c' : '#ff6b6b';
        if (line.type === 'status') return '#a9e34b';
        return LOG_LEVEL_COLOR[line.level ?? ''] ?? '#ced4da';
    };

    const formatDate = (iso: string | null) => {
        if (!iso) return '—';
        return new Date(iso).toLocaleString();
    };

    // -----------------------------------------------------------------------
    // Render
    // -----------------------------------------------------------------------

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
            <TopNavBar>
                <Typography variant="h6" sx={{ color: 'white' }}>
                    Incorporate Archives
                </Typography>
            </TopNavBar>

            <Box sx={{ flex: 1, overflowY: 'auto', p: 3 }}>
            <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
                {/* Run button */}
                <Stack direction="row" alignItems="center" gap={2} mb={3}>
                    <Button
                        variant="contained"
                        color="primary"
                        size="large"
                        startIcon={running || starting ? <CircularProgress size={18} color="inherit" /> : <PlayArrowIcon />}
                        onClick={handleStart}
                        disabled={running || starting}
                    >
                        {running ? 'Running…' : starting ? 'Starting…' : 'Run Incorporation'}
                    </Button>
                    {running && (
                        <Button
                            variant="outlined"
                            color="error"
                            size="large"
                            startIcon={stopping ? <CircularProgress size={18} color="inherit" /> : <StopIcon />}
                            onClick={handleStop}
                            disabled={stopping}
                        >
                            {stopping ? 'Stopping…' : 'Stop'}
                        </Button>
                    )}
                    <Chip
                        label={wsConnected ? 'Live' : 'Disconnected'}
                        color={wsConnected ? 'success' : 'default'}
                        size="small"
                        variant="outlined"
                    />
                    <Box sx={{ flexGrow: 1 }} />
                    <Button
                        variant="outlined"
                        color="warning"
                        startIcon={<RestartAltIcon />}
                        onClick={openResetModal}
                    >
                        Reset Status…
                    </Button>
                </Stack>

                {resetSuccess && (
                    <Alert severity="success" sx={{ mb: 2 }} onClose={() => setResetSuccess(null)}>
                        {resetSuccess}
                    </Alert>
                )}

                {/* Optional test scope — overrides server-side env defaults for one run */}
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    Test scope (optional). Limit/Filter select which archives are registered (or re-queued);
                    parsing, extraction and thumbnails then process everything still pending.
                </Typography>
                <Stack direction="row" alignItems="center" gap={2} mb={3} flexWrap="wrap">
                    <TextField
                        select
                        label="Mode"
                        size="small"
                        value={mode}
                        onChange={e => setMode(e.target.value as 'register' | 'rerun')}
                        disabled={running || starting}
                        sx={{ minWidth: 200 }}
                        helperText="rerun re-incorporates existing archives in place"
                    >
                        <MenuItem value="register">Register new</MenuItem>
                        <MenuItem value="rerun">Re-run latest</MenuItem>
                    </TextField>
                    <TextField
                        label="Limit"
                        size="small"
                        type="number"
                        value={limit}
                        onChange={e => setLimit(e.target.value)}
                        disabled={running || starting}
                        placeholder="env default"
                        sx={{ width: 160 }}
                        helperText="newest N to register/requeue; blank = default"
                    />
                    <TextField
                        label="Filter"
                        size="small"
                        value={filter}
                        onChange={e => setFilter(e.target.value)}
                        disabled={running || starting}
                        placeholder="e.g. eran or eran_2026*"
                        sx={{ minWidth: 240 }}
                        helperText="match archive folder name"
                    />
                </Stack>

                {/* Live log panel */}
                {logs.length > 0 && (
                    <Paper
                        ref={logBoxRef}
                        sx={{
                            bgcolor: '#1a1b1e',
                            p: 2,
                            mb: 3,
                            height: 350,
                            overflowY: 'auto',
                            fontFamily: 'monospace',
                            fontSize: '0.8rem',
                            borderRadius: 1,
                        }}
                    >
                        {logs.map((line, i) => (
                            <Box key={i} sx={{ color: logLineColor(line), whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                                {line.type === 'done'
                                    ? `[${line.status?.toUpperCase()}] ${line.error ?? 'Incorporation finished.'}`
                                    : line.text}
                            </Box>
                        ))}
                    </Paper>
                )}

                {/* History table */}
                <Typography variant="h6" gutterBottom>
                    History
                </Typography>
                <TableContainer component={Paper} sx={{ maxHeight: 400, overflowY: 'auto' }}>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>ID</TableCell>
                                <TableCell>Started</TableCell>
                                <TableCell>Completed</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>User</TableCell>
                                <TableCell>IP</TableCell>
                                <TableCell>Error</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {history.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={7} align="center">No jobs yet</TableCell>
                                </TableRow>
                            ) : (
                                history.map(job => (
                                    <TableRow key={job.id}>
                                        <TableCell>{job.id}</TableCell>
                                        <TableCell>{formatDate(job.started_at)}</TableCell>
                                        <TableCell>{formatDate(job.completed_at)}</TableCell>
                                        <TableCell>
                                            <Chip
                                                label={job.status}
                                                color={STATUS_COLOR[job.status] ?? 'default'}
                                                size="small"
                                            />
                                        </TableCell>
                                        <TableCell>{job.triggered_by_user_id ?? '—'}</TableCell>
                                        <TableCell>{job.triggered_by_ip ?? '—'}</TableCell>
                                        <TableCell sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {job.error_message ?? '—'}
                                        </TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </TableContainer>
            </Box>
            </Box>

            {/* Reset incorporation status modal */}
            <Dialog open={resetOpen} onClose={() => !resetBusy && setResetOpen(false)} maxWidth="sm" fullWidth>
                <DialogTitle>Reset Incorporation Status</DialogTitle>
                <DialogContent dividers>
                    <Stack gap={2.5} sx={{ mt: 1 }}>
                        {resetError && <Alert severity="error">{resetError}</Alert>}

                        <Typography variant="body2" color="text.secondary">
                            Reverts the incorporation status of matching sessions so the next run reprocesses them.
                            This only lowers a session's status — it never skips forward — and does not delete any
                            extracted entities (re-incorporation is idempotent). Only <code>local_har</code> /{' '}
                            <code>local_wacz</code> sessions are affected.
                        </Typography>

                        <FormControl disabled={resetBusy}>
                            <FormLabel>Reset to</FormLabel>
                            <RadioGroup
                                value={resetTarget}
                                onChange={(e) => { setResetTarget(e.target.value as 'pending' | 'parsed'); invalidatePreview(); }}
                            >
                                <FormControlLabel
                                    value="pending"
                                    control={<Radio />}
                                    label="pending — re-parse HAR, then re-extract (affects parse_failed / parsed / extract_failed / done)"
                                />
                                <FormControlLabel
                                    value="parsed"
                                    control={<Radio />}
                                    label="parsed — re-extract entities from stored structures (affects extract_failed / done only)"
                                />
                            </RadioGroup>
                        </FormControl>

                        <Box>
                            <FormLabel sx={{ display: 'block', mb: 1 }}>Range (all bounds optional — blank = open-ended, combined with AND)</FormLabel>
                            <Stack direction="row" gap={2} flexWrap="wrap">
                                <TextField
                                    label="Session ID from"
                                    size="small"
                                    type="number"
                                    value={resetIdMin}
                                    onChange={(e) => { setResetIdMin(e.target.value); invalidatePreview(); }}
                                    disabled={resetBusy}
                                    sx={{ width: 160 }}
                                />
                                <TextField
                                    label="Session ID to"
                                    size="small"
                                    type="number"
                                    value={resetIdMax}
                                    onChange={(e) => { setResetIdMax(e.target.value); invalidatePreview(); }}
                                    disabled={resetBusy}
                                    sx={{ width: 160 }}
                                />
                            </Stack>
                            <Stack direction="row" gap={2} flexWrap="wrap" sx={{ mt: 2 }}>
                                <TextField
                                    label="Archived from"
                                    size="small"
                                    type="datetime-local"
                                    value={resetFrom}
                                    onChange={(e) => { setResetFrom(e.target.value); invalidatePreview(); }}
                                    disabled={resetBusy}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 220 }}
                                />
                                <TextField
                                    label="Archived to"
                                    size="small"
                                    type="datetime-local"
                                    value={resetTo}
                                    onChange={(e) => { setResetTo(e.target.value); invalidatePreview(); }}
                                    disabled={resetBusy}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 220 }}
                                />
                            </Stack>
                        </Box>

                        {resetPreviewCount !== null && (
                            <Alert severity={resetPreviewCount === 0 ? 'warning' : 'info'}>
                                {resetPreviewCount === 0
                                    ? 'No sessions match this range — nothing would be reset.'
                                    : `${resetPreviewCount} session(s) will be reset to "${resetTarget}".`}
                            </Alert>
                        )}

                        {resetPreviewCount !== null && resetPreviewCount > 0 && (
                            <TextField
                                label={`Type "${RESET_CONFIRMATION}" to confirm`}
                                fullWidth
                                autoFocus
                                value={resetConfirmText}
                                onChange={(e) => setResetConfirmText(e.target.value)}
                                disabled={resetBusy}
                                placeholder={RESET_CONFIRMATION}
                            />
                        )}
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setResetOpen(false)} disabled={resetBusy}>Cancel</Button>
                    <Button
                        variant="outlined"
                        onClick={handlePreview}
                        disabled={resetBusy}
                        startIcon={resetBusy ? <CircularProgress size={16} /> : undefined}
                    >
                        Preview
                    </Button>
                    <Button
                        variant="contained"
                        color="warning"
                        onClick={handleReset}
                        disabled={resetBusy || resetPreviewCount === null || resetPreviewCount === 0 || resetConfirmText !== RESET_CONFIRMATION}
                        startIcon={resetBusy ? <CircularProgress size={16} color="inherit" /> : undefined}
                    >
                        Reset
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
