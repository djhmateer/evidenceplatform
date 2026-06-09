import React, {useEffect, useMemo, useState} from 'react';
import {
    IAccountAndAssociatedEntities,
    IExtractedEntitiesNested,
    IPostAndAssociatedEntities
} from "../../types/entities";
import {Pagination, Stack} from "@mui/material";
import Post from "./Post";
import Account from "./Account";
import Media from "./Media";
import {EntityViewerConfig} from "./EntitiesViewerConfig";

interface IProps {
    entities: IExtractedEntitiesNested
    viewerConfig?: EntityViewerConfig
    highlightCommentId?: number
    highlightLikeId?: number
    highlightRelationId?: number
    hideAccountsWithoutPosts?: boolean
    accountsPageSize?: number | null
}

export default function EntitiesViewer({entities, viewerConfig, highlightCommentId, highlightLikeId, highlightRelationId, hideAccountsWithoutPosts, accountsPageSize}: IProps) {
    const sortedPosts = useMemo(() =>
        [...entities.posts].sort((a, b) =>
            (new Date(b.publication_date || 0).getTime()) - (new Date(a.publication_date || 0).getTime())
        ), [entities.posts]);

    const sortedAccounts = useMemo(() =>
        [...(entities.accounts ?? [])].sort(
            (a, b) => (b.account_posts?.length ?? 0) - (a.account_posts?.length ?? 0)
        ), [entities.accounts]);

    const filteredAccounts = useMemo(() =>
        hideAccountsWithoutPosts
            ? sortedAccounts.filter(a => (a.account_posts?.length ?? 0) > 0)
            : sortedAccounts
    , [sortedAccounts, hideAccountsWithoutPosts]);

    const paginate = typeof accountsPageSize === 'number' && accountsPageSize > 0;
    const pageCount = paginate ? Math.ceil(filteredAccounts.length / accountsPageSize!) : 1;

    const [page, setPage] = useState(1);
    useEffect(() => {
        if (page > pageCount) setPage(Math.max(1, pageCount));
    }, [page, pageCount]);

    const visibleAccounts = paginate
        ? filteredAccounts.slice((page - 1) * accountsPageSize!, page * accountsPageSize!)
        : filteredAccounts;

    const initialAccountTagsMap = entities.account_tags ?? {};

    return <Stack gap={1}>
        {paginate && pageCount > 1 &&
            <Pagination count={pageCount} page={page} onChange={(_, p) => setPage(p)}/>
        }
        {visibleAccounts.map((account: IAccountAndAssociatedEntities, index: number) =>
            <Account
                account={account}
                key={account.id ?? `idx-${(page - 1) * (accountsPageSize ?? 0) + index}`}
                viewerConfig={viewerConfig}
                highlightCommentId={highlightCommentId}
                highlightLikeId={highlightLikeId}
                highlightRelationId={highlightRelationId}
                initialAccountTagsMap={initialAccountTagsMap}
            />
        )}
        {sortedPosts.map((post: IPostAndAssociatedEntities, index: number) =>
            <Post
                post={post}
                key={index}
                viewerConfig={viewerConfig}
                highlightCommentId={highlightCommentId}
                highlightLikeId={highlightLikeId}
                initialAccountTagsMap={initialAccountTagsMap}
            />
        )}
        {entities.media.map((media, index: number) =>
            <Media media={media} key={index} viewerConfig={viewerConfig}/>
        )}
    </Stack>
}
