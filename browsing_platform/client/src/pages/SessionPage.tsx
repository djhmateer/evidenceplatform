import React, {useEffect, useState} from 'react';
import {useParams} from "react-router";
import {FormControlLabel, Stack, Switch, Tooltip, Typography,} from "@mui/material";
import {IArchiveSession, IExtractedEntitiesNested} from "../types/entities";
import {fetchArchivingSession} from "../services/DataFetcher";
import EntitiesViewer from "../UIComponents/Entities/EntitiesViewer";
import ArchivingSessionsList from "../UIComponents/Entities/ArchivingSessionsList";
import {EntityViewerConfig} from "../UIComponents/Entities/EntitiesViewerConfig";
import cookie from "js-cookie";
import LinkSharing from "../UIComponents/LinkSharing/LinkSharing";
import DataLoadGuard from "./DataLoadGuard";
import {getShareTokenFromHref} from "../services/linkSharing";
import PageShell, {PageSubtitleLoading} from "./PageShell";

export default function SessionPage() {
    const {id: idParam} = useParams();

    const id = idParam === undefined ? null : parseInt(idParam);
    const shareMode = !!getShareTokenFromHref();
    const hideHeader = shareMode;

    const [data, setData] = useState<IExtractedEntitiesNested | null>(null);
    const [loadingData, setLoadingData] = useState(id !== null);
    const [fetchError, setFetchError] = useState<string | null>(null);
    const [sessions, setSessions] = useState<IArchiveSession[] | null>(null);
    const [showAccountsWithoutPosts, setShowAccountsWithoutPosts] = useState(false);

    useEffect(() => {
        if (id === null) return;
        setLoadingData(true);
        setFetchError(null);
        fetchArchivingSession(id, {
            flattened_entities_transform: {
                retain_only_media_with_local_files: true,
                local_files_root: null,
            },
            nested_entities_transform: {
                retain_only_posts_with_media: true,
                retain_only_accounts_with_posts: false,
            }
        }).then(result => {
            setData(result.entities);
            setSessions([result.session]);
            setLoadingData(false);
        }).catch(err => {
            setFetchError(err?.message || 'Failed to load session');
            setLoadingData(false);
        });
    }, [id]);

    useEffect(() => {
        if (loadingData) {
            document.title = 'Session - Loading... | Browsing Platform';
        } else {
            document.title = id !== null ? `Session #${id} | Browsing Platform` : 'Session | Browsing Platform';
        }
    }, [loadingData, id]);

    const renderData = () => (
        <DataLoadGuard loadingData={loadingData} fetchError={fetchError} data={data}>
            <EntitiesViewer
                entities={data!}
                hideAccountsWithoutPosts={!showAccountsWithoutPosts}
                accountsPageSize={10}
                viewerConfig={
                    new EntityViewerConfig({
                        media: {
                            style: {
                                width: '350px',
                                maxHeight: '350px'
                            },
                        }
                    })
                }
            />
        </DataLoadGuard>
    );

    const isLoggedIn = !!(cookie.get("token"));
    return (
        <PageShell
            hideMenu={hideHeader}
            title="Archiving Session Data"
            subtitle={<PageSubtitleLoading data={data}><Typography>Session #{id}</Typography></PageSubtitleLoading>}
            headerRight={
                <Stack direction={"row"} alignItems={"center"} gap={2} sx={{flexShrink: 0}}>
                    <FormControlLabel
                        control={<Switch size={"small"} checked={showAccountsWithoutPosts}
                                         onChange={e => setShowAccountsWithoutPosts(e.target.checked)}/>}
                        label={"Show Accounts With 0 Posts"}
                        sx={{m: 0, whiteSpace: 'nowrap'}}
                    />
                    {isLoggedIn && id ? <LinkSharing entityType={"archiving_session"} entityId={id}/> : null}
                </Stack>
            }
        >
            {renderData()}
            <ArchivingSessionsList sessions={sessions} loadingSessions={loadingData}/>
        </PageShell>
    );
}
