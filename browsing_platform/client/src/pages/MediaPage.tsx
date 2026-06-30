import React, {useEffect, useMemo} from 'react';
import {useParams, useSearchParams} from "react-router";
import {Typography,} from "@mui/material";
import MediaPartFocusModal from "../UIComponents/Entities/MediaPartFocusModal";
import {fetchArchivingSessionsMedia, fetchMedia} from "../services/DataFetcher";
import EntitiesViewer from "../UIComponents/Entities/EntitiesViewer";
import ArchivingSessionsList from "../UIComponents/Entities/ArchivingSessionsList";
import {EntityViewerConfig} from "../UIComponents/Entities/EntitiesViewerConfig";
import cookie from "js-cookie";
import LinkSharing from "../UIComponents/LinkSharing/LinkSharing";
import DataLoadGuard from "./DataLoadGuard";
import {getShareTokenFromHref} from "../services/linkSharing";
import {useEntityPageState} from "./useEntityPageState";
import PageShell, {PageSubtitleLoading} from "./PageShell";

export default function MediaPage() {
    const {id: idParam, platformId} = useParams();

    const apiRef: number | string | null = useMemo(() => {
        if (platformId) return `pk/${platformId}`;
        if (idParam) return parseInt(idParam);
        return null;
    }, [idParam, platformId]);

    const shareMode = !!getShareTokenFromHref();
    const hideHeader = shareMode;
    const disableAnnotator = shareMode;

    const {data, loadingData, fetchError, sessions, loadingSessions, dbId} = useEntityPageState(
        apiRef,
        (ref) => fetchMedia(ref, {
            flattened_entities_transform: {retain_only_media_with_local_files: true, local_files_root: null},
            nested_entities_transform: {retain_only_posts_with_media: true, retain_only_accounts_with_posts: false},
        }),
        (id) => fetchArchivingSessionsMedia(id, {}),
        (result) => result.accounts?.[0]?.account_posts?.[0]?.post_media?.[0]?.id ?? null,
        'Failed to load media',
    );

    useEffect(() => {
        if (loadingData) {
            document.title = 'Media - Loading... | Browsing Platform';
        } else {
            const media = data?.accounts?.[0]?.account_posts?.[0]?.post_media?.[0];
            const author = data?.accounts?.[0];
            const authorName = author?.display_name || author?.url;
            document.title = media
                ? `Media #${media.id} by ${authorName || 'Unknown'} | Browsing Platform`
                : 'Media | Browsing Platform';
        }
    }, [loadingData, data]);

    const renderData = () => (
        <DataLoadGuard loadingData={loadingData} fetchError={fetchError} data={data}>
            <EntitiesViewer
                entities={data!}
                viewerConfig={
                    new EntityViewerConfig({
                        account: {
                            annotator: "disable",
                        },
                        post: {
                            annotator: "disable",
                        },
                        media: {
                            style: {
                                width: '80vw',
                                maxHeight: '80vh',
                            },
                            annotator: disableAnnotator ? "disable" : "show",
                        },
                        mediaPart: {
                            display: "display",
                            annotator: disableAnnotator ? "disable" : "show"
                        }
                    })
                }
            />
        </DataLoadGuard>
    );

    const primaryMedia = data?.accounts?.[0]?.account_posts?.[0]?.post_media?.[0];
    const stableSharePath = primaryMedia?.id_on_platform ? `/media/pk/${primaryMedia.id_on_platform}` : undefined;
    const isLoggedIn = !!(cookie.get("token"));

    // ?part_id=… brings a single segment into focus once the enriched media (with its nested parts)
    // has loaded.
    const [searchParams, setSearchParams] = useSearchParams();
    const focusPartId = searchParams.get("part_id");
    const focusedPart = useMemo(
        () => focusPartId
            ? (primaryMedia?.media_parts || []).find(p => String(p.id) === focusPartId)
            : undefined,
        [focusPartId, primaryMedia],
    );
    const clearFocusPart = () => {
        const next = new URLSearchParams(searchParams);
        next.delete("part_id");
        setSearchParams(next, {replace: true});
    };

    return (
        <PageShell
            hideMenu={hideHeader}
            title="Media Data"
            subtitle={<PageSubtitleLoading data={data}><Typography noWrap>{primaryMedia?.url}</Typography></PageSubtitleLoading>}
            headerRight={isLoggedIn && dbId ? <LinkSharing entityType={"media"} entityId={dbId} stableSharePath={stableSharePath}/> : undefined}
        >
            {renderData()}
            {primaryMedia && focusedPart && (
                <MediaPartFocusModal open onClose={clearFocusPart} media={primaryMedia} part={focusedPart}/>
            )}
            {!fetchError && <ArchivingSessionsList sessions={sessions} loadingSessions={loadingSessions}/>}
        </PageShell>
    );
}
