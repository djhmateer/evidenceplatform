import React from 'react';
import withRouter, {IRouterProps} from "../services/withRouter";
import {Box, CircularProgress, Divider, Stack,} from "@mui/material";
import {IArchiveSession, IExtractedEntitiesNested} from "../types/entities";
import {fetchArchivingSessionsMedia, fetchMedia} from "../services/DataFetcher";
import EntitiesViewer from "../UIComponents/Entities/EntitiesViewer";
import TopNavBar from "../UIComponents/TopNavBar/TopNavBar";
import ArchivingSessionsList from "../UIComponents/Entities/ArchivingSessionsList";
import {EntityViewerConfig} from "../UIComponents/Entities/EntitiesViewerConfig";

type IProps = {} & IRouterProps;

interface IState {
    id: number | null;
    data: IExtractedEntitiesNested | null;
    loadingData: boolean;
    sessions: IArchiveSession[] | null;
    loadingSessions: boolean;
}

class MediaPage extends React.Component<IProps, IState> {
    constructor(props: IProps) {
        super(props);
        const idArg = this.props.params.id;
        const id = idArg === undefined ? null : parseInt(idArg);
        this.state = {
            id,
            data: null,
            loadingData: id !== null,
            sessions: null,
            loadingSessions: false,
        }
    }

    componentDidUpdate() {
        const id_param = this.props.params.id;
        const id = id_param === undefined ? null : parseInt(id_param);
        if (id !== this.state.id) {
            this.setState((curr) => ({...curr, id}), async () => {
                await Promise.all([
                    this.fetchData(),
                    this.fetchSessions(),
                ])
            })
        }
    }

    async componentDidMount() {
        await Promise.all([
            this.fetchData(),
            this.fetchSessions(),
        ])
    }

    fetchData = async () => {
        const id = this.state.id;
        if (id === null) {
            return;
        }
        this.setState((curr) => ({...curr, loadingData: true}), async () => {
            const data = await fetchMedia(
                id,
                {
                    flattened_entities_transform: {
                        retain_only_media_with_local_files: true,
                        local_files_root: null,
                    },
                    nested_entities_transform: {
                        retain_only_posts_with_media: true,
                        retain_only_accounts_with_posts: false,
                    }
                }
            )
            this.setState((curr) => ({...curr, data, loadingData: false}))
        });
    }

    fetchSessions = async () => {
        const id = this.state.id;
        if (id === null) {
            return;
        }
        this.setState((curr) => ({...curr, loadingSessions: true}), async () => {
            const sessions = await fetchArchivingSessionsMedia(id);
            this.setState((curr) => ({...curr, sessions, loadingSessions: false}))
        });
    }

    renderData() {
        const data = this.state.data;
        const loadingData = this.state.loadingData;
        if (loadingData) {
            return <Box sx={{display: "flex", justifyContent: "center", alignItems: "center", height: "100%"}}>
                <CircularProgress/>
            </Box>
        }
        if (!data) {
            return <div>No data</div>
        }
        return <EntitiesViewer
            entities={data}
            viewerConfig={
                new EntityViewerConfig({
                    media: {
                        style: {
                            maxWidth: '100%',
                            maxHeight: '75vh',
                        },
                        annotator: "show"
                    },
                    mediaPart: {
                        display: "display"
                    }
                })
            }
        />
    }

    render() {
        return <div className={"page-wrap"}>
            <TopNavBar>
                Media Data
            </TopNavBar>
            <div className={"page-content content-wrap"}>
                <Stack gap={2} sx={{width: '100%'}} divider={<Divider orientation="horizontal" flexItem/>}>
                    {this.renderData()}
                    <ArchivingSessionsList
                        sessions={this.state.sessions}
                        loadingSessions={this.state.loadingSessions}
                    />
                </Stack>
            </div>
        </div>
    }
}

export default withRouter(MediaPage);