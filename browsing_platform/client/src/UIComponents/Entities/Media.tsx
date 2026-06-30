import React, {useCallback, useEffect, useRef, useState} from 'react';
import {useLocation, useNavigate} from "react-router";
import {IMediaAndAssociatedEntities,} from "../../types/entities";
import {Box, Button, CircularProgress, Fade, IconButton, Stack, Typography} from "@mui/material";
import SelfContainedPopover from "../SelfContainedComponents/selfContainedPopover";
import ReactJson from "react-json-view";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import LinkIcon from "@mui/icons-material/Link";
import AddIcon from "@mui/icons-material/Add";
import {fetchMediaData} from "../../services/DataFetcher";
import {anchor_local_static_files} from "../../services/server";
import MediaPart from "./MediaPart";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import EntityAnnotator from "./Annotator";
import {getShareTokenFromHref, SHARE_URL_PARAM} from "../../services/linkSharing";
import ResizableMediaWrapper from "./ResizableMediaWrapper";
import VideoPlayer from "./VideoPlayer";

interface IProps {
    media: IMediaAndAssociatedEntities
    viewerConfig?: EntityViewerConfig
}

function clamp(v: number, min: number, max: number) { return Math.max(min, Math.min(max, v)); }

export default function Media({media: mediaProp, viewerConfig}: IProps) {
    const [media, setMedia] = useState(mediaProp);
    const [expandDetails, setExpandDetails] = useState(false);
    const [awaitingDetailsFetch, setAwaitingDetailsFetch] = useState(false);

    const fetchDetails = async () => {
        const itemId = media.id;
        if (awaitingDetailsFetch || itemId === undefined || itemId === null) return;
        setAwaitingDetailsFetch(true);
        const data = await fetchMediaData(itemId);
        setMedia(curr => ({...curr, data}));
        setAwaitingDetailsFetch(false);
    };


    const navigate = useNavigate();
    const location = useLocation();
    const onMediaPage = location.pathname.startsWith('/media/');

    const localUrl = anchor_local_static_files(media.local_url) || undefined;
    const thumbnailUrl = anchor_local_static_files(media.thumbnail_path) || undefined;
    const [thumbnailLoaded, setThumbnailLoaded] = useState(false);
    const [mediaLoaded, setMediaLoaded] = useState(false);
    const [naturalAspectRatio, setNaturalAspectRatio] = useState<number | undefined>(mediaProp.aspect_ratio ?? undefined);
    const naturalAspectRatioRef = useRef<number | undefined>(mediaProp.aspect_ratio ?? undefined);

    useEffect(() => {
        setThumbnailLoaded(false);
        setMediaLoaded(false);
        const initial = mediaProp.aspect_ratio ?? undefined;
        setNaturalAspectRatio(initial);
        naturalAspectRatioRef.current = initial;
    }, [localUrl]); // eslint-disable-line react-hooks/exhaustive-deps

    // Set once from whichever image (thumbnail or full-res) loads first; ref guard
    // prevents duplicate state updates when both load in quick succession.
    const recordAspectRatio = (img: HTMLImageElement) => {
        if (img.naturalWidth && img.naturalHeight && !naturalAspectRatioRef.current) {
            const ratio = img.naturalWidth / img.naturalHeight;
            naturalAspectRatioRef.current = ratio;
            setNaturalAspectRatio(ratio);
        }
    };

    useEffect(() => {
        if (!thumbnailUrl) setThumbnailLoaded(true);
    }, [thumbnailUrl]);

    const shareToken = getShareTokenFromHref();
    const compactMode = !!(viewerConfig?.post?.compactMode);

    // ── Zoom & Pan state ──────────────────────────────────────────────────────
    // Refs hold the current values for synchronous reads inside event handlers.
    // State drives re-renders.
    const zoomRef = useRef(1);
    const txRef = useRef(0);
    const tyRef = useRef(0);
    const [zoom, setZoom] = useState(1);
    const [translateX, setTranslateX] = useState(0);
    const [translateY, setTranslateY] = useState(0);
    const mediaContainerRef = useRef<HTMLDivElement>(null);
    const ctrlHeld = useRef(false);
    // cleared via setTimeout(0) after resizeStop so the click following mouseup is still suppressed
    const resizingRef = useRef(false);
    const panDrag = useRef<{startX: number; startY: number; startTX: number; startTY: number} | null>(null);

    const applyZoomTranslate = useCallback((newZoom: number, newTX: number, newTY: number) => {
        zoomRef.current = newZoom;
        txRef.current = newTX;
        tyRef.current = newTY;
        setZoom(newZoom);
        setTranslateX(newTX);
        setTranslateY(newTY);
    }, []);

    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Control') ctrlHeld.current = true; };
        const onKeyUp = (e: KeyboardEvent) => { if (e.key === 'Control') ctrlHeld.current = false; };
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('keyup', onKeyUp);
        return () => { window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', onKeyUp); };
    }, []);

    // Ctrl+scroll zoom: keep the point under the cursor fixed
    const handleWheel = useCallback((e: WheelEvent) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        const container = mediaContainerRef.current;
        if (!container) return;
        const rect = container.getBoundingClientRect();
        // Cursor position relative to container center (0,0 = center)
        const cursorX = e.clientX - rect.left - rect.width / 2;
        const cursorY = e.clientY - rect.top - rect.height / 2;

        const prevZoom = zoomRef.current;
        const prevTX = txRef.current;
        const prevTY = tyRef.current;
        const delta = e.deltaY < 0 ? 0.15 : -0.15;
        const newZoom = clamp(prevZoom + delta, 1, 4);
        if (newZoom === prevZoom) return;

        if (newZoom === 1) {
            applyZoomTranslate(1, 0, 0);
            return;
        }

        // Keep the world point under cursor fixed across zoom change:
        // worldPoint = (cursorPos - translate) / prevZoom
        // newTranslate = cursorPos - worldPoint * newZoom
        const worldX = (cursorX - prevTX) / prevZoom;
        const newTX = clamp(cursorX - worldX * newZoom, -(rect.width * (newZoom - 1)) / 2, (rect.width * (newZoom - 1)) / 2);
        const worldY = (cursorY - prevTY) / prevZoom;
        const newTY = clamp(cursorY - worldY * newZoom, -(rect.height * (newZoom - 1)) / 2, (rect.height * (newZoom - 1)) / 2);

        applyZoomTranslate(newZoom, newTX, newTY);
    }, [applyZoomTranslate]);

    useEffect(() => {
        if (compactMode) return;
        const el = mediaContainerRef.current;
        if (!el) return;
        el.addEventListener('wheel', handleWheel, {passive: false});
        return () => el.removeEventListener('wheel', handleWheel);
    }, [compactMode, handleWheel]);

    // Pan via ctrl+drag
    const onMouseDown = useCallback((e: React.MouseEvent) => {
        if (!e.ctrlKey || zoomRef.current <= 1) return;
        e.preventDefault();
        panDrag.current = {startX: e.clientX, startY: e.clientY, startTX: txRef.current, startTY: tyRef.current};
    }, []);

    const onMouseMove = useCallback((e: React.MouseEvent) => {
        if (!panDrag.current) return;
        const container = mediaContainerRef.current;
        if (!container) return;
        const rect = container.getBoundingClientRect();
        const curZoom = zoomRef.current;
        const dx = e.clientX - panDrag.current.startX;
        const dy = e.clientY - panDrag.current.startY;
        const newTX = clamp(panDrag.current.startTX + dx, -(rect.width * (curZoom - 1)) / 2, (rect.width * (curZoom - 1)) / 2);
        const newTY = clamp(panDrag.current.startTY + dy, -(rect.height * (curZoom - 1)) / 2, (rect.height * (curZoom - 1)) / 2);
        txRef.current = newTX;
        tyRef.current = newTY;
        setTranslateX(newTX);
        setTranslateY(newTY);
    }, []);

    const onMouseUp = useCallback(() => { panDrag.current = null; }, []);

    const videoContainerSx = {
        position: 'relative', display: 'block',
        '@keyframes mediaPlaceholderPulse': {
            '0%': {opacity: 1}, '50%': {opacity: 0.4}, '100%': {opacity: 1},
        },
        ...viewerConfig?.media?.style,
        ...(!thumbnailLoaded && {
            aspectRatio: naturalAspectRatio ?? '1 / 1',
            backgroundColor: 'action.hover',
            animation: 'mediaPlaceholderPulse 2s ease-in-out infinite',
        }),
    };

    return <div>
        <Box
            ref={mediaContainerRef}
            sx={{cursor: onMediaPage ? "default" : "pointer", position: "relative"}}
            onMouseEnter={() => setExpandDetails(true)}
            onMouseLeave={() => { setExpandDetails(false); panDrag.current = null; }}
            onClick={(e) => {
                if (resizingRef.current) return;
                if (ctrlHeld.current) return;
                if (media.media_type === "video" && !compactMode) return;
                if (!onMediaPage && media.id !== undefined) {
                    navigate(`/media/${media.id}${shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : ''}`);
                    e.preventDefault();
                }
            }}
            onMouseDown={(e) => {
                // ctrl+drag for pan — handle first, suppress navigation
                if (e.ctrlKey) {
                    onMouseDown(e);
                    return;
                }
                if (e.button === 1) {
                    if (!onMediaPage && media.id !== undefined) {
                        window?.open?.(`/media/${media.id}${shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : ''}`, '_blank')?.focus?.();
                        e.preventDefault();
                    }
                }
            }}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
        >
            {media.media_type === "video" ? (
                compactMode ? (
                    // Compact: thumbnail background + silent hover-play overlay; no controls
                    <Box sx={videoContainerSx}>
                        {thumbnailUrl && (
                            <img src={thumbnailUrl} alt=""
                                 style={{
                                     width: '100%', height: '100%', objectFit: 'cover', display: 'block',
                                     ...(!thumbnailLoaded && {display: 'none'}),
                                 }}
                                 ref={(el) => { if (el?.complete) setThumbnailLoaded(true); }}
                                 onLoad={() => setThumbnailLoaded(true)}/>
                        )}
                        {expandDetails && localUrl && thumbnailLoaded && (
                            <video
                                src={localUrl}
                                autoPlay muted loop playsInline
                                style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
                            />
                        )}
                    </Box>
                ) : (
                    // Normal: resizable custom video player with zoom support
                    <ResizableMediaWrapper
                        initialStyle={viewerConfig?.media?.style}
                        compactMode={false}
                        naturalAspectRatio={naturalAspectRatio}
                        onResizeStart={() => { resizingRef.current = true; }}
                        onResizeStop={() => { setTimeout(() => { resizingRef.current = false; }, 0); }}
                    >
                        {thumbnailUrl && (
                            <img src={thumbnailUrl} alt="" style={{display: 'none'}}
                                 ref={(el) => { if (el?.complete) setThumbnailLoaded(true); }}
                                 onLoad={() => setThumbnailLoaded(true)}/>
                        )}
                        <VideoPlayer
                            src={localUrl}
                            zoom={zoom}
                            translateX={translateX}
                            translateY={translateY}
                            onCanPlay={() => setMediaLoaded(true)}
                            onNaturalAspectRatio={setNaturalAspectRatio}
                            thumbnailLoaded={thumbnailLoaded}
                            initialAspectRatio={naturalAspectRatio}
                        />
                    </ResizableMediaWrapper>
                )
            ) : null}
            {media.media_type === "image" ? (
                // While thumbnail loads: 1:1 grey box. Thumbnail then full-res swap in-flow.
                // compactMode: ResizableMediaWrapper is a passthrough; styles applied to images directly (as before).
                // non-compact: ResizableMediaWrapper controls size; images fill the wrapper 100%.
                <ResizableMediaWrapper
                    initialStyle={viewerConfig?.media?.style}
                    compactMode={compactMode}
                    naturalAspectRatio={naturalAspectRatio}
                    onResizeStart={() => { resizingRef.current = true; }}
                    onResizeStop={() => { setTimeout(() => { resizingRef.current = false; }, 0); }}
                >
                    <Box sx={{
                        position: 'relative', display: 'block', width: '100%',
                        overflow: 'hidden',
                        '@keyframes mediaPlaceholderPulse': {
                            '0%': {opacity: 1}, '50%': {opacity: 0.4}, '100%': {opacity: 1},
                        },
                        ...(!(thumbnailLoaded || mediaLoaded) && {
                            aspectRatio: naturalAspectRatio ?? '1 / 1',
                            backgroundColor: 'action.hover',
                            animation: 'mediaPlaceholderPulse 2s ease-in-out infinite',
                        }),
                    }}>
                        {/* Thumbnail — in-flow, sizes the box; triggers thumbnailLoaded on load */}
                        {thumbnailUrl && !mediaLoaded && (
                            <img src={thumbnailUrl} alt=""
                                 style={{
                                     // In compact mode, apply viewerConfig style (aspectRatio, objectFit, etc.)
                                     // In non-compact mode, just fill the wrapper
                                     ...(compactMode ? viewerConfig?.media?.style : {}),
                                     width: '100%', display: 'block',
                                     transformOrigin: 'center center',
                                     transform: `scale(${zoom}) translate(${translateX / zoom}px, ${translateY / zoom}px)`,
                                     transition: 'transform 0.05s ease-out',
                                 }}
                                 ref={(el) => { if (el?.complete) { setThumbnailLoaded(true); recordAspectRatio(el); } }}
                                 onLoad={(e) => { setThumbnailLoaded(true); recordAspectRatio(e.currentTarget); }}/>
                        )}
                        {/* Full-res — preloads silently while thumbnail shows, then becomes in-flow */}
                        <img
                            src={localUrl}
                            alt="photo"
                            style={{
                                ...(compactMode ? viewerConfig?.media?.style : {}),
                                width: '100%',
                                transformOrigin: 'center center',
                                transform: `scale(${zoom}) translate(${translateX / zoom}px, ${translateY / zoom}px)`,
                                transition: 'transform 0.05s ease-out',
                                ...(mediaLoaded ? {display: 'block'} : {
                                    position: 'absolute',
                                    opacity: 0,
                                    pointerEvents: 'none',
                                    top: 0,
                                    left: 0,
                                }),
                            }}
                            ref={(el) => { if (el?.complete && el?.naturalWidth > 0) { setMediaLoaded(true); recordAspectRatio(el); } }}
                            onLoad={(e) => { setMediaLoaded(true); recordAspectRatio(e.currentTarget); }}
                            onError={() => setMediaLoaded(true)}
                        />
                    </Box>
                </ResizableMediaWrapper>
            ) : null}
            {!compactMode && <Box
                sx={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    pointerEvents: "auto",
                }}
            >
                <Fade in={expandDetails} timeout={300}>
                    <Stack
                        direction={"row"}
                        alignItems={"center"}
                        gap={1}
                        sx={{
                            width: "100%",
                            boxSizing: "border-box",
                            backgroundColor: "rgba(0,0,0,0.7)",
                            color: "#fff",
                            p: 2,
                            textAlign: "center",
                        }}
                        className={"media-item-interactions-layout"}
                    >
                        {
                            viewerConfig?.all?.hideInnerLinks ? null : <IconButton
                                color={"primary"}
                                href={"/media/" + media.id + (shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : '')}
                            >
                                <LinkIcon/>
                            </IconButton>
                        }
                        <span>
                            <SelfContainedPopover
                                trigger={(popupVisibilitySetter) => (
                                    <IconButton
                                        size="small"
                                        color={"primary"}
                                        onClick={async (e) => {
                                            if (media.data === undefined || media.data === null) {
                                                await fetchDetails();
                                            }
                                            popupVisibilitySetter(e, true);
                                        }}
                                    >
                                        <MoreHorizIcon/>
                                    </IconButton>
                                )}
                                content={() => (<span>
                                    {
                                        awaitingDetailsFetch ?
                                            <CircularProgress size={20}/> :
                                            media.data ?
                                                <ReactJson
                                                    src={media.data}
                                                    enableClipboard={false}
                                                    style={{wordBreak: 'break-word'}}
                                                /> :
                                                null
                                    }
                                </span>)}
                                popoverProps={{
                                    anchorOrigin: {vertical: 'bottom', horizontal: 'left'},
                                    transformOrigin: {vertical: 'top', horizontal: 'left'},
                                    sx: {maxWidth: "90vw", maxHeight: "60vh"},
                                }}
                            />
                        </span>
                    </Stack>
                </Fade>
            </Box>}
        </Box>
        {
            viewerConfig?.media?.annotator !== "hide" &&
            <EntityAnnotator
                entity={media}
                entityType={"media"}
                readonly={viewerConfig?.media?.annotator === "disable"}
            />
        }
        {
            viewerConfig?.mediaPart.display === "display" ? <Stack direction={"column"} gap={1}>
                <Typography variant={"subtitle1"}>Segments</Typography>
                {
                    (media.media_parts || []).map(
                        (mediaPart, index: number) => <MediaPart
                            mediaPart={mediaPart}
                            media={media}
                            index={index}
                            viewerConfig={viewerConfig}
                            key={mediaPart.id ?? `new-${index}`}
                            onSaved={(saved) => {
                                setMedia(curr => {
                                    const parts = [...(curr.media_parts || [])];
                                    parts[index] = saved;
                                    return {...curr, media_parts: parts};
                                });
                            }}
                            onDelete={() => {
                                try {
                                    const parts = [...(media.media_parts || [])];
                                    parts.splice(index, 1);
                                    setMedia(curr => ({...curr, media_parts: parts}));
                                } catch (_) {}
                            }}
                        />
                    )
                }
                {viewerConfig?.mediaPart?.annotator !== "disable" && <Button
                    variant={"outlined"} color={"primary"} startIcon={<AddIcon/>}
                    onClick={() => {
                        // New segments start unsaved in edit mode; the Save button persists them
                        // (and reveals the per-part tag assigner once they get an id).
                        const newPart = {
                            media_id: media.id,
                            crop_area: [0, 100, 0, 100],
                            timestamp_range_start: 0,
                        };
                        setMedia(curr => ({...curr, media_parts: [...(curr.media_parts || []), newPart]}));
                    }}
                >
                    New segment
                </Button>}
            </Stack> : null
        }
    </div>
}
