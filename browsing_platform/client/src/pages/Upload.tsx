import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Upload as TusUpload} from 'tus-js-client';
import cookie from 'js-cookie';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Collapse,
    FormControlLabel,
    IconButton,
    LinearProgress,
    Pagination,
    Radio,
    RadioGroup,
    Stack,
    Switch,
    Tooltip,
    Typography,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import UnfoldLessIcon from '@mui/icons-material/UnfoldLess';
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore';
import CreateNewFolderIcon from '@mui/icons-material/CreateNewFolder';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import TopNavBar from '../UIComponents/TopNavBar/TopNavBar';
import config from '../services/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Phase = 'idle' | 'scanning' | 'setup' | 'uploading' | 'done';

interface FileState {
    relativePath: string;
    file: File;
    uploadedBytes: number;
    status: 'pending' | 'hashing' | 'uploading' | 'done' | 'error';
    error?: string;
}

interface VerifyResult {
    status: 'pass' | 'fail' | 'no_checksum_file';
    results: { path: string; status: string }[];
}

interface ArchiveState {
    name: string;
    files: FileState[];
    totalBytes: number;
    uploadedBytes: number;
    hasConflict: boolean;
    resolution: 'skip' | 'overwrite';
    status: 'pending' | 'uploading' | 'verifying' | 'done' | 'failed' | 'skipped';
    verifyResult?: VerifyResult;
    expanded: boolean;
}

/** Byte offsets of a file's data within the assembled tar stream. */
interface TarFileInfo {
    relativePath: string;
    file: File;
    dataStart: number; // first byte of file content in the tar
    dataEnd: number;   // first byte after file content (non-padded)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function readAllDirEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
    const entries: FileSystemEntry[] = [];
    while (true) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (!batch.length) break;
        entries.push(...batch);
    }
    return entries;
}

async function collectFiles(entry: FileSystemEntry, prefix: string): Promise<{ relativePath: string; file: File }[]> {
    const currentPath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isFile) {
        const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
        return [{ relativePath: currentPath, file }];
    }
    const children = await readAllDirEntries((entry as FileSystemDirectoryEntry).createReader());
    const results = await Promise.all(children.map(c => collectFiles(c, currentPath)));
    return results.flat();
}

/** Scan dropped directories and call preflight. Returns ready-to-use ArchiveState list. */
async function processDroppedDirs(dirEntries: FileSystemDirectoryEntry[]): Promise<ArchiveState[]> {
    const archiveList: ArchiveState[] = [];
    for (const archiveEntry of dirEntries) {
        const children = await readAllDirEntries(archiveEntry.createReader());
        const flat = await Promise.all(children.map(c => collectFiles(c, '')));
        const fileList = flat.flat();
        const files: FileState[] = fileList.map(({ relativePath, file }): FileState => ({
            relativePath,
            file,
            uploadedBytes: 0,
            status: 'pending',
        }));
        const totalBytes = files.reduce((s, f) => s + f.file.size, 0);
        archiveList.push({
            name: archiveEntry.name,
            files,
            totalBytes,
            uploadedBytes: 0,
            hasConflict: false,
            resolution: 'skip' as ArchiveState['resolution'],
            status: 'pending' as ArchiveState['status'],
            expanded: false,
        });
    }
    const preflight = await apiPost('upload/preflight', { archives: archiveList.map(a => a.name) });
    const conflicts: Record<string, boolean> = preflight.conflicts ?? {};
    return archiveList.map((a): ArchiveState => ({
        ...a,
        hasConflict: !!conflicts[a.name],
        resolution: (conflicts[a.name] ? 'skip' : 'overwrite') as ArchiveState['resolution'],
    }));
}

