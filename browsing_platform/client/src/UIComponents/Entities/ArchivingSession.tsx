import React from 'react';
import {IArchiveSession} from "../../types/entities";
import {Box, Card, CardContent, CardHeader, Divider, IconButton, Skeleton, Stack, Typography} from "@mui/material";
import {DataGrid} from "@mui/x-data-grid";
import {Download, LocalMovies} from "@mui/icons-material";
import {fetchArchivingSessionData} from "../../services/DataFetcher";
import {anchor_local_static_files} from "../../services/server";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import TextField from "@mui/material/TextField";
import {getShareTokenFromHref, SHARE_URL_PARAM} from "../../services/linkSharing";
import LinkIcon from "@mui/icons-material/Link";

interface IProps {
    archiveSession: IArchiveSession,
    viewerConfig?: EntityViewerConfig
}

interface IState {
    archiveSession: IArchiveSession,
    expandDetails: boolean
    awaitingDetailsFetch: boolean
}


const isPlayableVideo = (filename?: string) => {
    if (!filename) return false;
    const lower = filename.toLowerCase();
    const noSearch = lower.split('?')[0];
    return noSearch.endsWith('.mp4') || noSearch.endsWith('.ogg') || noSearch.endsWith('.webm');
}


export default class ArchiveSessionMetadata extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            archiveSession: props.archiveSession,
            expandDetails: false,
            awaitingDetailsFetch: false
        };
    }

    render() {
        const archiveSession = this.state.archiveSession;
        const metadata = archiveSession.metadata || {};
        // Convert metadata object to array of { key, value } for DataGrid
        const rows = Object.entries(metadata).map(([key, value], idx) => ({
            id: idx,
            key,
            value: typeof value === 'object' ? JSON.stringify(value) : String(value)
        }));

        const columns = [
            {field: 'key', headerName: 'Key', flex: 1},
            {field: 'value', headerName: 'Value', flex: 2}
        ];

        const shareToken = getShareTokenFromHref()

        return (
            <Stack
                direction={"column"}
                divider={<Divider orientation="horizontal" flexItem/>}
                sx={{width: 600}}
            >
                <Stack
                    direction={"row"}
                    alignItems={"center"}
                    justifyContent={"space-between"}
                    sx={{width: "100%", overflow: 'auto'}}
                >
                <Typography variant={"h6"}>Archiving Session {archiveSession.id}</Typography>
                {
                    this.props.viewerConfig?.all?.hideInnerLinks ? null : <IconButton
                        color={"primary"}
                        href={"/archive/" + archiveSession.id + (shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : '')}
                    >
                        <LinkIcon/>
                    </IconButton>
                }
                </Stack>
                <Stack
                    direction={"row"}
                    alignItems={"center"}
                    sx={{height: 400, width: "100%", overflow: 'auto'}}
                >
                    {
                        archiveSession.attachments?.screen_recordings?.map((sr) => {
                            const resourceUrl = anchor_local_static_files(sr) || undefined
                            if (isPlayableVideo(sr)) {
                                return <video
                                    key={sr}
                                    src={resourceUrl}
                                    style={{
                                        backgroundColor: '#000',
                                        maxWidth: 300,
                                        maxHeight: 300
                                    }}
                                    controls
                                />
                            } else {
                                return <Card sx={{width: 300}} key={sr}>
                                    <a
                                        title={"download video"}
                                        href={resourceUrl} target={"_blank"}
                                        style={{textDecoration: "none", color: "inherit"}}
                                    >
                                        <CardHeader
                                            avatar={<Skeleton animation="wave" variant="circular" width={40}
                                                              height={40}/>}
                                            title={<Skeleton
                                                animation="wave"
                                                height={10}
                                                width="80%"
                                                style={{marginBottom: 6}}
                                            />}
                                            subheader={<Skeleton animation="wave" height={10} width="40%"/>}
                                        />
                                        <Skeleton sx={{
                                            height: 190, width: "100%", maxWidth: "100%", cursor: "pointer",
                                            "& > *": {visibility: "visible"}
                                        }} animation="wave" variant="rectangular">
                                            <Stack
                                                direction={"column"} gap={1} alignItems={"center"}
                                                justifyContent={"center"}
                                                sx={{height: '100%', width: '100%'}}
                                            >
                                                <LocalMovies color={"primary"} fontSize="large"/>
                                                <Typography variant={"subtitle2"}>Video Can't Be Played In
                                                    Browser</Typography>
                                                <Stack
                                                    direction={"row"} gap={1} alignItems={"center"}
                                                    justifyContent={"center"}
                                                >
                                                    <Download color={"primary"}/>
                                                    <Typography variant={"body1"}>Click to Download</Typography>
                                                </Stack>
                                            </Stack>
                                        </Skeleton>
                                        <CardContent>
                                            <React.Fragment>
                                                <Skeleton animation="wave" height={10} style={{marginBottom: 6}}/>
                                                <Skeleton animation="wave" height={10} width="80%"/>
                                            </React.Fragment>
                                        </CardContent>
                                    </a>
                                </Card>
                            }
                        })
                    }
                </Stack>
                <Box sx={{height: 400, width: "100%", overflowY: 'auto'}}>
                    <DataGrid
                        rows={rows}
                        columns={columns}
                        hideFooterPagination
                        hideFooter
                    />
                </Box>
                {
                    this.props.viewerConfig?.archivingSession?.annotator === "show" && <Stack gap={1}>
                        <TextField
                            label={"Notes"}
                            multiline
                            value={archiveSession.notes || ""}
                            onChange={(e) => {
                                archiveSession.notes = e.target.value;
                                this.setState((curr) => ({...curr, archiveSession}))
                            }}
                        />
                    </Stack>
                }
            </Stack>
        );
    }
}
