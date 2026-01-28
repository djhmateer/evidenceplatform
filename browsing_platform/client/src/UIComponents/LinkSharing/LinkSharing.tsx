import * as React from 'react';
import TextField from '@mui/material/TextField';
import {CircularProgress, Fab, IconButton, Tooltip, Typography} from "@mui/material";
import {ContentCopy, Share} from "@mui/icons-material";
import server from "../../services/server";
import InputAdornment from "@mui/material/InputAdornment";
import {NoMaxWidthTooltip} from "../StyledComponents/CustomTooltips";
import {SHARE_URL_PARAM} from "../../services/linkSharing";


type E_ENTITY_TYPES = "archiving_session" | "account" | "post" | "media" | "media_part"

interface IProps {
    entityType: E_ENTITY_TYPES,
    entityId: number,
}

interface IState {
    awaitingLinkFetch: boolean,
    sharedLink: string | null,
    generationError: string | null,
}

export default class LinkSharing extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            awaitingLinkFetch: false,
            sharedLink: null,
            generationError: null
        };
    }

    componentDidMount() {
        this.fetchShareLink();
    }

    componentDidUpdate = (prevProps: Readonly<IProps>, prevState: Readonly<IState>, snapshot?: any) => {
        if (prevProps.entityType !== this.props.entityType || prevProps.entityId !== this.props.entityId) {
            this.setState({sharedLink: null, awaitingLinkFetch: false, generationError: null}, () => {
                this.fetchShareLink();
            });
        }
    }

    shareLinkFromSuffix = (link_suffix: string) => {
        const url = new URL(window.location.href);
        url.searchParams.set(SHARE_URL_PARAM, link_suffix);
        return url.toString();
    }

    fetchShareLink = () => {
        if (this.state.sharedLink || this.state.awaitingLinkFetch) {
            return;
        }
        this.setState({awaitingLinkFetch: true}, async () => {
            const response: string | null = await server.get(`share/${this.props.entityType}/${this.props.entityId}/`);
            const sharedLink = response ? this.shareLinkFromSuffix(response) : null;
            this.setState({sharedLink, awaitingLinkFetch: false});
        })
    }

    generateShareLink = () => {
        this.setState({awaitingLinkFetch: true}, async () => {
            const response: {
                success: boolean,
                link_suffix: null | string,
                error: null | string
            } = await server.post(`share/`, {
                view: true,
                shared_entity: {
                    entity: this.props.entityType,
                    entity_id: this.props.entityId,
                }
            });
            if (response.success && response.link_suffix) {
                const sharedLink = this.shareLinkFromSuffix(response.link_suffix);
                this.setState({sharedLink, awaitingLinkFetch: false, generationError: null});
            } else {
                this.setState({generationError: response.error || "Unknown error", awaitingLinkFetch: false});
            }
        })
    }

    copyShareLinkToClipboard = () => {
        if (this.state.sharedLink) {
            navigator.clipboard.writeText(this.state.sharedLink);
            window.alert("Link copied to clipboard!");
        }
    }


    render() {
        return <NoMaxWidthTooltip
            title={
                this.state.awaitingLinkFetch ?
                    <CircularProgress size={"20"} color={"primary"}/> :
                    this.state.sharedLink ?
                        <TextField
                            value={this.state.sharedLink || ''}
                            size="small"
                            variant="outlined"
                            inputProps={{readOnly: true}}
                            InputProps={{
                                endAdornment: (
                                    <InputAdornment position="end">
                                        <Tooltip title="Copy">
                                            <IconButton size="small" onClick={this.copyShareLinkToClipboard}>
                                                <ContentCopy fontSize="small"/>
                                            </IconButton>
                                        </Tooltip>
                                    </InputAdornment>
                                )
                            }}
                            sx={{
                                padding: 0,
                                background: "white",
                                borderRadius: "inherit",
                                width: `${Math.max(10, (this.state.sharedLink || '').length)}ch`
                            }}
                        /> :
                        <Typography variant={"body2"}>Generate shareable link</Typography>
            }
            arrow
        >
            {
                this.state.awaitingLinkFetch ?
                    <CircularProgress size={20} color={"primary"}/> :
                    <Fab
                        size={"small"}
                        color={this.state.sharedLink ? "success" : "primary"}
                        onClick={
                            this.state.sharedLink ?
                                this.copyShareLinkToClipboard :
                                this.generateShareLink
                        }
                    >
                        <Share/>
                    </Fab>
            }
        </NoMaxWidthTooltip>
    }
}