import React from 'react';
import {IPostAndAssociatedEntities} from "../../types/entities";
import {CircularProgress, Collapse, IconButton, Paper, Stack, Typography} from "@mui/material";
import MoreHorizIcon from '@mui/icons-material/MoreHoriz';
import Media from "./Media";
import ReactJson from "react-json-view";
import LinkIcon from "@mui/icons-material/Link";
import {fetchPostData} from "../../services/DataFetcher";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import EntityAnnotator from "./Annotator";
import dayjs from "dayjs";
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

import {getShareTokenFromHref, SHARE_URL_PARAM} from "../../services/linkSharing";

dayjs.extend(utc);
dayjs.extend(timezone);

interface IProps {
    post: IPostAndAssociatedEntities
    viewerConfig?: EntityViewerConfig
}

interface IState {
    post: IPostAndAssociatedEntities
    expandDetails: boolean
    awaitingDetailsFetch: boolean
    savingAnnotations: boolean
}


export default class Post extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            post: props.post,
            expandDetails: false,
            awaitingDetailsFetch: false,
            savingAnnotations: false
        };
    }

    private fetchPostDetails = async () => {
        const post = this.state.post;
        const itemId = post.id;
        if (this.state.awaitingDetailsFetch || itemId === undefined || itemId === null) {
            return;
        }
        this.setState((curr => ({...curr, awaitingDetailsFetch: true})), async () => {
            post.data = await fetchPostData(itemId);
            this.setState((curr => ({...curr, awaitingDetailsFetch: false, post})));
        });
    }

    render() {
        const post = this.state.post;
        const dateRaw = post.publication_date;
        const date = dayjs.utc(dateRaw);
        const dateInUTC = date.utc().format('YYYY-MM-DD HH:mm:ss');
        const dateInGaza = date.tz('Asia/Jerusalem').format('YYYY-MM-DD HH:mm:ss');
        const shareToken = getShareTokenFromHref()
        return <Paper sx={{padding: '1em', boxSizing: 'border-box', width: '100%'}}>
            <Stack gap={0.5}>
                <Stack gap={1} direction={"row"} alignItems={"center"}>
                    <Typography variant={"body1"}>{post.url}</Typography>
                    {
                        this.props.viewerConfig?.all?.hideInnerLinks ? null : <IconButton
                            color={"primary"}
                            href={"/post/" + post.id + (shareToken ? `?${SHARE_URL_PARAM}=${shareToken}` : '')}
                        >
                            <LinkIcon/>
                        </IconButton>
                    }
                </Stack>
                <Typography variant="caption">{dateInUTC} (UTC+0)</Typography>
                <Typography variant="caption">{dateInGaza} (in Gaza)</Typography>
                {post.caption ? <Typography variant="body2">{post.caption}</Typography> : null}
                <span>
                    <IconButton
                        size="small"
                        color={"primary"}
                        onClick={() => this.setState((curr) => ({
                            ...curr,
                            expandDetails: !curr.expandDetails
                        }), async () => {
                            if (this.state.expandDetails && (post.data === undefined || post.data === null)) {
                                await this.fetchPostDetails();
                            }
                        })}
                    >
                        <MoreHorizIcon/>
                    </IconButton>
                </span>
                <Collapse in={this.state.expandDetails}>
                    {
                        this.state.awaitingDetailsFetch ?
                            <CircularProgress size={20}/> :
                            this.props.post.data ?
                                <ReactJson
                                    src={post.data}
                                    enableClipboard={false}
                                    style={{wordBreak: 'break-word'}}
                                /> :
                                null
                    }
                </Collapse>
                <Stack direction={"row"} useFlexGap={true} gap={1} flexWrap={"wrap"}>
                    {
                        post.post_media.map((m, m_i) => {
                            return <Media media={m} viewerConfig={this.props.viewerConfig} key={m_i}/>
                        })
                    }
                </Stack>
                {
                    this.props.viewerConfig?.post?.annotator !== "hide" ?
                        <EntityAnnotator
                            entity={this.state.post}
                            entityType={"post"}
                            readonly={this.props.viewerConfig?.post?.annotator === "disable"}
                        /> :
                        null
                }
            </Stack>
        </Paper>
    }
}
