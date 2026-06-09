"""
V034 — Backfill the account `bio` column from the profile biography in the archives

Until the accompanying extractor change, the Instagram biography was dropped at
parse time: the viewed subject's bio lives in the archives only inside the
PolarisProfilePageContentQuery GraphQL response (`data.user.biography`), which is
served from the `/api/graphql` endpoint — a URL the old parser did not route to
the GraphQL extractor (it matched only `graphql/query`). (The profile-page HTML
`PolarisViewer` bootstrap carries only the logged-in operator's own profile, not
the subject, so it is not a usable bio source.) As a result every `account.bio` /
`account_archive.bio` is NULL, and the parsed-structure JSON
(`archive_session.structures`) and the entity `data` columns contain no biography
at all. A pure SQL backfill is therefore impossible — the data must be recovered
from the original archive sources.

This migration re-parses each session's source archive (WACZ or HAR) with the
now-fixed extractor, extracts the profile biography, and fills ONLY the `bio`
columns:

  * `account_archive.bio` — per session, matched to the account by id_on_platform
    (and by url_suffix as a fallback), filled only where currently empty.
  * `account.bio` (canonical) — backfilled from the non-empty archive snapshots.

It is idempotent (only ever fills an empty bio), touches no other column or the
`data` JSON, and is safe to re-run. Sessions whose source archive is not present
on this machine are skipped with a warning (their bio simply stays NULL until the
source is available and the pipeline / this migration is re-run).

Reuses `convert_structure_to_entities`, so the bio length cap and the url_suffix
normalization match the live ingestion exactly.

NOTE: WACZ sources are scanned STRUCTURE-ONLY here. The pipeline's `scan_wacz`
also re-extracts and writes media (videos/photos/PAR2) into the archive dir as a
side effect — undesirable and unnecessary for a bio backfill — so this migration
reads the WARC records directly and parses only the GraphQL/HTML responses (the
biography arrives via the GraphQL `/api/graphql` response). The HAR path
(`structures_from_har`) has no media side effects and is reused as-is.
"""

import json
import traceback
import zipfile

from warcio.archiveiterator import ArchiveIterator

import root_anchor
from db_loaders.db_intake import LOCAL_ARCHIVES_DIR_ALIAS, LOCAL_WACZ_ARCHIVES_DIR_ALIAS
from extractors.structures_extraction import structures_from_har
from extractors.structures_extraction_graphql import extract_graphql_from_response, is_graphql_url
from extractors.structures_extraction_html import extract_data_from_html_entry
from extractors.structures_from_wacz import _decode_response_body, _make_minimal_har_request
from extractors.structures_to_entities import convert_structure_to_entities


def _structures_from_wacz_no_media(wacz_path):
    """Structure-only scan of a WACZ: iterate WARC response records and parse the
    GraphQL and HTML responses (the only carriers of biography). Deliberately
    skips all media extraction/writing that `scan_wacz` performs, so no files are
    written into the archive directory."""
    structures = []
    with zipfile.ZipFile(wacz_path) as zf:
        warc_names = [
            n for n in zf.namelist()
            if (n.startswith('archive/') or n.startswith('data/'))
            and (n.endswith('.warc') or n.endswith('.warc.gz'))
        ]
        for warc_name in warc_names:
            with zf.open(warc_name) as warc_file:
                for record in ArchiveIterator(warc_file):
                    if record.rec_type != 'response':
                        continue
                    url = record.rec_headers.get_header('WARC-Target-URI', '')
                    if not url or url.startswith('urn:'):
                        continue
                    status_code = record.http_headers.get_statuscode()
                    if status_code and str(status_code) not in ('200', '206'):
                        continue
                    ct = record.http_headers.get_header('Content-Type', '') or ''
                    clean_url = url.split('?__wb_method=')[0] if '?__wb_method=' in url else url
                    try:
                        if is_graphql_url(clean_url):
                            body = _decode_response_body(record)
                            if body:
                                structure = extract_graphql_from_response(json.loads(body))
                                if structure:
                                    structures.append(structure)
                        elif ct.startswith('text/html'):
                            body = _decode_response_body(record)
                            if body:
                                structure = extract_data_from_html_entry(
                                    body.decode('utf-8', errors='replace'),
                                    _make_minimal_har_request(clean_url),
                                )
                                if structure:
                                    structures.append(structure)
                    except Exception as e:
                        print(f"      WACZ record parse error for {clean_url}: {e}")
    return structures


