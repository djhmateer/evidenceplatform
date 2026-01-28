import React from 'react';
import {IMediaAndAssociatedEntities,} from "../../types/entities";
import {Box, Button, CircularProgress, Fade, IconButton, Stack, Typography} from "@mui/material";
import SelfContainedPopover from "../SelfContainedComponents/selfContainedPopover";
import ReactJson from "react-json-view";
import MoreHorizIcon from "@mui/icons-material/MoreHoriz";
import LinkIcon from "@mui/icons-material/Link";
import {fetchMediaData, fetchMediaParts} from "../../services/DataFetcher";
import {anchor_local_static_files} from "../../services/server";
import MediaPart from "./MediaPart";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import EntityAnnotator from "./Annotator";
import {getShareTokenFromHref, SHARE_URL_PARAM} from "../../services/linkSharing";

interface IProps {
    media: IMediaAndAssociatedEntities
    viewerConfig?: EntityViewerConfig
}

interface IState {
    media: IMediaAndAssociatedEntities
    expandDetails: boolean
    awaitingDetailsFetch: boolean
    savingAnnotations: boolean
}


export default class Media extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            media: props.media,
            expandDetails: false,
            awaitingDetailsFetch: false,
            savingAnnotations: false
        };
    }

    private fetchMediaDetails = async () => {
        const media = this.state.media;
        const itemId = media.id;
        if (this.state.awaitingDetailsFetch || itemId === undefined || itemId === null) {
            return;
        }
        this.setState((curr => ({...curr, awaitingDetailsFetch: true})), async () => {
            media.data = await fetchMediaData(itemId);
            this.setState((curr => ({...curr, awaitingDetailsFetch: false, media})));
        });
    }

    private fetchMediaParts = async () => {
        const itemId = this.props.media.id;
        if (itemId === undefined || itemId === null) {
            return;
        }
        this.props.media.media_parts = await fetchMediaParts(itemId);
        this.setState((curr => ({...curr})));
    }

    render() {
        const media = this.props.media;
        let localUrl = anchor_local_static_files(media.local_url) || undefined;
        const shareToken = getShareTokenFromHref()

        return <div>
            <Box
                sx={{cursor: "pointer", position: "relative"}}
                onMouseEnter={() => this.setState({expandDetails: true})}
                onMouseLeave={() => this.setState({expandDetails: false})}
            >
                {
                    media.media_type === "video" ?
                        <video
                            src={localUrl}
                            style={
                                {
                                    backgroundColor: '#000',
                                    ...this.props.viewerConfig?.media?.style
                                }
                            }
                            controls
                        /> :
                        null
                }
                {
                    media.media_type === "image" ?
                        <img
                            src={localUrl}
                            alt={"photo"}
                            style={this.props.viewerConfig?.media.style}
                        /> :
                        null
                }
                <Box
                    sx={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        pointerEvents: "auto",
                    }}
                >
                    <Fade in={this.state.expandDetails} timeout={300}>
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
                        >
                            {
                                this.props.viewerConfig?.all?.hideInnerLinks ? null : <IconButton
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
                                        onClick={(e) => this.setState((curr) => ({
                                            ...curr,
                                            expandDetails: !curr.expandDetails
                                        }), async () => {
                                            if (this.state.expandDetails) {
                                                if (media.data === undefined || media.data === null) {
                                                    await this.fetchMediaDetails();
                                                }
                                                popupVisibilitySetter(e, true)
                                            }
                                        })}
                                    >
                                        <MoreHorizIcon/>
                                    </IconButton>
                                )}
                                content={() => (<span>
                                    {
                                        this.state.awaitingDetailsFetch ?
                                            <CircularProgress size={20}/> :
                                            this.props.media.data ?
                                                <ReactJson
                                                    src={media.data}
                                                    enableClipboard={false}
                                                    style={{wordBreak: 'break-word'}}
                                                /> :
                                                null
                                    }
                                </span>)}
                                popoverProps={
                                    {
                                        anchorOrigin: {
                                            vertical: 'bottom',
                                            horizontal: 'left',
                                        },
                                        transformOrigin: {
                                            vertical: 'top',
                                            horizontal: 'left',
                                        }
                                    }
                                }
                            />
                        </span>
                        </Stack>
                    </Fade>
                </Box>
            </Box>
            {
                this.props.viewerConfig?.media?.annotator !== "hide" &&
                <EntityAnnotator
                    entity={this.state.media}
                    entityType={"media"}
                    readonly={this.props.viewerConfig?.media?.annotator === "disable"}
                />
            }
            {
                this.props.viewerConfig?.mediaPart.display === "display" ? <Stack direction={"column"} gap={1}>
                    <Typography>Segments</Typography>
                    {
                        (media.media_parts || []).map(
                            (mediaPart, index: number) => <MediaPart
                                mediaPart={mediaPart}
                                media={this.props.media}
                                key={index}
                                refetchMediaParts={this.fetchMediaParts}
                                onDelete={() => {
                                    try {
                                        const mediaParts = media.media_parts || [];
                                        mediaParts?.splice(index, 1);
                                        this.setState((curr) => ({...curr, media}));
                                    } catch (_) {
                                    }
                                }}
                            />
                        )
                    }
                    <Button
                        variant={"contained"} color={"primary"}
                        onClick={() => {
                            const newPart = {
                                id: undefined,
                                media_id: this.props.media.id,
                                crop_area: [0, 100, 0, 100],
                                timestamp_range_start: 0,
                                timestamp_range_end: undefined,
                                notes: "",
                            };
                            this.props.media.media_parts = this.props.media.media_parts || [];
                            this.props.media.media_parts.push(newPart);
                            this.setState((curr) => ({...curr}));
                        }}
                    >
                        New Part
                    </Button>
                </Stack> : null
            }
        </div>
    }
}
