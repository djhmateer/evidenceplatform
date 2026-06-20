import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    MenuItem,
    Paper,
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
                </Stack>

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
        </Box>
    );
}