/** Compute SHA-256 of a file using the browser's native Web Crypto API. */
async function computeSha256(file: File): Promise<string> {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(hashBuffer))
        .map(b => b.toString(16).padStart(2, '0'))
        .join('');
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDuration(s: number): string {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function authHeaders(): Record<string, string> {
    const token = cookie.get('token');
    return token ? { Authorization: `token:${token}` } : {};
}

async function apiPost(path: string, body?: object): Promise<any> {
    const res = await fetch(`${config.serverPath}api/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
    return res.json();
}

async function apiDelete(path: string): Promise<void> {
    await fetch(`${config.serverPath}api/${path}`, {
        method: 'DELETE',
        headers: authHeaders(),
    });
}

// ---------------------------------------------------------------------------
// Tar helpers
// ---------------------------------------------------------------------------

/**
 * Build a single 512-byte POSIX ustar header block.
 * typeFlag: '0' = regular file, 'L' = GNU long-name extension entry.
 */
function makeTarHeader(name: string, size: number, typeFlag: string = '0'): Uint8Array<ArrayBuffer> {
    const enc = new TextEncoder();
    const buf = new Uint8Array(512);

    const setStr = (off: number, maxLen: number, s: string) => {
        const b = enc.encode(s);
        buf.set(b.slice(0, maxLen), off);
    };
    const setOctal = (off: number, len: number, n: number) =>
        setStr(off, len, n.toString(8).padStart(len - 1, '0') + '\0');

    setStr(0, 100, name);
    setStr(100, 8, '0000644\0');   // mode
    setStr(108, 8, '0000000\0');   // uid
    setStr(116, 8, '0000000\0');   // gid
    setOctal(124, 12, size);       // file size
    setOctal(136, 12, Math.floor(Date.now() / 1000)); // mtime
    buf.fill(32, 148, 156);        // checksum field = spaces (required before computing)
    buf[156] = typeFlag.charCodeAt(0);
    setStr(257, 6, 'ustar\0');     // magic
    setStr(263, 2, '00');          // version

    // Compute and write checksum: sum of all 512 bytes (spaces in checksum field)
    let cs = 0;
    for (let i = 0; i < 512; i++) cs += buf[i];
    setStr(148, 8, cs.toString(8).padStart(6, '0') + '\0 ');

    return buf;
}

/**
 * Return the BlobParts that make up one complete tar entry (header(s) + data + padding)
 * and the byte count of headers preceding the data (used to calculate data offsets).
 */
function tarEntryParts(
    name: string,
    data: BlobPart,
    size: number,
): { blobParts: BlobPart[]; preDataBytes: number } {
    const enc = new TextEncoder();
    const blobParts: BlobPart[] = [];
    let preDataBytes = 0;

    const nameBytes = enc.encode(name);
    if (nameBytes.length > 100) {
        // GNU long-name extension: precede with a ././@LongLink entry
        const longNameNulled = enc.encode(name + '\0');
        const longPad = (512 - (longNameNulled.length % 512)) % 512;
        const longData = new Uint8Array(longNameNulled.length + longPad);
        longData.set(longNameNulled);
        blobParts.push(makeTarHeader('././@LongLink', longNameNulled.length, 'L'));
        blobParts.push(longData);
        preDataBytes += 512 + longData.length;
    }

    // Main header (name truncated to 100 chars; GNU long-name header above carries the full name)
    blobParts.push(makeTarHeader(name.slice(0, 100), size));
    preDataBytes += 512;

    blobParts.push(data);

    const pad = (512 - (size % 512)) % 512;
    if (pad > 0) blobParts.push(new Uint8Array(pad));

    return { blobParts, preDataBytes };
}

/**
 * Assemble a tar Blob from a manifest + file list.
 *
 * Files are referenced by their existing File handles — no data is copied into
 * a new buffer. The browser reads file bytes on-demand as TUS slices the Blob
 * into chunks, so memory overhead is only the tar headers (~512 bytes per file).
 *
 * Returns the Blob and, for each file, its data byte offsets within the stream
 * (used to back-calculate per-file upload progress from the TUS byte counter).
 */
function buildTarBlob(
    files: ReadonlyArray<{ relativePath: string; file: File }>,
    manifest: Record<string, string>,
): { blob: Blob; fileInfos: TarFileInfo[] } {
    const allParts: BlobPart[] = [];
    const fileInfos: TarFileInfo[] = [];
    let offset = 0;

    const addEntry = (name: string, data: BlobPart, size: number): number => {
        const { blobParts, preDataBytes } = tarEntryParts(name, data, size);
        const dataStart = offset + preDataBytes;
        allParts.push(...blobParts);
        const pad = (512 - (size % 512)) % 512;
        offset += preDataBytes + size + pad;
        return dataStart;
    };

    // _manifest.json is the first entry so the server can read it after extraction
    const manifestBytes = new TextEncoder().encode(JSON.stringify(manifest));
    addEntry('_manifest.json', manifestBytes, manifestBytes.length);

    for (const f of files) {
        const dataStart = addEntry(f.relativePath, f.file, f.file.size);
        fileInfos.push({ relativePath: f.relativePath, file: f.file, dataStart, dataEnd: dataStart + f.file.size });
    }

    allParts.push(new Uint8Array(1024)); // end-of-archive marker

    return { blob: new Blob(allParts), fileInfos };
}

const ITEMS_PER_PAGE = 10;
const MAX_CONCURRENT_UPLOADS = 10;
const HASH_CONCURRENCY = Math.min(navigator.hardwareConcurrency || 4, 8);

async function runConcurrently<T>(
    tasks: (() => Promise<T>)[],
    limit: number,
): Promise<PromiseSettledResult<T>[]> {
    const results: Promise<T>[] = [];
    const executing = new Set<Promise<T>>();
    for (const task of tasks) {
        const p = Promise.resolve().then(task);
        results.push(p);
        executing.add(p);
        p.finally(() => executing.delete(p));
        while (executing.size >= limit) await Promise.race(executing).catch(() => {});
    }
    return Promise.allSettled(results);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UploadPage() {
    const [phase, setPhase] = useState<Phase>('idle');
    const [archives, setArchives] = useState<ArchiveState[]>([]);
    const [scanError, setScanError] = useState<string | null>(null);
    const [hideSkipped, setHideSkipped] = useState(false);
    const [currentPage, setCurrentPage] = useState(1);
    const [isDragActive, setIsDragActive] = useState(false);
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    const [isAddingMore, setIsAddingMore] = useState(false);

    const activeUploadsRef = useRef<Map<string, TusUpload>>(new Map());
    const cancelledRef = useRef(false);
    const dragCounterRef = useRef(0);
    const uploadStartTimeRef = useRef<number>(0);
    const speedSamplesRef = useRef<{ time: number; bytes: number }[]>([]);
    const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    // Mirrors `archives` for read-only access from network/timer callbacks where the
    // closure-captured value can lag behind unflushed setArchives updates.
    const archivesRef = useRef<ArchiveState[]>(archives);
    archivesRef.current = archives;

    useEffect(() => {
        document.title = 'Upload | Browsing Platform';
    }, []);

    const isUploading = phase === 'uploading';

    // Warn on browser close / refresh while uploading
    useEffect(() => {
        if (!isUploading) return;
        const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
        window.addEventListener('beforeunload', handler);
        return () => window.removeEventListener('beforeunload', handler);
    }, [isUploading]);

    // Abort active TUS transfers if the component unmounts mid-upload (in-app navigation)
    useEffect(() => {
        return () => {
            if (activeUploadsRef.current.size > 0) {
                cancelledRef.current = true;
                for (const upload of activeUploadsRef.current.values()) {
                    Promise.resolve(upload.abort(true)).catch(() => {});
                }
                activeUploadsRef.current.clear();
            }
            if (elapsedIntervalRef.current) clearInterval(elapsedIntervalRef.current);
        };
    }, []);

    // -----------------------------------------------------------------------
    // State helpers
    // -----------------------------------------------------------------------

    const setArchiveStatus = (archiveName: string, update: Partial<ArchiveState>) =>
        setArchives(prev => prev.map(a => a.name !== archiveName ? a : { ...a, ...update }));

    const updateArchiveFiles = (archiveName: string, fileMapper: (f: FileState) => FileState) =>
        setArchives(prev => prev.map(a =>
            a.name !== archiveName ? a : { ...a, files: a.files.map(fileMapper) }
        ));

    // -----------------------------------------------------------------------
    // Drop handling (full-page)
    // -----------------------------------------------------------------------

    const handlePageDragEnter = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        dragCounterRef.current += 1;
        if (dragCounterRef.current === 1) setIsDragActive(true);
    }, []);

    const handlePageDragLeave = useCallback(() => {
        dragCounterRef.current -= 1;
        if (dragCounterRef.current === 0) setIsDragActive(false);
    }, []);

    const handlePageDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    }, []);

    const handlePageDrop = useCallback(async (e: React.DragEvent) => {
        e.preventDefault();
        dragCounterRef.current = 0;
        setIsDragActive(false);
        const wasIdle = phase === 'idle';
        if (!wasIdle && phase !== 'setup') return;

        const items = Array.from(e.dataTransfer.items);
        const dirEntries = items
            .map(item => item.webkitGetAsEntry())
            .filter((entry): entry is FileSystemDirectoryEntry => !!entry && entry.isDirectory);

        if (!dirEntries.length) {
            if (wasIdle) setScanError('No folders detected. Please drop one or more archive folders.');
            return;
        }

        if (wasIdle) {
            setScanError(null);
            setPhase('scanning');
        } else {
            setIsAddingMore(true);
        }

        try {
            const newArchives = await processDroppedDirs(dirEntries);
            if (wasIdle) {
                setArchives(newArchives);
                setHideSkipped(false);
                setCurrentPage(1);
                setPhase('setup');
            } else {
                setArchives(prev => {
                    const existingNames = new Set(prev.map(a => a.name));
                    const toAdd = newArchives.filter(a => !existingNames.has(a.name));
                    return [...prev, ...toAdd];
                });
            }
        } catch (err) {
            if (wasIdle) {
                setScanError(`Failed to scan folders: ${err instanceof Error ? err.message : String(err)}`);
                setPhase('idle');
            }
        } finally {
            setIsAddingMore(false);
        }
    }, [phase]);

    // -----------------------------------------------------------------------
    // Bulk conflict toggle
    // -----------------------------------------------------------------------

    const bulkAllSkip = archives.filter(a => a.hasConflict).every(a => a.resolution === 'skip');

    const toggleBulkResolution = () => {
        const newResolution = bulkAllSkip ? 'overwrite' : 'skip';
        setArchives(prev => prev.map(a => a.hasConflict ? { ...a, resolution: newResolution } : a));
    };

    // -----------------------------------------------------------------------
    // Upload — tar-based
    // -----------------------------------------------------------------------

    /**
     * Hash every file, build a tar Blob (zero-copy — files referenced, not buffered),
     * and stream-upload via a single TUS session. Per-file progress is derived from
     * the tar byte offset reported by TUS.
     */
    const uploadArchiveAsTar = async (archive: ArchiveState): Promise<void> => {
        // Bounded parallel hashing: many small PAR2 sidecars per archive make sequential
        // hashing the dominant cost; concurrent subtle.digest calls pipeline reads + crypto.
        const manifest: Record<string, string> = {};
        const hashTasks = archive.files.map(f => async () => {
            if (cancelledRef.current) throw new Error('cancelled');
            setArchives(prev => prev.map(a =>
                a.name !== archive.name ? a : {
                    ...a,
                    files: a.files.map(af =>
                        af.relativePath === f.relativePath ? { ...af, status: 'hashing' } : af
                    ),
                }
            ));
            manifest[f.relativePath] = await computeSha256(f.file);
        });
        const hashResults = await runConcurrently(hashTasks, HASH_CONCURRENCY);

        if (cancelledRef.current) throw new Error('cancelled');
        const failedHash = hashResults.find((r): r is PromiseRejectedResult => r.status === 'rejected');
        if (failedHash) throw failedHash.reason;

        const { blob: tarBlob, fileInfos } = buildTarBlob(archive.files, manifest);
        const infoByPath = new Map(fileInfos.map(fi => [fi.relativePath, fi]));

        updateArchiveFiles(archive.name, af => ({ ...af, status: 'uploading', uploadedBytes: 0 }));

        return new Promise<void>((resolve, reject) => {
            const upload = new TusUpload(tarBlob, {
                endpoint: `${config.serverPath}api/upload/tus/`,
                chunkSize: 5 * 1024 * 1024,
                retryDelays: [0, 1000, 3000, 5000, 10000],
                removeFingerprintOnSuccess: true,
                metadata: { archiveName: archive.name, uploadMode: 'tar' },
                headers: authHeaders(),
                onProgress: (uploadedTarBytes: number) => {
                    setArchives(prev => prev.map(a => {
                        if (a.name !== archive.name) return a;
                        let changed = false;
                        const files = a.files.map(af => {
                            const fi = infoByPath.get(af.relativePath);
                            if (!fi) return af;
                            const uploaded = Math.min(Math.max(0, uploadedTarBytes - fi.dataStart), fi.file.size);
                            const status: FileState['status'] = uploaded >= fi.file.size ? 'done'
                                : uploaded > 0 ? 'uploading' : 'pending';
                            if (uploaded === af.uploadedBytes && status === af.status) return af;
                            changed = true;
                            return { ...af, uploadedBytes: uploaded, status };
                        });
                        if (!changed) return a;
                        const uploadedBytes = files.reduce((s, af) => s + af.uploadedBytes, 0);
                        return { ...a, files, uploadedBytes };
                    }));
                },
                onSuccess: () => {
                    // Force-mark everything done; rounding can leave the last file short of its size.
                    setArchives(prev => prev.map(a =>
                        a.name !== archive.name ? a : {
                            ...a,
                            uploadedBytes: a.totalBytes,
                            files: a.files.map(af => ({ ...af, status: 'done', uploadedBytes: af.file.size })),
                        }
                    ));
                    activeUploadsRef.current.delete(archive.name);
                    resolve();
                },
                onError: (err) => {
                    const msg = err instanceof Error ? err.message : String(err);
                    updateArchiveFiles(archive.name, af => ({ ...af, status: 'error', error: msg }));
                    activeUploadsRef.current.delete(archive.name);
                    reject(err);
                },
            });

            activeUploadsRef.current.set(archive.name, upload);
            upload.start();
        });
    };

    const startUpload = async () => {
        cancelledRef.current = false;

        uploadStartTimeRef.current = Date.now();
        speedSamplesRef.current = [];
        setElapsedSeconds(0);
        elapsedIntervalRef.current = setInterval(() => {
            const now = Date.now();
            setElapsedSeconds(Math.floor((now - uploadStartTimeRef.current) / 1000));
            const totalUploaded = archivesRef.current.reduce((s, a) => s + a.uploadedBytes, 0);
            speedSamplesRef.current.push({ time: now, bytes: totalUploaded });
            speedSamplesRef.current = speedSamplesRef.current.filter(s => s.time >= now - 60_000);
        }, 1000);

        setPhase('uploading');

        const archivesToUpload = archives.filter(a => a.resolution !== 'skip' || !a.hasConflict);

        setArchives(prev => prev.map(a =>
            (a.hasConflict && a.resolution === 'skip') ? { ...a, status: 'skipped' } : a
        ));

        const processArchive = async (archive: ArchiveState) => {
            if (cancelledRef.current) return;
            setArchiveStatus(archive.name, { status: 'uploading' });

            await apiDelete(`upload/staging/${archive.name}`).catch(() => {});

            try {
                await uploadArchiveAsTar(archive);
            } catch {
                if (!cancelledRef.current) setArchiveStatus(archive.name, { status: 'failed' });
                return;
            }

            if (cancelledRef.current) return;

            setArchiveStatus(archive.name, { status: 'verifying' });
            try {
                const verifyResult: VerifyResult = await apiPost(`upload/verify/${archive.name}`);
                if (verifyResult.status === 'pass' || verifyResult.status === 'no_checksum_file') {
                    await apiPost(`upload/commit/${archive.name}`);
                    setArchiveStatus(archive.name, { status: 'done', verifyResult });
                } else {
                    setArchiveStatus(archive.name, { status: 'failed', verifyResult });
                }
            } catch (err) {
                setArchiveStatus(archive.name, {
                    status: 'failed',
                    verifyResult: { status: 'fail', results: [{ path: '', status: `Error: ${err}` }] },
                });
            }
        };

        await runConcurrently(archivesToUpload.map(a => () => processArchive(a)), MAX_CONCURRENT_UPLOADS);

        if (elapsedIntervalRef.current) {
            clearInterval(elapsedIntervalRef.current);
            elapsedIntervalRef.current = null;
        }

        if (!cancelledRef.current) setPhase('done');
    };

    // -----------------------------------------------------------------------
    // Cancel
    // -----------------------------------------------------------------------

    const cancel = async () => {
        cancelledRef.current = true;
        dragCounterRef.current = 0;
        setIsDragActive(false);

        if (elapsedIntervalRef.current) {
            clearInterval(elapsedIntervalRef.current);
            elapsedIntervalRef.current = null;
        }

        for (const upload of activeUploadsRef.current.values()) {
            Promise.resolve(upload.abort(true)).catch(() => {});
        }
        activeUploadsRef.current.clear();

        const inProgress = archivesRef.current.filter(a => a.status === 'uploading' || a.status === 'verifying');
        await Promise.allSettled(
            inProgress.map(a => apiDelete(`upload/staging/${a.name}`).catch(() => {}))
        );

        setArchives([]);
        setPhase('idle');
    };

    // -----------------------------------------------------------------------
    // Retry failed archives
    // -----------------------------------------------------------------------

    const cleanupFailed = async () => {
        const failedArchives = archivesRef.current.filter(a => a.status === 'failed');
        await Promise.allSettled(
            failedArchives.map(a => apiDelete(`upload/staging/${a.name}`).catch(() => {}))
        );
        const remaining = archivesRef.current.filter(a => a.status !== 'failed');
        if (remaining.length === 0 || remaining.every(a => a.status === 'skipped')) {
            setArchives([]);
            setPhase('idle');
        } else {
            setArchives(remaining);
        }
    };

    const retryFailed = () => {
        dragCounterRef.current = 0;
        setArchives(prev => prev.map(a =>
            a.status === 'failed' ? {
                ...a,
                status: 'pending',
                uploadedBytes: 0,
                files: a.files.map(f => ({ ...f, uploadedBytes: 0, status: 'pending', error: undefined })),
                verifyResult: undefined,
            } : a
        ));
        setCurrentPage(1);
        setPhase('setup');
    };

    // -----------------------------------------------------------------------
    // Derived values for upload phase
    // -----------------------------------------------------------------------

    const totalBytesToUpload = archives
        .filter(a => a.status !== 'skipped')
        .reduce((s, a) => s + a.totalBytes, 0);
    const totalBytesUploaded = archives
        .filter(a => a.status !== 'skipped')
        .reduce((s, a) => s + a.uploadedBytes, 0);
    const overallPct = totalBytesToUpload > 0
        ? Math.round((totalBytesUploaded / totalBytesToUpload) * 100)
        : 0;

    const samples = speedSamplesRef.current;
    let speedBytesPerSec = 0;
    let etaSeconds: number | null = null;
    if (samples.length >= 2) {
        const dt = (samples[samples.length - 1].time - samples[0].time) / 1000;
        if (dt > 0) {
            speedBytesPerSec = (samples[samples.length - 1].bytes - samples[0].bytes) / dt;
            const remaining = totalBytesToUpload - totalBytesUploaded;
            etaSeconds = speedBytesPerSec > 0 ? Math.ceil(remaining / speedBytesPerSec) : null;
        }
    }

    // -----------------------------------------------------------------------
    // Render helpers
    // -----------------------------------------------------------------------

    const statusChip = (status: ArchiveState['status']) => {
        const map: Record<string, { label: string; color: 'default' | 'info' | 'warning' | 'success' | 'error' }> = {
            pending: { label: 'Pending', color: 'default' },
            uploading: { label: 'Uploading', color: 'info' },
            verifying: { label: 'Verifying', color: 'warning' },
            done: { label: 'Done', color: 'success' },
            failed: { label: 'Failed', color: 'error' },
            skipped: { label: 'Skipped', color: 'default' },
        };
        const { label, color } = map[status] ?? { label: status, color: 'default' };
        return <Chip label={label} color={color} size="small" />;
    };

    const pct = (a: ArchiveState) =>
        a.totalBytes > 0 ? Math.round((a.uploadedBytes / a.totalBytes) * 100) : 0;

    const doneSummary = () => {
        const done = archives.filter(a => a.status === 'done').length;
        const failed = archives.filter(a => a.status === 'failed').length;
        const skipped = archives.filter(a => a.status === 'skipped').length;
        return { done, failed, skipped };
    };

    const activeSetupArchives = archives.filter(a => !(a.hasConflict && a.resolution === 'skip'));
    const hasAnySkipped = archives.some(a => a.hasConflict && a.resolution === 'skip');
    const visibleSetupArchives = hideSkipped ? activeSetupArchives : archives;

    const paginate = <T,>(items: T[]): T[] =>
        items.slice((currentPage - 1) * ITEMS_PER_PAGE, currentPage * ITEMS_PER_PAGE);

    const setupPageItems = paginate(visibleSetupArchives);
    const uploadingPageItems = paginate(archives);
    const donePageItems = paginate(archives);

    const renderPagination = (totalCount: number) =>
        totalCount > ITEMS_PER_PAGE ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', pt: 1 }}>
                <Pagination
                    count={Math.ceil(totalCount / ITEMS_PER_PAGE)}
                    page={currentPage}
                    onChange={(_, p) => setCurrentPage(p)}
                    color="primary"
                />
            </Box>
        ) : null;

    // -----------------------------------------------------------------------
    // Render
    // -----------------------------------------------------------------------

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
            <TopNavBar>
                <Typography variant="h6" sx={{ color: 'white' }}>Upload Archives</Typography>
            </TopNavBar>

            {/* Scroll container — also the full-page drag target */}
            <Box
                onDragEnter={handlePageDragEnter}
                onDragLeave={handlePageDragLeave}
                onDragOver={handlePageDragOver}
                onDrop={handlePageDrop}
                sx={{ flex: 1, overflow: 'auto', position: 'relative' }}
            >
                <Box sx={{ maxWidth: 900, mx: 'auto', p: 3 }}>

                    {/* ── IDLE ── */}
                    {phase === 'idle' && (
                        <Box
                            sx={{
                                border: '2px dashed',
                                borderColor: 'divider',
                                borderRadius: 2,
                                p: 8,
                                textAlign: 'center',
                                cursor: 'copy',
                                transition: 'border-color 0.2s',
                                '&:hover': { borderColor: 'primary.main' },
                            }}
                        >
                            <CloudUploadIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
                            <Typography variant="h6" gutterBottom>Drop archive folders here</Typography>
                            <Typography variant="body2" color="text.secondary">
                                You can drop multiple archive folders at once.
                            </Typography>
                            {scanError && <Alert severity="error" sx={{ mt: 2 }}>{scanError}</Alert>}
                        </Box>
                    )}

                    {/* ── SCANNING ── */}
                    {phase === 'scanning' && (
                        <Stack alignItems="center" gap={2} sx={{ py: 8 }}>
                            <CircularProgress />
                            <Typography>Scanning folder structure…</Typography>
                        </Stack>
                    )}

                    {/* ── SETUP ── */}
                    {phase === 'setup' && (
                        <Stack gap={2}>
                            {/* Header */}
                            <Stack direction="row" alignItems="baseline" gap={1}>
                                <Typography variant="h6">
                                    {archives.length} archive{archives.length !== 1 ? 's' : ''} detected
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                    ({activeSetupArchives.reduce((s, a) => s + a.files.length, 0)} files,{' '}
                                    {formatBytes(activeSetupArchives.reduce((s, a) => s + a.totalBytes, 0))}{' '}
                                    {activeSetupArchives.length < archives.length ? 'to upload' : 'total'})
                                </Typography>
                            </Stack>

                            {/* Action buttons — always at top */}
                            <Stack direction="row" gap={2}>
                                <Button variant="contained" size="large" onClick={startUpload}>
                                    Start Upload
                                </Button>
                                <Button variant="outlined" onClick={() => { setArchives([]); setPhase('idle'); }}>
                                    Cancel
                                </Button>
                            </Stack>

                            {/* Conflict alert */}
                            {archives.some(a => a.hasConflict) && (
                                <Alert
                                    severity="warning"
                                    action={
                                        <FormControlLabel
                                            control={
                                                <Tooltip title={bulkAllSkip
                                                    ? 'Existing archives will be skipped'
                                                    : 'Existing archives will be overridden'
                                                }>
                                                    <Switch checked={!bulkAllSkip} onChange={toggleBulkResolution} />
                                                </Tooltip>
                                            }
                                            label="Re-upload existing archives"
                                            sx={{ mr: 0 }}
                                        />
                                    }
                                >
                                    Some archives already exist in the destination.
                                </Alert>
                            )}

                            {/* Hide skipped button */}
                            {archives.some(a => a.hasConflict) && (
                                <Box>
                                    <Button
                                        size="small"
                                        variant="outlined"
                                        startIcon={<VisibilityOffIcon />}
                                        disabled={!hasAnySkipped}
                                        onClick={() => { setHideSkipped(p => !p); setCurrentPage(1); }}
                                    >
                                        {hideSkipped ? 'Show skipped' : 'Hide skipped'}
                                    </Button>
                                </Box>
                            )}

                            {/* Archive cards (paginated) */}
                            {setupPageItems.map(archive => (
                                <Card key={archive.name} variant="outlined">
                                    <CardContent>
                                        <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1}>
                                            <Stack gap={0.5}>
                                                <Typography variant="subtitle1" fontWeight="bold">{archive.name}</Typography>
                                                <Typography variant="body2" color="text.secondary">
                                                    {archive.files.length} files · {formatBytes(archive.totalBytes)}
                                                </Typography>
                                            </Stack>
                                            {archive.hasConflict ? (
                                                <Stack direction="row" alignItems="center" gap={1}>
                                                    <Chip label="Already exists" color="warning" size="small" icon={<WarningIcon />} />
                                                    <RadioGroup
                                                        row
                                                        value={archive.resolution}
                                                        onChange={(_, v) => setArchiveStatus(archive.name, { resolution: v as 'skip' | 'overwrite' })}
                                                    >
                                                        <FormControlLabel value="skip" control={<Radio size="small" />} label="Skip" />
                                                        <FormControlLabel value="overwrite" control={<Radio size="small" />} label="Overwrite" />
                                                    </RadioGroup>
                                                </Stack>
                                            ) : <Chip label="New archive" color="primary" size="small" icon={<CreateNewFolderIcon />} />}
                                        </Stack>
                                    </CardContent>
                                </Card>
                            ))}

                            {renderPagination(visibleSetupArchives.length)}

                            {isAddingMore && (
                                <Stack direction="row" alignItems="center" justifyContent="center" gap={1}>
                                    <CircularProgress size={16} />
                                    <Typography variant="body2" color="text.secondary">
                                        Scanning additional folders…
                                    </Typography>
                                </Stack>
                            )}

                            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center' }}>
                                Drop additional archive folders here to add them
                            </Typography>
                        </Stack>
                    )}

                    {/* ── UPLOADING ── */}
                    {phase === 'uploading' && (
                        <Stack gap={2}>
                            {/* Cancel — always visible above accordion */}
                            <Stack direction="row" justifyContent="space-between" alignItems="center">
                                <Typography variant="h6">Uploading…</Typography>
                                <Button color="error" variant="outlined" onClick={cancel}>Cancel</Button>
                            </Stack>

                            <Accordion defaultExpanded={false} disableGutters>
                                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                    <Stack sx={{ width: '100%', pr: 1 }} gap={0.5}>
                                        <Tooltip title={speedBytesPerSec > 0
                                            ? `${formatBytes(Math.round(speedBytesPerSec))}/s`
                                            : 'Calculating speed…'
                                        }>
                                            <span>
                                                <LinearProgress
                                                    variant="determinate"
                                                    value={overallPct}
                                                    sx={{ height: 8, borderRadius: 1 }}
                                                />
                                            </span>
                                        </Tooltip>
                                        <Stack direction="row" justifyContent="space-between">
                                            <Typography variant="caption" color="text.secondary">
                                                {formatBytes(totalBytesUploaded)} / {formatBytes(totalBytesToUpload)} ({overallPct}%)
                                            </Typography>
                                            <Stack direction="row" gap={2}>
                                                <Typography variant="caption" color="text.secondary">
                                                    Elapsed: {formatDuration(elapsedSeconds)}
                                                </Typography>
                                                {etaSeconds !== null && (
                                                    <Typography variant="caption" color="text.secondary">
                                                        ETA: {formatDuration(etaSeconds)}
                                                    </Typography>
                                                )}
                                            </Stack>
                                        </Stack>
                                    </Stack>
                                </AccordionSummary>

                                <AccordionDetails sx={{ p: 0 }}>
                                    <Stack direction="row" justifyContent="flex-end" gap={1} sx={{ px: 2, pb: 1 }}>
                                        <Button
                                            size="small"
                                            startIcon={<UnfoldLessIcon />}
                                            onClick={() => setArchives(prev => prev.map(a => ({ ...a, expanded: false })))}
                                        >
                                            Collapse all
                                        </Button>
                                        <Button
                                            size="small"
                                            startIcon={<UnfoldMoreIcon />}
                                            onClick={() => setArchives(prev => prev.map(a => ({ ...a, expanded: true })))}
                                        >
                                            Expand all
                                        </Button>
                                    </Stack>

                                    <Stack gap={1} sx={{ px: 2, pb: 1 }}>
                                        {uploadingPageItems.map(archive => (
                                            <Card key={archive.name} variant="outlined">
                                                <CardContent>
                                                    <Stack direction="row" alignItems="center" gap={1} mb={1}>
                                                        <Typography variant="subtitle1" fontWeight="bold" sx={{ flex: 1 }}>
                                                            {archive.name}
                                                        </Typography>
                                                        {statusChip(archive.status)}
                                                        {(archive.status === 'uploading' || archive.status === 'verifying') && (
                                                            <CircularProgress size={16} />
                                                        )}
                                                        <Tooltip title={archive.expanded ? 'Hide files' : 'Show files'}>
                                                            <IconButton size="small" onClick={() => setArchiveStatus(archive.name, { expanded: !archive.expanded })}>
                                                                {archive.expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                                                            </IconButton>
                                                        </Tooltip>
                                                    </Stack>

                                                    {archive.status !== 'skipped' && (
                                                        <>
                                                            <LinearProgress
                                                                variant="determinate"
                                                                value={pct(archive)}
                                                                sx={{ mb: 0.5 }}
                                                            />
                                                            <Typography variant="caption" color="text.secondary">
                                                                {formatBytes(archive.uploadedBytes)} / {formatBytes(archive.totalBytes)} ({pct(archive)}%)
                                                            </Typography>
                                                        </>
                                                    )}

                                                    {archive.status === 'failed' && archive.verifyResult && (
                                                        <Alert severity="error" sx={{ mt: 1 }}>
                                                            Checksum verification failed for{' '}
                                                            {archive.verifyResult.results.filter(r => r.status !== 'pass').length} file(s).
                                                        </Alert>
                                                    )}

                                                    <Collapse in={archive.expanded}>
                                                        <Stack gap={0.5} mt={1}>
                                                            {archive.files.map(f => (
                                                                <Stack key={f.relativePath} direction="row" alignItems="center" gap={1}>
                                                                    {f.status === 'done' && <CheckCircleIcon fontSize="small" color="success" />}
                                                                    {f.status === 'error' && <ErrorIcon fontSize="small" color="error" />}
                                                                    {(f.status === 'uploading' || f.status === 'hashing' || f.status === 'pending') && (
                                                                        <Box sx={{ width: 20, display: 'flex', justifyContent: 'center' }}>
                                                                            {(f.status === 'uploading' || f.status === 'hashing')
                                                                                ? <CircularProgress size={14} />
                                                                                : <Box sx={{ width: 14, height: 14 }} />}
                                                                        </Box>
                                                                    )}
                                                                    <Typography variant="caption" sx={{ flex: 1, fontFamily: 'monospace' }}>
                                                                        {f.relativePath}
                                                                    </Typography>
                                                                    <Typography variant="caption" color="text.secondary">
                                                                        {f.status === 'hashing'
                                                                            ? 'Hashing…'
                                                                            : `${formatBytes(f.uploadedBytes)} / ${formatBytes(f.file.size)}`}
                                                                    </Typography>
                                                                </Stack>
                                                            ))}
                                                        </Stack>
                                                    </Collapse>
                                                </CardContent>
                                            </Card>
                                        ))}
                                    </Stack>

                                    {renderPagination(archives.length)}
                                </AccordionDetails>
                            </Accordion>
                        </Stack>
                    )}

                    {/* ── DONE ── */}
                    {phase === 'done' && (() => {
                        const { done, failed, skipped } = doneSummary();
                        const totalTransferred = archives
                            .filter(a => a.status === 'done')
                            .reduce((s, a) => s + a.totalBytes, 0);
                        return (
                            <Stack gap={2}>
                                <Typography variant="h6">Upload complete</Typography>
                                <Stack direction="row" gap={1}>
                                    {done > 0 && <Chip label={`${done} uploaded`} color="success" icon={<CheckCircleIcon />} />}
                                    {failed > 0 && <Chip label={`${failed} failed`} color="error" icon={<ErrorIcon />} />}
                                    {skipped > 0 && <Chip label={`${skipped} skipped`} color="default" />}
                                </Stack>
                                {totalTransferred > 0 && (
                                    <Typography variant="body2" color="text.secondary">
                                        Total data transferred: {formatBytes(totalTransferred)}
                                    </Typography>
                                )}

                                {donePageItems.map(archive => (
                                    <Card key={archive.name} variant="outlined">
                                        <CardContent>
                                            <Stack direction="row" alignItems="center" gap={1}>
                                                <Typography variant="subtitle1" fontWeight="bold" sx={{ flex: 1 }}>
                                                    {archive.name}
                                                </Typography>
                                                {statusChip(archive.status)}
                                            </Stack>
                                            {archive.verifyResult?.status === 'fail' && (
                                                <Alert severity="error" sx={{ mt: 1 }}>
                                                    <Typography variant="body2" fontWeight="bold">Failed files:</Typography>
                                                    {archive.verifyResult.results
                                                        .filter(r => r.status !== 'pass')
                                                        .map(r => (
                                                            <Typography key={r.path} variant="caption" component="div" fontFamily="monospace">
                                                                {r.path} — {r.status}
                                                            </Typography>
                                                        ))}
                                                </Alert>
                                            )}
                                        </CardContent>
                                    </Card>
                                ))}

                                {renderPagination(archives.length)}

                                <Stack direction="row" gap={2}>
                                    <Button variant="outlined" onClick={() => { setArchives([]); setPhase('idle'); }}>
                                        Upload more
                                    </Button>
                                    {failed > 0 && (
                                        <>
                                            <Button variant="outlined" color="error" onClick={cleanupFailed}>
                                                Clean up failed
                                            </Button>
                                            <Button variant="contained" color="warning" onClick={retryFailed}>
                                                Retry failed
                                            </Button>
                                        </>
                                    )}
                                </Stack>
                            </Stack>
                        );
                    })()}
                </Box>

                {/* Full-page drag overlay */}
                {isDragActive && phase === 'idle' && (
                    <Box sx={{
                        position: 'absolute',
                        inset: 0,
                        border: '4px dashed',
                        borderColor: 'primary.main',
                        borderRadius: 2,
                        bgcolor: 'rgba(25, 118, 210, 0.08)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 10,
                        pointerEvents: 'none',
                    }}>
                        <Stack alignItems="center" gap={2}>
                            <CloudUploadIcon sx={{ fontSize: 80, color: 'primary.main' }} />
                            <Typography variant="h5" color="primary">Drop archive folders here</Typography>
                        </Stack>
                    </Box>
                )}
            </Box>
        </Box>
    );
}
