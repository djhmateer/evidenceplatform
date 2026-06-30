import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Box, Fade, IconButton, Slider, Tooltip} from '@mui/material';
import PauseIcon from '@mui/icons-material/Pause';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import VolumeOffIcon from '@mui/icons-material/VolumeOff';
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import {formatTime} from "../../lib/timeFormat";

const FPS = 30;
const FRAME_DURATION = 1 / FPS;
const CONTROL_BAR_HEIGHT = 44;
const MIN_UNMUTE_VOLUME = 0.33;

interface IProps {
    src: string | undefined;
    zoom: number;
    translateX: number;
    translateY: number;
    onCanPlay?: () => void;
    onLoaded?: () => void;
    onNaturalAspectRatio?: (ratio: number) => void;
    thumbnailLoaded: boolean;
    initialAspectRatio?: number;
}


export default function VideoPlayer({src, zoom, translateX, translateY, onCanPlay, onLoaded, onNaturalAspectRatio, thumbnailLoaded, initialAspectRatio}: IProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const videoRef = useRef<HTMLVideoElement>(null);
    const [playing, setPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [volume, setVolume] = useState(1);
    const [muted, setMuted] = useState(false);
    const [volumeHovered, setVolumeHovered] = useState(false);
    const lastNonZeroVolume = useRef(1);
    const [focused, setFocused] = useState(false);
    const [videoAspectRatio, setVideoAspectRatio] = useState(initialAspectRatio ?? 16 / 9);
    const [controlsVisible, setControlsVisible] = useState(true);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const clearHideTimer = useCallback(() => {
        if (hideTimerRef.current !== null) {
            clearTimeout(hideTimerRef.current);
            hideTimerRef.current = null;
        }
    }, []);

    const scheduleHide = useCallback((delayMs: number) => {
        clearHideTimer();
        hideTimerRef.current = setTimeout(() => setControlsVisible(false), delayMs);
    }, [clearHideTimer]);

    // Clean up timer on unmount
    useEffect(() => () => clearHideTimer(), [clearHideTimer]);

    const stepFrame = useCallback((direction: 1 | -1) => {
        const v = videoRef.current;
        if (!v) return;
        v.pause();
        setPlaying(false);
        v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + direction * FRAME_DURATION));
    }, []);

    useEffect(() => {
        if (!focused) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === ',' || e.key === '<') { e.preventDefault(); stepFrame(-1); }
            if (e.key === '.' || e.key === '>') { e.preventDefault(); stepFrame(1); }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [focused, stepFrame]);

    // Keep fullscreen state in sync with browser (e.g. Esc, F11, or native exit)
    useEffect(() => {
        const handler = () => setIsFullscreen(document.fullscreenElement === containerRef.current);
        document.addEventListener('fullscreenchange', handler);
        return () => document.removeEventListener('fullscreenchange', handler);
    }, []);

    const toggleFullscreen = () => {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            containerRef.current?.requestFullscreen();
        }
    };

    const togglePlay = () => {
        const v = videoRef.current;
        if (!v) return;
        if (v.paused) { v.play(); setPlaying(true); }
        else { v.pause(); setPlaying(false); }
    };

    const toggleMute = () => {
        const v = videoRef.current;
        if (!v) return;
        if (v.muted || volume === 0) {
            const restored = Math.max(MIN_UNMUTE_VOLUME, lastNonZeroVolume.current);
            v.volume = restored;
            v.muted = false;
            setVolume(restored);
            setMuted(false);
        } else {
            v.muted = true;
            setMuted(true);
        }
    };

    const handleVolumeChange = (_: Event, value: number | number[]) => {
        const v = videoRef.current;
        if (!v) return;
        const vol = value as number;
        if (vol > 0) lastNonZeroVolume.current = vol;
        v.volume = vol;
        setVolume(vol);
        if (vol === 0) { v.muted = true; setMuted(true); }
        else if (muted) { v.muted = false; setMuted(false); }
    };

    const handleSeek = (_: Event, value: number | number[]) => {
        const v = videoRef.current;
        if (!v) return;
        v.currentTime = value as number;
        setCurrentTime(value as number);
    };

    return (
        <Box
            ref={containerRef}
            sx={{
                width: '100%',
                position: 'relative',
                aspectRatio: videoAspectRatio,
                backgroundColor: '#000',
                ...(isFullscreen && {aspectRatio: 'auto', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center'}),
            }}
            tabIndex={0}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onMouseEnter={() => {
                setFocused(true);
                clearHideTimer();
                setControlsVisible(true);
            }}
            onMouseLeave={() => {
                setFocused(false);
                if (playing) scheduleHide(1500);
            }}
            onClick={(e) => { e.stopPropagation(); togglePlay(); }}
        >
            {/* Video area — clips zoom overflow, fills the aspect-ratio box */}
            <Box sx={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
                <video
                    ref={videoRef}
                    src={src}
                    style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'contain',
                        display: thumbnailLoaded ? 'block' : 'none',
                        transformOrigin: 'center center',
                        transform: `scale(${zoom}) translate(${translateX / zoom}px, ${translateY / zoom}px)`,
                        transition: 'transform 0.05s ease-out',
                    }}
                    onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
                    onDurationChange={() => setDuration(videoRef.current?.duration ?? 0)}
                    onPlay={() => {
                        setPlaying(true);
                        scheduleHide(2500);
                    }}
                    onPause={() => {
                        setPlaying(false);
                        clearHideTimer();
                        setControlsVisible(true);
                    }}
                    onCanPlay={onCanPlay}
                    onLoadedData={onLoaded}
                    onLoadedMetadata={() => {
                        const v = videoRef.current;
                        if (v && v.videoWidth && v.videoHeight) {
                            const ratio = v.videoWidth / v.videoHeight;
                            setVideoAspectRatio(ratio);
                            onNaturalAspectRatio?.(ratio);
                        }
                    }}
                />
            </Box>

            {/* Control bar — overlaid at bottom, outside clip, unaffected by zoom */}
            <Fade in={controlsVisible} timeout={400}>
                <Box
                    sx={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        zIndex: 1,
                        height: CONTROL_BAR_HEIGHT,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 0.5,
                        pl: 1,
                        pr: 2,
                        backgroundColor: 'rgba(0,0,0,0.75)',
                        color: '#fff',
                    }}
                    onClick={(e) => e.stopPropagation()}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    <IconButton size="small" onClick={togglePlay} sx={{color: '#fff', p: 0.25}}>
                        {playing ? <PauseIcon fontSize="small"/> : <PlayArrowIcon fontSize="small"/>}
                    </IconButton>
                    <Tooltip title="Previous frame (,)">
                        <IconButton size="small" onClick={() => stepFrame(-1)} sx={{color: '#fff', p: 0.25}}>
                            <SkipPreviousIcon fontSize="small"/>
                        </IconButton>
                    </Tooltip>
                    <Tooltip title="Next frame (.)">
                        <IconButton size="small" onClick={() => stepFrame(1)} sx={{color: '#fff', p: 0.25}}>
                            <SkipNextIcon fontSize="small"/>
                        </IconButton>
                    </Tooltip>
                    <Box sx={{fontSize: 11, whiteSpace: 'nowrap', mx: 0.5, color: 'rgba(255,255,255,0.8)'}}>
                        {formatTime(currentTime)} / {formatTime(duration)}
                    </Box>
                    <Slider
                        size="small"
                        value={currentTime}
                        min={0}
                        max={duration || 1}
                        step={FRAME_DURATION}
                        onChange={handleSeek}
                        sx={{color: '#fff', flexGrow: 1, mx: 0.5, '& .MuiSlider-thumb': {width: 10, height: 10}}}
                    />
                    <Box
                        sx={{position: 'relative', display: 'flex', alignItems: 'center'}}
                        onMouseEnter={() => setVolumeHovered(true)}
                        onMouseLeave={() => setVolumeHovered(false)}
                    >
                        <IconButton size="small" onClick={toggleMute} sx={{color: '#fff', p: 0.25}}>
                            {muted || volume === 0 ? <VolumeOffIcon fontSize="small"/> : <VolumeUpIcon fontSize="small"/>}
                        </IconButton>
                        <Fade in={volumeHovered} timeout={150}>
                            <Box
                                sx={{
                                    position: 'absolute',
                                    bottom: '100%',
                                    left: '50%',
                                    transform: 'translateX(-50%)',
                                    mb: 0.5,
                                    backgroundColor: 'rgba(0,0,0,0.85)',
                                    borderRadius: 1,
                                    px: 1,
                                    pt: 1.5,
                                    pb: 1,
                                    display: 'flex',
                                    alignItems: 'center',
                                    height: 90,
                                    zIndex: 10,
                                }}
                            >
                                <Slider
                                    orientation="vertical"
                                    size="small"
                                    value={muted ? 0 : volume}
                                    min={0}
                                    max={1}
                                    step={0.05}
                                    onChange={handleVolumeChange}
                                    sx={{color: '#fff', height: '100%', '& .MuiSlider-thumb': {width: 10, height: 10}}}
                                />
                            </Box>
                        </Fade>
                    </Box>
                    <Tooltip title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
                        <IconButton size="small" onClick={toggleFullscreen} sx={{color: '#fff', p: 0.25}}>
                            {isFullscreen ? <FullscreenExitIcon fontSize="small"/> : <FullscreenIcon fontSize="small"/>}
                        </IconButton>
                    </Tooltip>
                </Box>
            </Fade>
        </Box>
    );
}
