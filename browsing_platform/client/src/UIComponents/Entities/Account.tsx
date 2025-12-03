import React from 'react';
import {IAccountAndAssociatedEntities} from "../../types/entities";
import {Button, CircularProgress, Collapse, IconButton, Paper, Stack, Typography} from "@mui/material";
import LinkIcon from '@mui/icons-material/Link';
import MoreHorizIcon from '@mui/icons-material/MoreHoriz';
import Post from "./Post";
import ReactJson from "react-json-view";
import {fetchAccountData} from "../../services/DataFetcher";
import {EntityViewerConfig} from "./EntitiesViewerConfig";
import EntityAnnotator from "./Annotator";

interface IProps {
    account: IAccountAndAssociatedEntities
    viewerConfig?: EntityViewerConfig
}

interface IState {
    account: IAccountAndAssociatedEntities
    expandDetails: boolean
    postsToShow: number
    awaitingDetailsFetch: boolean
}


export default class Account extends React.Component <IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            account: props.account,
            expandDetails: false,
            awaitingDetailsFetch: false,
            postsToShow: props.viewerConfig?.account?.postsPageSize || props.account.account_posts.length || 5,
        };
    }

    private fetchPostDetails = async () => {
        const account = this.state.account;
        const itemId = account.id;
        if (this.state.awaitingDetailsFetch || itemId === undefined || itemId === null) {
            return;
        }
        this.setState((curr => ({...curr, awaitingDetailsFetch: true})), async () => {
            this.state.account.data = await fetchAccountData(itemId);
            this.setState((curr => ({...curr, awaitingDetailsFetch: false, account})));
        });
    }

    render() {
        const account = this.state.account;
        return <Paper sx={{padding: '1em'}}>
            <Stack gap={0.5} sx={{height: "100%"}}>
                <Stack gap={1} direction={"row"} alignItems={"center"}>
                    <a href={account.url}>
                        <Typography variant={"body1"}>{account.url}</Typography>
                    </a>
                    <IconButton
                        color={"primary"}
                        href={"/account/" + account.id}
                    >
                        <LinkIcon/>
                    </IconButton>
                </Stack>
                {account.display_name ? <Typography variant="h4">{account.display_name}</Typography> : null}
                <Typography variant="caption">{account.bio}</Typography>
                <span>
                    <IconButton
                        size="small"
                        color={"primary"}
                        onClick={() => this.setState((curr) => ({
                            ...curr,
                            expandDetails: !curr.expandDetails
                        }), async () => {
                            if (this.state.expandDetails && (account.data === undefined || account.data === null)) {
                                await this.fetchPostDetails();
                            }
                        })}>
                        <MoreHorizIcon/>
                    </IconButton>
                </span>
                <Collapse in={this.state.expandDetails}>
                    {
                        this.state.awaitingDetailsFetch ?
                            <CircularProgress size={20}/> :
                            this.props.account.data ?
                                <ReactJson
                                    src={account.data}
                                    enableClipboard={false}
                                /> :
                                null
                    }
                </Collapse>
                {
                    this.props.viewerConfig?.account?.annotator === "show" && <Stack gap={1}>
                        <EntityAnnotator entity={this.state.account} entityType={"account"} readonly={false}/>
                    </Stack>
                }
                <Stack direction={"column"} sx={{width: "100%", flexGrow: 1}} gap={1}>
                    {
                        account.account_posts
                            .sort((a, b) => (new Date(b.publication_date || 0).getTime()) - (new Date(a.publication_date || 0).getTime()))
                            .slice(0, this.state.postsToShow)
                            .map((p, p_i) => {
                                return <React.Fragment key={p_i}>
                                    <Post post={p} viewerConfig={this.props.viewerConfig}/>
                                </React.Fragment>
                            })
                    }
                    {
                        this.props.viewerConfig?.account?.postsPageSize ?
                            <Button
                                variant="contained"
                                disabled={account.account_posts.length <= this.state.postsToShow}
                                onClick={() => this.setState((curr) => ({
                                    ...curr,
                                    postsToShow: (curr.postsToShow) + 5
                                }))}
                                onDoubleClick={() => this.setState({postsToShow: account.account_posts.length})}
                            >
                                Load More Posts
                            </Button>
                            : null
                    }
                </Stack>
            </Stack>
        </Paper>
    }
}
