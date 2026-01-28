import os

from fastapi import Request

from browsing_platform.server.services.archiving_session import ArchivingSessionTransform
from browsing_platform.server.services.enriched_entities import EntitiesTransformConfig, FlattenedEntitiesTransform, \
    NestedEntitiesTransform
from browsing_platform.server.services.permissions import parse_token_from_header
from browsing_platform.server.services.search import SearchResultTransform

SERVER_HOST = os.getenv("SERVER_HOST")


def extract_entities_transform_config(request: Request) -> EntitiesTransformConfig:
    params = request.query_params
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    config: EntitiesTransformConfig = EntitiesTransformConfig(
        flattened_entities_transform=FlattenedEntitiesTransform(
            access_token=params.get("st", None) or token,
            local_files_root=params.get("lfr", None) or SERVER_HOST,
            retain_only_media_with_local_files=params.get("mwf") == "true" if params.get("mwf") is not None else False,
            strip_raw_data=params.get("srd") is None or int(params.get("srd")),
        ),
        nested_entities_transform=NestedEntitiesTransform(
            retain_only_posts_with_media=params.get("pwm") == "true" if params.get("pwm") is not None else False,
            retain_only_accounts_with_posts=params.get("awp") == "true" if params.get("awp") is not None else False,
        )
    )
    return config


def extract_session_transform_config(request: Request) -> ArchivingSessionTransform:
    params = request.query_params
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    config: ArchivingSessionTransform = ArchivingSessionTransform(
        access_token=params.get("st", None) or token,
        local_files_root=params.get("lfr", None) or SERVER_HOST,
        properties_to_censor=[]
    )
    return config


def extract_search_results_config(request: Request) -> SearchResultTransform:
    params = request.query_params
    auth_header = request.headers.get("Authorization")
    token = parse_token_from_header(auth_header)
    config: SearchResultTransform = SearchResultTransform(
        access_token=token,
        local_files_root=params.get("lfr", None) or SERVER_HOST
    )
    return config