def _bios_from_structures(structures) -> tuple[dict, dict]:
    """Reduce parsed structures to {id_on_platform: bio} and {url_suffix: bio}
    maps, keeping only accounts that carry a non-empty biography. Reusing the
    real entity conversion gives us the same url_suffix normalization and bio
    truncation the ingestion pipeline applies."""
    bios_by_id: dict[str, str] = {}
    bios_by_suffix: dict[str, str] = {}
    for structure in structures:
        try:
            entities = convert_structure_to_entities(structure)
        except Exception as e:
            print(f"      structure conversion failed: {e}")
            continue
        for account in entities.accounts:
            if not account.bio:
                continue
            if account.id_on_platform:
                bios_by_id[account.id_on_platform] = account.bio
            if account.url_suffix:
                bios_by_suffix[account.url_suffix] = account.bio
    return bios_by_id, bios_by_suffix


def _reparse_session(archive_location: str, source_type: str):
    """Locate and re-parse a session's source archive exactly as parse_archives
    does. Returns the list of parsed structures, or None if the source file is
    absent on this machine."""
    if source_type == "local_wacz":
        archive_name = archive_location.split(f"{LOCAL_WACZ_ARCHIVES_DIR_ALIAS}/")[-1]
        archive_dir = root_anchor.ROOT_ARCHIVES / archive_name
        wacz_path = archive_dir / "archive.wacz"
        if not wacz_path.exists():
            print(f"      source missing, skipping: {wacz_path}")
            return None
        return _structures_from_wacz_no_media(wacz_path)
    else:
        archive_name = archive_location.split(f"{LOCAL_ARCHIVES_DIR_ALIAS}/")[-1]
        har_path = root_anchor.ROOT_ARCHIVES / archive_name / "archive.har"
        if not har_path.exists():
            print(f"      source missing, skipping: {har_path}")
            return None
        return structures_from_har(har_path)


def run(cnx):
    cur = cnx.cursor()
    try:
        cur.execute(
            "SELECT id, archive_location, source_type FROM archive_session "
            "WHERE archive_location IS NOT NULL AND source_type IN ('local_har', 'local_wacz')"
        )
        sessions = cur.fetchall()
        print(f"    V034: {len(sessions)} session(s) to re-parse for biographies")

        archive_updates = 0
        parsed_sessions = 0
        skipped_sessions = 0

        for session_id, archive_location, source_type in sessions:
            try:
                structures = _reparse_session(archive_location, source_type or "local_har")
            except Exception as e:
                traceback.print_exc()
                print(f"      session {session_id}: re-parse failed: {e}")
                skipped_sessions += 1
                continue
            if structures is None:
                skipped_sessions += 1
                continue

            bios_by_id, bios_by_suffix = _bios_from_structures(structures)
            if not bios_by_id and not bios_by_suffix:
                parsed_sessions += 1
                continue

            # Fill this session's archive rows where bio is still empty. Match on
            # id_on_platform first (most reliable), then url_suffix as a fallback.
            for id_on_platform, bio in bios_by_id.items():
                cur.execute(
                    "UPDATE account_archive SET bio = %s "
                    "WHERE archive_session_id = %s AND id_on_platform = %s "
                    "  AND (bio IS NULL OR bio = '')",
                    (bio, session_id, id_on_platform),
                )
                archive_updates += cur.rowcount
            for url_suffix, bio in bios_by_suffix.items():
                cur.execute(
                    "UPDATE account_archive SET bio = %s "
                    "WHERE archive_session_id = %s AND url_suffix = %s "
                    "  AND (bio IS NULL OR bio = '')",
                    (bio, session_id, url_suffix),
                )
                archive_updates += cur.rowcount

            parsed_sessions += 1

        print(
            f"    V034: re-parsed {parsed_sessions} session(s), "
            f"skipped {skipped_sessions} (missing/failed source), "
            f"{archive_updates} account_archive row(s) updated"
        )

        # Backfill canonical accounts from their non-empty archive snapshots,
        # preferring the LATEST bio (by capture time) — a user's current bio, not
        # an arbitrary one. (A future change may instead retain the full bio
        # history the way `identifiers` keeps old handles; for now we keep only
        # the most recent value.) Rank snapshots per canonical by the session's
        # archiving_timestamp, falling back to the row create_date when it is
        # null, and break ties on the newest archive row.
        cur.execute(
            """UPDATE account a
               JOIN (
                   SELECT canonical_id, bio FROM (
                       SELECT aa.canonical_id, aa.bio,
                              ROW_NUMBER() OVER (
                                  PARTITION BY aa.canonical_id
                                  ORDER BY COALESCE(s.archiving_timestamp, aa.create_date) DESC,
                                           aa.id DESC
                              ) AS rn
                       FROM account_archive aa
                       LEFT JOIN archive_session s ON s.id = aa.archive_session_id
                       WHERE aa.bio IS NOT NULL AND aa.bio <> '' AND aa.canonical_id IS NOT NULL
                   ) ranked
                   WHERE rn = 1
               ) x ON a.id = x.canonical_id
               SET a.bio = x.bio
               WHERE a.bio IS NULL OR a.bio = ''"""
        )
        print(f"    V034: {cur.rowcount} canonical account(s) backfilled")

        cnx.commit()
    finally:
        cur.close()
