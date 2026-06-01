import {E_ENTITY_TYPES} from '../types/entities';

// Single client-side source of truth for tag-filter scopes.
//
// Tag scopes selectable per searched entity. The first entry is the entity itself (the default,
// always-on scope); the rest broaden the filter to tags on related entities. This mirrors the
// backend whitelist derived from `_SCOPE_BRANCHES` in services/search.py — the two are kept in
// sync manually across the language boundary, so any change here must be matched there.
export const SCOPE_OPTIONS: Partial<Record<E_ENTITY_TYPES, E_ENTITY_TYPES[]>> = {
    media:   ["media", "post", "account", "media_part"],
    post:    ["post", "media", "account", "media_part"],
    account: ["account", "post", "media", "media_part"],
};

// Every entity type that may legitimately appear in the `ts` URL param / tag_scopes payload,
// derived from SCOPE_OPTIONS so the accepted set can never drift from what the UI offers.
export const VALID_TAG_SCOPES: E_ENTITY_TYPES[] =
    Array.from(new Set(Object.values(SCOPE_OPTIONS).flat().filter((s): s is E_ENTITY_TYPES => !!s)));

// The default scope set for a searched entity: just the entity itself (or none when not taggable).
export const defaultScopesFor = (entity?: E_ENTITY_TYPES): E_ENTITY_TYPES[] =>
    entity ? [entity] : [];

// Resolve an incoming (possibly empty/undefined) scope list to the effective set used by the UI
// and sent to the backend, applying the default-to-entity fallback in one place.
export const resolveScopes = (
    tagScopes: E_ENTITY_TYPES[] | undefined,
    entity?: E_ENTITY_TYPES,
): E_ENTITY_TYPES[] => (tagScopes && tagScopes.length ? tagScopes : defaultScopesFor(entity));

// True when `scopes` is just the entity's own default scope (nothing broadened) — used to keep
// the default out of shareable URLs.
export const isDefaultScopes = (
    scopes: E_ENTITY_TYPES[] | undefined,
    entity?: E_ENTITY_TYPES,
): boolean => {
    const resolved = resolveScopes(scopes, entity);
    return entity ? (resolved.length === 1 && resolved[0] === entity) : resolved.length === 0;
};
