import {E_ENTITY_TYPES} from '../types/entities';

// Single client-side source of truth for tag-filter scopes.
//
// Tag scopes selectable per searched entity. The first entry is the entity itself (the default,
// always-on scope); the rest broaden the filter to tags on related entities. This mirrors the
// backend whitelist derived from `_SCOPE_BRANCHES` in services/search.py — the two are kept in
// sync manually across the language boundary, so any change here must be matched there.
export const SCOPE_OPTIONS: Partial<Record<E_ENTITY_TYPES, E_ENTITY_TYPES[]>> = {
    media:   ["media", "post", "account"],
    post:    ["post", "media", "account"],
    account: ["account", "post", "media"],
};

// Every entity type that may legitimately appear in the `ts` URL param / tag_scopes payload,
// derived from SCOPE_OPTIONS so the accepted set can never drift from what the UI offers.
export const VALID_TAG_SCOPES: E_ENTITY_TYPES[] =
    Array.from(new Set(Object.values(SCOPE_OPTIONS).flat().filter((s): s is E_ENTITY_TYPES => !!s)));

// The default scope set for a searched entity: every applicable scope is on (the filter consults
// tags across all related-entity types out of the box), falling back to just the entity itself
// when it has no scope whitelist, or none when not taggable.
export const defaultScopesFor = (entity?: E_ENTITY_TYPES): E_ENTITY_TYPES[] =>
    entity ? (SCOPE_OPTIONS[entity] ?? [entity]) : [];

// Resolve an incoming (possibly empty/undefined) scope list to the effective set used by the UI
// and sent to the backend, applying the default-to-entity fallback in one place.
export const resolveScopes = (
    tagScopes: E_ENTITY_TYPES[] | undefined,
    entity?: E_ENTITY_TYPES,
): E_ENTITY_TYPES[] => (tagScopes && tagScopes.length ? tagScopes : defaultScopesFor(entity));

// True when `scopes` matches the default set for the entity (nothing narrowed or broadened away
// from the default) — used to keep the default out of shareable URLs. Order-insensitive.
export const isDefaultScopes = (
    scopes: E_ENTITY_TYPES[] | undefined,
    entity?: E_ENTITY_TYPES,
): boolean => {
    const resolved = resolveScopes(scopes, entity);
    const def = defaultScopesFor(entity);
    return resolved.length === def.length && resolved.every(s => def.includes(s));
};
