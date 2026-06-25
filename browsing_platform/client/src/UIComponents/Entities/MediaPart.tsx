import React, {useRef, useState} from 'react';
import {useLocation, useSearchParams} from "react-router";
import {IMedia, IMediaPart} from "../../types/entities";
import {
    Box,
    Button,
    Card,
    CardContent,
    CircularProgress,
    Divider,
    IconButton,
    Link,
    Slider,
    Stack,
    Tooltip,
    Typography
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/Edit";
import SaveIcon from "@mui/icons-material/Save";
import {anchor_local_static_files} from "../../services/server";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import {deleteMediaPart, saveMediaPart} from "../../services/DataSaver";
import EntityAnnotator from "./Annotator";
import InlineTagsDisplay from "../Tags/InlineTagsDisplay";
import CroppedMediaView from "./CroppedMediaView";
import {formatTime} from "../../lib/timeFormat";

// crop_area is [left%, right%, bottom%, top%] with the vertical axis measured from the BOTTOM of
// the frame. All drag math is done in a top-left rect ({x, y, w, h} in %) and converted once at
// the boundary, which keeps the geometry readable.
const MIN_SIZE = 3;

type Rect = { x: number; y: number; w: number; h: number };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function rectFromCrop(crop?: number[]): Rect {
    const c = crop && crop.length === 4 ? crop : [0, 100, 0, 100];
    return {x: c[0], y: 100 - c[3], w: c[1] - c[0], h: c[3] - c[2]};
}

function cropFromRect(r: Rect): number[] {
    return [r.x, r.x + r.w, 100 - (r.y + r.h), 100 - r.y];
}

const HANDLES: { dir: string; cursor: string; style: React.CSSProperties }[] = [
    {dir: "nw", cursor: "nwse-resize", style: {top: 0, left: 0}},
    {dir: "n", cursor: "ns-resize", style: {top: 0, left: "50%"}},
    {dir: "ne", cursor: "nesw-resize", style: {top: 0, left: "100%"}},
    {dir: "e", cursor: "ew-resize", style: {top: "50%", left: "100%"}},
    {dir: "se", cursor: "nwse-resize", style: {top: "100%", left: "100%"}},
    {dir: "s", cursor: "ns-resize", style: {top: "100%", left: "50%"}},
    {dir: "sw", cursor: "nesw-resize", style: {top: "100%", left: 0}},
    {dir: "w", cursor: "ew-resize", style: {top: "50%", left: 0}},
];

function CropRectEditor({mediaType, localUrl, cropArea, onChange, videoRef, imageRef, onLoaded}: {
    mediaType: string;
    localUrl: string | undefined;
    cropArea: number[] | undefined;
    onChange: (crop: number[]) => void;
    videoRef: React.RefObject<HTMLVideoElement | null>;
    imageRef: React.RefObject<HTMLImageElement | null>;
    onLoaded: () => void;
}) {
    const containerRef = useRef<HTMLDivElement>(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;

    const rect = rectFromCrop(cropArea);

    const pointerPct = (clientX: number, clientY: number) => {
        const el = containerRef.current;
        if (!el) return {x: 0, y: 0};
        const b = el.getBoundingClientRect();
        return {
            x: clamp((clientX - b.left) / b.width * 100, 0, 100),
            y: clamp((clientY - b.top) / b.height * 100, 0, 100),
        };
    };

    const beginDrag = (mode: string) => (e: React.MouseEvent) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        const startRect = rectFromCrop(cropArea);
        const start = pointerPct(e.clientX, e.clientY);

        const onMove = (ev: MouseEvent) => {
            const p = pointerPct(ev.clientX, ev.clientY);
            let nr: Rect;
            if (mode === "draw") {
                const x0 = Math.min(start.x, p.x), x1 = Math.max(start.x, p.x);
                const y0 = Math.min(start.y, p.y), y1 = Math.max(start.y, p.y);
                nr = {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
            } else if (mode === "move") {
                nr = {
                    ...startRect,
                    x: clamp(startRect.x + (p.x - start.x), 0, 100 - startRect.w),
                    y: clamp(startRect.y + (p.y - start.y), 0, 100 - startRect.h),
                };
            } else {
                const dir = mode.slice(7); // "resize-XX"
                let left = startRect.x, right = startRect.x + startRect.w;
                let top = startRect.y, bottom = startRect.y + startRect.h;
                if (dir.includes("w")) left = Math.min(p.x, right - MIN_SIZE);
                if (dir.includes("e")) right = Math.max(p.x, left + MIN_SIZE);
                if (dir.includes("n")) top = Math.min(p.y, bottom - MIN_SIZE);
                if (dir.includes("s")) bottom = Math.max(p.y, top + MIN_SIZE);
                nr = {x: left, y: top, w: right - left, h: bottom - top};
            }
            nr.w = clamp(nr.w, MIN_SIZE, 100);
            nr.h = clamp(nr.h, MIN_SIZE, 100);
            nr.x = clamp(nr.x, 0, 100 - nr.w);
            nr.y = clamp(nr.y, 0, 100 - nr.h);
            onChangeRef.current(cropFromRect(nr));
        };
        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    };

    return (
        <Box
            ref={containerRef}
            onMouseDown={beginDrag("draw")}
            sx={{
                position: "relative",
                overflow: "hidden",
                width: "100%",
                maxWidth: 480,
                borderRadius: 1,
                bgcolor: "#000",
                cursor: "crosshair",
                userSelect: "none",
                lineHeight: 0,
            }}
        >
            {mediaType === "video" ? (
                <video ref={videoRef} src={localUrl} onLoadedMetadata={onLoaded}
                       style={{width: "100%", display: "block", pointerEvents: "none"}}/>
            ) : (
                <img ref={imageRef} src={localUrl} alt="media part" onLoad={onLoaded} draggable={false}
                     style={{width: "100%", display: "block", pointerEvents: "none"}}/>
            )}

            {/* Selected region: a clear window cut into a dimming mask, with drag handles. */}
            <Box
                onMouseDown={beginDrag("move")}
                sx={{
                    position: "absolute",
                    left: `${rect.x}%`,
                    top: `${rect.y}%`,
                    width: `${rect.w}%`,
                    height: `${rect.h}%`,
                    boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
                    outline: "1px solid rgba(255,255,255,0.9)",
                    cursor: "move",
                }}
            >
                {HANDLES.map(h => (
                    <Box
                        key={h.dir}
                        onMouseDown={beginDrag("resize-" + h.dir)}
                        sx={{
                            position: "absolute",
                            ...h.style,
                            width: 12,
                            height: 12,
                            transform: "translate(-50%, -50%)",
                            bgcolor: "#fff",
                            border: "1px solid rgba(0,0,0,0.5)",
                            borderRadius: "2px",
                            cursor: h.cursor,
                        }}
                    />
                ))}
            </Box>
        </Box>
    );
}

interface IProps {
    media: IMedia
    mediaPart: IMediaPart
    index?: number
    onDelete: () => void
    onSaved?: (saved: IMediaPart) => void
    viewerConfig?: EntityViewerConfig
}

export default function MediaPart({media, mediaPart: mediaPartProp, index, onDelete, onSaved, viewerConfig}: IProps) {
    const [mediaPart, setMediaPart] = useState(mediaPartProp);
    const [editing, setEditing] = useState(mediaPartProp.id === undefined);
    const [awaitingSave, setAwaitingSave] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [mediaRuntime, setMediaRuntime] = useState<number | undefined>(undefined);

    const readonly = viewerConfig?.mediaPart?.annotator === "disable";
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const videoRef = useRef<HTMLVideoElement>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const localUrl = anchor_local_static_files(media.local_url) || undefined;
    const isVideo = media.media_type === "video";

    const handleMediaLoaded = () => {
        if (isVideo && videoRef.current) {
            const duration = videoRef.current.duration;
            setMediaRuntime(duration);
            if (mediaPart.timestamp_range_end === undefined) {
                setMediaPart(curr => ({...curr, timestamp_range_end: duration}));
            }
            videoRef.current.currentTime = mediaPart.timestamp_range_start || 0;
        }
    };

    const handleSave = async () => {
        setAwaitingSave(true);
        try {
            const saved = await saveMediaPart(mediaPart);
            const next = {...mediaPart, ...saved};
            setMediaPart(next);
            onSaved?.(next);
            setEditing(false);
        } catch { /* surfaced by the server toast */ }
        setAwaitingSave(false);
    };

    const segmentLabel = `Segment${index !== undefined ? ` ${index + 1}` : ""}`;
    const header = (actions?: React.ReactNode) => (
        <Stack direction="row" alignItems="center" justifyContent="space-between">
            {/* Once saved, the label deep-links to this part (opens the focus modal); a new
                unsaved part has no id yet, so it stays plain text. */}
            {mediaPart.id != null && media.id != null ? (
                <Link
                    href={`/media/${media.id}?part_id=${mediaPart.id}`}
                    onClick={(e) => {
                        // Only the MediaPage for this same media reacts to ?part_id; elsewhere
                        // (e.g. search results) the link must navigate normally.
                        const onThisMediaPage =
                            location.pathname === `/media/${media.id}` ||
                            (media.id_on_platform != null && location.pathname === `/media/pk/${media.id_on_platform}`);
                        if (!onThisMediaPage) return;
                        // Leave modified clicks (open-in-new-tab, etc.) to the browser.
                        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                        e.preventDefault();
                        const next = new URLSearchParams(searchParams);
                        next.set("part_id", String(mediaPart.id));
                        setSearchParams(next, {replace: false});
                    }}
                    underline="hover"
                    variant="subtitle2"
                    color="text.secondary"
                >
                    {segmentLabel}
                </Link>
            ) : (
                <Typography variant="subtitle2" color="text.secondary">
                    {segmentLabel}
                </Typography>
            )}
            {actions && <Stack direction="row" alignItems="center" gap={0.5}>{actions}</Stack>}
        </Stack>
    );

    const timeRangeLabel = isVideo && (
        <Typography variant="caption" color="text.secondary">
            {formatTime(mediaPart.timestamp_range_start)} – {formatTime(mediaPart.timestamp_range_end ?? mediaRuntime)}
        </Typography>
    );

    // The applied (cropped + trimmed) view, shared by the read-only and saved (non-editing) states.
    const appliedView = (
        <>
            <CroppedMediaView
                media={media}
                cropArea={mediaPart.crop_area}
                timestampStart={mediaPart.timestamp_range_start}
                timestampEnd={mediaPart.timestamp_range_end}
                sx={{width: "100%", maxWidth: 480}}
            />
            {timeRangeLabel}
        </>
    );

    const deleteButton = (
        <Tooltip title="Delete segment">
            <span>
                <IconButton size="small" color="error" disabled={deleting || awaitingSave}
                            onClick={async () => {
                                setDeleting(true);
                                if (mediaPart.id !== undefined && mediaPart.id !== null) {
                                    try {
                                        await deleteMediaPart(mediaPart.id);
                                    } catch { /* surfaced by the server toast */ }
                                }
                                onDelete();
                            }}>
                    <DeleteOutlineIcon fontSize="small"/>
                </IconButton>
            </span>
        </Tooltip>
    );

    // Read-only (e.g. shared links): the applied view plus tags, no editing affordances.
    if (readonly) {
        return <Card variant="outlined">
            <CardContent>
                <Stack direction="column" gap={1}>
                    {header()}
                    {appliedView}
                    {mediaPart.tags && mediaPart.tags.length > 0 && <InlineTagsDisplay tags={mediaPart.tags}/>}
                </Stack>
            </CardContent>
        </Card>;
    }

    return <Card variant="outlined">
        <CardContent>
            <Stack direction="column" gap={1.5}>
                {editing ? (
                    <>
                        {header(
                            <>
                                <Button
                                    variant="contained" size="small" color="primary" disabled={awaitingSave}
                                    startIcon={awaitingSave ? <CircularProgress size={16} color="inherit"/> : <SaveIcon/>}
                                    onClick={handleSave}
                                >
                                    Save
                                </Button>
                                {deleteButton}
                            </>
                        )}
                        <CropRectEditor
                            mediaType={media.media_type}
                            localUrl={localUrl}
                            cropArea={mediaPart.crop_area}
                            videoRef={videoRef}
                            imageRef={imageRef}
                            onLoaded={handleMediaLoaded}
                            onChange={(crop) => setMediaPart(curr => ({...curr, crop_area: crop}))}
                        />
                        {isVideo && (
                            <Stack gap={0.5}>
                                <Stack direction="row" justifyContent="space-between">
                                    <Typography variant="caption" color="text.secondary">Time range</Typography>
                                    {timeRangeLabel}
                                </Stack>
                                <Slider
                                    size="small"
                                    value={[mediaPart.timestamp_range_start || 0, mediaPart.timestamp_range_end ?? mediaRuntime ?? 100]}
                                    onChange={(_, value) => {
                                        const [start, end] = value as number[];
                                        const seekTo = mediaPart.timestamp_range_start !== start ? start : end;
                                        if (videoRef.current) videoRef.current.currentTime = seekTo;
                                        setMediaPart(curr => ({...curr, timestamp_range_start: start, timestamp_range_end: end}));
                                    }}
                                    min={0}
                                    max={mediaRuntime || 100}
                                    step={0.1}
                                />
                            </Stack>
                        )}
                    </>
                ) : (
                    <>
                        {header(
                            <>
                                <Button
                                    variant="outlined" size="small" color="primary"
                                    startIcon={<EditIcon/>}
                                    onClick={() => setEditing(true)}
                                >
                                    Edit
                                </Button>
                                {deleteButton}
                            </>
                        )}
                        {appliedView}
                    </>
                )}

                {mediaPart.id !== undefined && mediaPart.id !== null && (
                    <>
                        <Divider/>
                        <EntityAnnotator
                            entity={mediaPart}
                            entityType="media_part"
                            readonly={false}
                        />
                    </>
                )}
            </Stack>
        </CardContent>
    </Card>;
}
