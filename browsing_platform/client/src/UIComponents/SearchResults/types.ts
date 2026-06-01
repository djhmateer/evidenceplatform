import {SearchResult} from '../../services/DataFetcher';
import {ITagWithType} from '../../types/tags';

export interface SearchResultsProps {
    results: SearchResult[];
    tagsMap?: Record<number, ITagWithType[]>;
    selectedIds?: Set<number>;
    onToggleSelected?: (id: number) => void;
    // When set, clicking the result calls this instead of navigating to the entity page
    onPrimaryClick?: (result: SearchResult) => void;
    // Desktop-only: render larger cells and auto-load full-res assets on scroll (media results)
    largeIcons?: boolean;
}
