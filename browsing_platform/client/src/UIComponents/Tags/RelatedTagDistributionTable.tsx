import React from 'react';
import {Table, TableBody, TableCell, TableHead, TableRow, Typography} from '@mui/material';
import {ITagStat} from '../../types/tags';

interface RelatedTagDistributionTableProps {
    stats: ITagStat[];
}

/**
 * Renders the distribution of tags assigned to an account's related accounts
 * (related = follow/like/comment/tag ties, in both directions). Shared by the
 * account page section and the community-detection score tooltip.
 */
export default function RelatedTagDistributionTable({stats}: RelatedTagDistributionTableProps) {
    if (stats.length === 0) {
        return <Typography variant="body2" color="text.secondary">No tag data for related accounts.</Typography>;
    }
    return (
        <Table size="small" sx={{maxWidth: 480}}>
            <TableHead>
                <TableRow>
                    <TableCell>Tag</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell align="right">Count</TableCell>
                </TableRow>
            </TableHead>
            <TableBody>
                {stats.map(s => (
                    <TableRow key={s.tag_id}>
                        <TableCell>{s.tag_name}</TableCell>
                        <TableCell>{s.tag_type_name}</TableCell>
                        <TableCell align="right">×{s.count}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}
