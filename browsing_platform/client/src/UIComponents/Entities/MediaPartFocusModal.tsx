import React from 'react';
import {Box, Dialog, IconButton, Link, Stack, Typography} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import CropFreeRoundedIcon from "@mui/icons-material/CropFreeRounded";
import cookie from "js-cookie";
import {IMedia, IMediaPart} from "../../types/entities";
import InlineTagsDisplay from "../Tags/InlineTagsDisplay";
import CroppedMediaView from "./CroppedMediaView";
import LinkSharing from "../LinkSharing/LinkSharing";
import {formatTime} from "../../lib/timeFormat";

interface IProps {
    open: boolean;
    onClose: () => void;
    media: IMedia;
    part: IMediaPart;
}

const TEXT = "#E8EAED";
const TEXT_DIM = "rgba(232,234,237,0.6)";
const ACCENT = "#57C7D4";
const HAIRLINE = "rgba(255,255,255,0.14)";
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

// An evidence lightbox: the part's applied (cropped + trimmed) view enlarged on a neutral dark
// surround so its colours read true, captioned with a specimen-style label. The cropped rendering
// and segment playback are handled by CroppedMediaView.
export default function MediaPartFocusModal({open, onClose, media, part}: IProps) {
    const isVideo = media.media_type === "video";
    const range = isVideo
        ? `${formatTime(part.timestamp_range_start)} – ${formatTime(part.timestamp_range_end)}`
        : null;

    // Direct link to this exact part on the media page (the ?part_id deep-link that opens this modal).
    const partHref = media.id != null ? `/media/${media.id}?part_id=${part.id}` : undefined;

    // Sharing a part is functionally sharing its parent media (access auth is per-media), but the
    // copied URL carries part_id so recipients land on this segment. Reuse the stable pk path when
    // available, mirroring MediaPage's header share.
    const sharePath = `${media.id_on_platform ? `/media/pk/${media.id_on_platform}` : `/media/${media.id}`}?part_id=${part.id}`;
    const isLoggedIn = !!cookie.get("token");
    const canShare = isLoggedIn && media.id != null && part.id != null;

    return (
        <Dialog
            open={open}
            onClose={onClose}
            maxWidth={false}
            slotProps={{backdrop: {sx: {bgcolor: "rgba(7,8,10,0.82)", backdropFilter: "blur(8px)"}}}}
            PaperProps={{sx: {bgcolor: "transparent", boxShadow: "none", m: 2, overflow: "visible", maxWidth: "none"}}}
        >
            <Stack gap={1.25} alignItems="center" sx={{position: "relative"}}>
                <IconButton
                    onClick={onClose}
                    aria-label="Close"
                    size="small"
                    sx={{
                        position: "absolute", top: -8, right: -8, zIndex: 3,
                        color: TEXT, bgcolor: "rgba(11,13,16,0.7)", border: `1px solid ${HAIRLINE}`,
                        "&:hover": {bgcolor: "rgba(11,13,16,0.9)", color: ACCENT, borderColor: ACCENT},
                    }}
                >
                    <CloseIcon fontSize="small"/>
                </IconButton>

                <Box sx={{boxShadow: "0 24px 64px rgba(0,0,0,0.6)", borderRadius: 1.5}}>
                    <CroppedMediaView
                        media={media}
                        cropArea={part.crop_area}
                        timestampStart={part.timestamp_range_start}
                        timestampEnd={part.timestamp_range_end}
                        fit="viewport"
                        autoPlay
                    />
                </Box>

                {/* Specimen label */}
                <Stack
                    direction="row"
                    alignItems="center"
                    gap={1.25}
                    sx={{
                        maxWidth: "92vw",
                        bgcolor: "rgba(11,13,16,0.78)",
                        border: `1px solid ${HAIRLINE}`,
                        borderRadius: 1,
                        pl: 1.5, pr: 1, py: 0.75,
                    }}
                >
                    <CropFreeRoundedIcon sx={{fontSize: 16, color: ACCENT}}/>
                    <Link
                        href={partHref}
                        underline="hover"
                        sx={{
                            color: TEXT, fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase",
                            textDecorationColor: ACCENT,
                            "&:hover": {color: ACCENT},
                        }}
                    >
                        Segment {part.id}
                    </Link>
                    {range && (
                        <Typography sx={{color: TEXT_DIM, fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums"}}>
                            {range}
                        </Typography>
                    )}
                    {part.tags && part.tags.length > 0 && (
                        <Box sx={{borderLeft: `1px solid ${HAIRLINE}`, pl: 1.25}}>
                            <InlineTagsDisplay tags={part.tags}/>
                        </Box>
                    )}
                    {canShare && (
                        <Box sx={{borderLeft: `1px solid ${HAIRLINE}`, pl: 1.25, display: "flex"}}>
                            <LinkSharing entityType="media" entityId={media.id!} stableSharePath={sharePath}/>
                        </Box>
                    )}
                </Stack>
            </Stack>
        </Dialog>
    );
}
