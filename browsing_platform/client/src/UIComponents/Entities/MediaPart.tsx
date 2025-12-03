import React from 'react';
import {IMedia, IMediaPart,} from "../../types/entities";
import {
    Box,
    Button,
    Card,
    CardActions,
    CardContent,
    CircularProgress,
    InputLabel,
    Slider,
    Stack,
    Typography
} from "@mui/material";

import EditIcon from "@mui/icons-material/Edit";
import SaveIcon from "@mui/icons-material/Save";
import {anchor_local_static_files} from "../../services/server";
import TextField from "@mui/material/TextField";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import {deleteMediaPart, saveMediaPart} from "../../services/DataSaver";

interface IProps {
    media: IMedia
    mediaPart: IMediaPart
    refetchMediaParts: () => Promise<void>
    onDelete: () => void
    viewerConfig?: EntityViewerConfig
}

interface IState {
    mediaPart: IMediaPart
    editing: boolean,
    awaitingSave: boolean
    mediaHeight?: number
    mediaRuntime?: number
}


export default class MediaPart extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            mediaPart: props.mediaPart,
            editing: props.mediaPart.id === undefined,
            awaitingSave: false
        };
    }

    videoRef = React.createRef<HTMLVideoElement>();
    imageRef = React.createRef<HTMLImageElement>();

    setMediaHeight = () => {
        if (this.props.media.media_type === "video" && this.videoRef.current) {
            const videoDuration = this.videoRef.current.duration;
            const {mediaPart} = this.props;
            if (mediaPart.timestamp_range_end === undefined) {
                mediaPart.timestamp_range_end = videoDuration;
            }
            this.setState({
                mediaHeight: this.videoRef.current.clientHeight,
                mediaRuntime: videoDuration,
            });
        } else if (this.props.media.media_type === "image" && this.imageRef.current) {
            this.setState({
                mediaHeight: this.imageRef.current.clientHeight,
                mediaRuntime: undefined,
            });
        }
    };

    renderMediaPartCropped = () => {
        const {mediaPart} = this.props;
        const {media} = this.props;
        let localUrl = anchor_local_static_files(media.local_url) || undefined;
        const cropArea = mediaPart.crop_area || [0, 100, 0, 100];
        const cropWidth = 300 * (cropArea[1] - cropArea[0]) / 100;
        const cropHeight = (this.state.mediaHeight || 300) * (cropArea[3] - cropArea[2]) / 100;
        const offsetX = 300 * cropArea[0] / 100;
        const offsetY = (this.state.mediaHeight || 300) * (100 - cropArea[3]) / 100;
        const containerStyle: React.CSSProperties = {
            width: `${cropWidth}px`,
            height: `${cropHeight}px`,
            overflow: 'hidden',
            position: 'relative'
        };
        const mediaStyle: React.CSSProperties = {
            position: 'absolute',
            left: `-${offsetX}px`,
            top: `-${offsetY}px`,
            width: '300px',
            height: this.state.mediaHeight ? `${this.state.mediaHeight}px` : 'auto',
            objectFit: 'cover'
        };
        return <Box style={containerStyle}>
            {media.media_type === "video" ? (
                <video
                    ref={this.videoRef}
                    src={localUrl + "#t=" + (mediaPart.timestamp_range_start || 0) + "," + (mediaPart.timestamp_range_end || '')}
                    style={mediaStyle}
                    width={cropWidth}
                    height={cropHeight}
                    onLoadedMetadata={this.setMediaHeight}
                    controls
                />
            ) : null}
            {media.media_type === "image" ? (
                <img
                    ref={this.imageRef}
                    src={localUrl}
                    alt={"photo"}
                    style={mediaStyle}
                    width={cropWidth}
                    height={cropHeight}
                    onLoad={this.setMediaHeight}
                />
            ) : null}
        </Box>
    }

    renderMediaPartCropper = () => {
        const {mediaPart} = this.state;
        const {media} = this.props;
        let localUrl = anchor_local_static_files(media.local_url) || undefined;
        return <Stack
            direction={"row"} gap={1}
            sx={{height: `calc(${this.state.mediaHeight}px + 2.2em)`}}
        >
            <Stack
                direction={"column"} gap={1}
            >
                <Box
                    sx={{
                        cursor: "pointer", position: "relative", overflow: "hidden",
                        "::after": {
                            content: '""',
                            position: 'absolute',
                            top: `${100 - (mediaPart.crop_area?.[3] || 0)}%`,
                            left: `${mediaPart.crop_area?.[0]}%`,
                            height: `${(mediaPart.crop_area?.[3] || 0) - (mediaPart.crop_area?.[2] || 0)}%`,
                            width: `${(mediaPart.crop_area?.[1] || 0) - (mediaPart.crop_area?.[0] || 0)}%`,
                            pointerEvents: 'none',
                            boxShadow: "0 0 0 9999px rgba(0, 100, 200, 0.4)"
                        },
                    }}
                >
                    {
                        media.media_type === "video" ?
                            <video
                                ref={this.videoRef}
                                src={localUrl}
                                style={
                                    {
                                        backgroundColor: '#000',
                                    }
                                }
                                controls
                                width={300}
                                onLoadedMetadata={this.setMediaHeight}
                            /> :
                            null
                    }
                    {
                        media.media_type === "image" ?
                            <img
                                ref={this.imageRef}
                                src={localUrl}
                                alt={"photo"}
                                width={300}
                                onLoad={this.setMediaHeight}
                            /> :
                            null
                    }
                </Box>
                <Slider
                    value={[mediaPart.crop_area?.[0] || 0, mediaPart.crop_area?.[1] || 100]}
                    onChange={(_, value) => {
                        const [start, end] = value as number[];
                        if (!mediaPart.crop_area) {
                            mediaPart.crop_area = [0, 100, 0, 100];
                        }
                        mediaPart.crop_area[0] = start;
                        mediaPart.crop_area[1] = end;
                        this.setState((curr) => ({...curr, mediaPart}));
                    }}
                    min={0}
                    max={100}
                    orientation={"horizontal"}
                />
            </Stack>
            <Slider
                value={[mediaPart.crop_area?.[2] || 0, mediaPart.crop_area?.[3] || 100]}
                onChange={(_, value) => {
                    const [start, end] = value as number[];
                    if (!mediaPart.crop_area) {
                        mediaPart.crop_area = [0, 100, 0, 100];
                    }
                    mediaPart.crop_area[2] = start;
                    mediaPart.crop_area[3] = end;
                    this.setState((curr) => ({...curr, mediaPart}));
                }}
                min={0}
                max={100}
                orientation={"vertical"}
                sx={{height: "calc(100% - 2.2em)"}}
            />
        </Stack>
    }

    render() {
        const {media} = this.props;
        const {mediaPart, editing, awaitingSave} = this.state;
        return <Card>
            <CardContent>
                <Stack direction={"column"} gap={1}>
                    {editing ? this.renderMediaPartCropper() : this.renderMediaPartCropped()}
                    {
                        media.media_type === "video" &&
                        <Stack>
                            <InputLabel>
                                Time Range
                            </InputLabel>
                            {editing ? <Slider
                                    value={[mediaPart.timestamp_range_start || 0, mediaPart.timestamp_range_end || this.state.mediaRuntime || 100]}
                                    onChange={(_, value) => {
                                        const [start, end] = value as number[];
                                        const seekTimestamp = mediaPart.timestamp_range_start !== start ? start : end;
                                        if (this.videoRef.current) {
                                            this.videoRef.current.currentTime = seekTimestamp;
                                        }
                                        mediaPart.timestamp_range_start = start;
                                        mediaPart.timestamp_range_end = end;
                                        this.setState((curr) => ({...curr, mediaPart}));
                                    }}
                                    min={0}
                                    max={this.state.mediaRuntime || 100}
                                /> :
                                <Typography>{mediaPart.timestamp_range_start} - {mediaPart.timestamp_range_end}</Typography>
                            }
                        </Stack>
                    }
                    <TextField
                        label={"notes"}
                        value={mediaPart.notes || ""}
                        onChange={(e) => {
                            mediaPart.notes = e.target.value;
                            this.setState((curr) => ({...curr, mediaPart}));
                        }}
                        fullWidth
                        multiline
                        disabled={!editing || awaitingSave}
                    />
                </Stack>
            </CardContent>
            <CardActions>
                {
                    editing ?
                        <Button
                            variant={"contained"} color={"primary"} disabled={awaitingSave}
                            startIcon={awaitingSave ? <CircularProgress size={20} color={"inherit"}/> : <SaveIcon/>}
                            onClick={() => {
                                this.setState({awaitingSave: true}, async () => {
                                    await saveMediaPart(this.state.mediaPart);
                                    await this.props.refetchMediaParts();
                                    this.setState({editing: false, awaitingSave: false});
                                })
                            }}
                        >
                            Save
                        </Button> :
                        <Button
                            variant={"contained"} color={"success"}
                            onClick={() => this.setState({editing: true})}
                            startIcon={<EditIcon/>}
                        >
                            Edit
                        </Button>
                }
                <Button
                    variant={"contained"}
                    color={"error"}
                    disabled={awaitingSave}
                    onClick={async () => {
                        this.setState({awaitingSave: true}, async () => {
                            const mediaPartId = mediaPart.id;
                            if (!(mediaPartId === null || mediaPartId === undefined)) {
                                await deleteMediaPart(mediaPartId);
                            }
                            this.props.onDelete();
                            this.setState({awaitingSave: false});
                        });
                    }}
                >
                    Delete
                </Button>
            </CardActions>
        </Card>
    }
}
