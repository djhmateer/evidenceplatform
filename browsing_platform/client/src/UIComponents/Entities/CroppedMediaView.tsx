import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Box, Fade, IconButton, Slider, SxProps, Theme, Tooltip} from "@mui/material";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import VolumeOffIcon from "@mui/icons-material/VolumeOff";
import SkipPreviousIcon from "@mui/icons-material/SkipPrevious";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import {IMedia} from "../../types/entities";
import {anchor_local_static_files} from "../../services/server";
import {formatTime} from "../../lib/timeFormat";

interface IProps {
    media: IMedia;
    cropArea?: number[];
    timestampStart?: number;
    timestampEnd?: number;
    // "container": fill the parent's width (caller bounds it via sx). "viewport": size to fit the
    // viewport (used by the focus modal).
    fit?: "container" | "viewport";
    // Video only: render playback controls (and optionally start playing).
    interactive?: boolean;
    autoPlay?: boolean;
    sx?: SxProps<Theme>;
}

const FPS = 30;
const FRAME = 1 / FPS;
const MIN_UNMUTE_VOLUME = 0.33;
const EPS = 0.05;

// Evidence-lightbox palette: a neutral dark surround so the media's own colours read true, with a
// single restrained instrument-cyan accent used only on active controls.
const INK = "#0B0D10";
const TEXT = "#E8EAED";
const TEXT_DIM = "rgba(232,234,237,0.62)";
const ACCENT = "#57C7D4";
const HAIRLINE = "rgba(255,255,255,0.14)";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// Renders a media asset cropped (and, for video, trimmed) to a MediaPart's bounds — the applied,
// "edit-mode off" view. The full media element is scaled so the crop region exactly fills a
// clipping box whose aspect ratio matches the crop. crop_area = [left%, right%, bottom%, top%] with
// the vertical axis measured from the bottom (matching the editor). Video playback is scoped to the
// segment: the timeline spans only [start, end], and playback always (re)starts at the segment start.
export default function CroppedMediaView({
    media, cropArea, timestampStart, timestampEnd,
    fit = "container", interactive = true, autoPlay = false, sx,
}: IProps) {
    const crop = cropArea && cropArea.length === 4 ? cropArea : [0, 100, 0, 100];
    const [left, right, bottom, top] = crop;
    const cw = Math.max(1, right - left);
    const ch = Math.max(1, top - bottom);
    // Prefer the stored aspect ratio; fall back to whatever the loaded element reports (media whose
    // thumbnail hasn't been generated yet have no stored aspect_ratio, and 1 would distort the crop).
    const [measuredAspect, setMeasuredAspect] = useState<number | undefined>(undefined);
    const mediaAspect = media.aspect_ratio || measuredAspect || 1;
    const boxAspect = (cw / ch) * mediaAspect;

    const localUrl = anchor_local_static_files(media.local_url) || undefined;
    const isVideo = media.media_type === "video";

    const videoRef = useRef<HTMLVideoElement>(null);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(timestampStart || 0);
    const [duration, setDuration] = useState(0);
    const [volume, setVolume] = useState(1);
    const [muted, setMuted] = useState(autoPlay); // autoplay must start muted to satisfy browsers
    const [volumeHovered, setVolumeHovered] = useState(false);
    const [controlsVisible, setControlsVisible] = useState(true);
    const lastNonZeroVolume = useRef(1);
    const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const startTime = timestampStart || 0;
    // End falls back to the full duration once known; before metadata loads it may be 0.
    const endTime = timestampEnd ?? (duration || 0);
    const segLen = Math.max(0, endTime - startTime);
    const showControls = isVideo && interactive;

    const clearHide = useCallback(() => {
        if (hideTimer.current !== null) {
            clearTimeout(hideTimer.current);
            hideTimer.current = null;
        }
    }, []);
    const scheduleHide = useCallback((ms: number) => {
        clearHide();
        hideTimer.current = setTimeout(() => setControlsVisible(false), ms);
    }, [clearHide]);
    useEffect(() => () => clearHide(), [clearHide]);

    const innerStyle: React.CSSProperties = {
        position: "absolute",
        width: `${10000 / cw}%`,
        height: "auto",
        left: `${-(left * 100 / cw)}%`,
        top: `${-((100 - top) * 100 / ch)}%`,
        display: "block",
        pointerEvents: "none",
    };

    // Always (re)start playback at the segment start when the head is parked outside the segment —
    // this is what fixes "clicking play after the segment ends restarts from the file's beginning".
    const play = () => {
        const v = videoRef.current;
        if (!v) return;
        if (endTime && (v.currentTime < startTime - EPS || v.currentTime >= endTime - EPS)) {
            v.currentTime = startTime;
        }
        v.play().catch(() => {});
    };
    const pause = () => videoRef.current?.pause();
    const togglePlay = () => (videoRef.current?.paused ? play() : pause());

    const onTimeUpdate = () => {
        const v = videoRef.current;
        if (!v) return;
        // Stop at the segment boundary; leave the head at the end so the next play resets to start.
        if (endTime && v.currentTime >= endTime) {
            v.pause();
            setCurrentTime(endTime);
            return;
        }
        setCurrentTime(v.currentTime);
    };

    const stepFrame = (dir: 1 | -1) => {
        const v = videoRef.current;
        if (!v) return;
        v.pause();
        v.currentTime = clamp(v.currentTime + dir * FRAME, startTime, endTime || v.duration || 0);
        setCurrentTime(v.currentTime);
    };

    const seek = (_: Event, value: number | number[]) => {
        const v = videoRef.current;
        if (!v) return;
        const t = clamp(value as number, startTime, endTime || v.duration || 0);
        v.currentTime = t;
        setCurrentTime(t);
    };

    const toggleMute = () => {
        const v = videoRef.current;
        if (!v) return;
        if (v.muted || volume === 0) {
            const restored = Math.max(MIN_UNMUTE_VOLUME, lastNonZeroVolume.current);
            v.volume = restored; v.muted = false; setVolume(restored); setMuted(false);
        } else {
            v.muted = true; setMuted(true);
        }
    };
    const onVolume = (_: Event, value: number | number[]) => {
        const v = videoRef.current;
        if (!v) return;
        const vol = value as number;
        if (vol > 0) lastNonZeroVolume.current = vol;
        v.volume = vol; setVolume(vol);
        if (vol === 0) { v.muted = true; setMuted(true); }
        else if (muted) { v.muted = false; setMuted(false); }
    };

    const iconBtn = {color: TEXT, p: 0.25, "&:hover": {color: ACCENT}};

    return (
        <Box
            onMouseEnter={() => { clearHide(); setControlsVisible(true); }}
            onMouseLeave={() => { if (playing) scheduleHide(1400); }}
            sx={{
                position: "relative",
                overflow: "hidden",
                bgcolor: INK,
                borderRadius: 1.5,
                border: `1px solid ${HAIRLINE}`,
                aspectRatio: `${boxAspect}`,
                width: fit === "viewport" ? `min(92vw, calc(82vh * ${boxAspect}))` : "100%",
                ...sx,
            }}
        >
            {isVideo ? (
                <video
                    ref={videoRef}
                    src={localUrl}
                    style={innerStyle}
                    muted={muted}
                    playsInline
                    onLoadedMetadata={(e) => {
                        const v = e.currentTarget;
                        setDuration(v.duration || 0);
                        if (!media.aspect_ratio && v.videoWidth && v.videoHeight) {
                            setMeasuredAspect(v.videoWidth / v.videoHeight);
                        }
                        v.currentTime = startTime;
                        if (autoPlay) v.play().catch(() => {});
                    }}
                    onTimeUpdate={onTimeUpdate}
                    onPlay={() => { setPlaying(true); scheduleHide(2200); }}
                    onPause={() => { setPlaying(false); clearHide(); setControlsVisible(true); }}
                />
            ) : (
                <img
                    src={localUrl}
                    style={innerStyle}
                    alt="segment"
                    onLoad={(e) => {
                        const img = e.currentTarget;
                        if (!media.aspect_ratio && img.naturalWidth && img.naturalHeight) {
                            setMeasuredAspect(img.naturalWidth / img.naturalHeight);
                        }
                    }}
                />
            )}

            {/* Center play affordance while paused */}
            {showControls && !playing && (
                <Box
                    onClick={play}
                    sx={{
                        position: "absolute", inset: 0, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}
                >
                    <Box sx={{
                        display: "flex", alignItems: "center", justifyContent: "center",
                        width: 64, height: 64, borderRadius: "50%",
                        bgcolor: "rgba(11,13,16,0.55)", border: `1px solid ${HAIRLINE}`,
                        backdropFilter: "blur(4px)", color: TEXT,
                        transition: "transform 120ms ease, color 120ms ease, border-color 120ms ease",
                        "&:hover": {transform: "scale(1.06)", color: ACCENT, borderColor: ACCENT},
                    }}>
                        <PlayArrowRoundedIcon sx={{fontSize: 40, ml: 0.5}}/>
                    </Box>
                </Box>
            )}

            {/* Segment-scoped control bar */}
            {showControls && (
                <Fade in={controlsVisible} timeout={300}>
                    <Box
                        onClick={(e) => e.stopPropagation()}
                        sx={{
                            position: "absolute", left: 0, right: 0, bottom: 0, zIndex: 2,
                            display: "flex", alignItems: "center", gap: 0.25, px: 1, py: 0.5,
                            color: TEXT,
                            background: "linear-gradient(to top, rgba(11,13,16,0.92), rgba(11,13,16,0.55) 70%, transparent)",
                            borderTop: `1px solid ${HAIRLINE}`,
                        }}
                    >
                        <IconButton size="small" onClick={togglePlay} sx={iconBtn}>
                            {playing ? <PauseIcon fontSize="small"/> : <PlayArrowIcon fontSize="small"/>}
                        </IconButton>
                        <Tooltip title="Previous frame">
                            <IconButton size="small" onClick={() => stepFrame(-1)} sx={iconBtn}>
                                <SkipPreviousIcon fontSize="small"/>
                            </IconButton>
                        </Tooltip>
                        <Tooltip title="Next frame">
                            <IconButton size="small" onClick={() => stepFrame(1)} sx={iconBtn}>
                                <SkipNextIcon fontSize="small"/>
                            </IconButton>
                        </Tooltip>
                        <Box sx={{fontFamily: MONO, fontSize: 11, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", mx: 0.75, color: TEXT_DIM}}>
                            {formatTime(Math.max(0, currentTime - startTime))} / {formatTime(segLen)}
                        </Box>
                        <Slider
                            size="small"
                            value={clamp(currentTime, startTime, endTime || startTime + 1)}
                            min={startTime}
                            max={endTime || startTime + 1}
                            step={FRAME}
                            onChange={seek}
                            sx={{
                                color: ACCENT, flexGrow: 1, mx: 0.75,
                                "& .MuiSlider-rail": {opacity: 0.3, bgcolor: TEXT},
                                "& .MuiSlider-thumb": {width: 11, height: 11, "&:hover, &.Mui-focusVisible": {boxShadow: `0 0 0 6px rgba(87,199,212,0.22)`}},
                            }}
                        />
                        <Box
                            sx={{position: "relative", display: "flex", alignItems: "center"}}
                            onMouseEnter={() => setVolumeHovered(true)}
                            onMouseLeave={() => setVolumeHovered(false)}
                        >
                            <IconButton size="small" onClick={toggleMute} sx={iconBtn}>
                                {muted || volume === 0 ? <VolumeOffIcon fontSize="small"/> : <VolumeUpIcon fontSize="small"/>}
                            </IconButton>
                            <Fade in={volumeHovered} timeout={150}>
                                <Box sx={{
                                    position: "absolute", bottom: "100%", left: "50%", transform: "translateX(-50%)",
                                    mb: 0.5, height: 88, px: 1, pt: 1.5, pb: 1, zIndex: 10,
                                    bgcolor: "rgba(11,13,16,0.92)", border: `1px solid ${HAIRLINE}`, borderRadius: 1,
                                }}>
                                    <Slider
                                        orientation="vertical" size="small"
                                        value={muted ? 0 : volume} min={0} max={1} step={0.05}
                                        onChange={onVolume}
                                        sx={{color: ACCENT, height: "100%", "& .MuiSlider-thumb": {width: 10, height: 10}}}
                                    />
                                </Box>
                            </Fade>
                        </Box>
                    </Box>
                </Fade>
            )}
        </Box>
    );
}
