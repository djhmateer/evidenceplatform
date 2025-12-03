import json
import traceback
from pathlib import Path
from typing import Union

import ijson

from extractors.models_har import HarRequest
from extractors.structures_extraction_api_v1 import extract_data_from_api_v1_entry, ApiV1Response
from extractors.structures_extraction_graphql import extract_data_from_graphql_entry, GraphQLResponse
from extractors.structures_extraction_html import extract_data_from_html_entry, PageResponse

StructureType = Union[GraphQLResponse, ApiV1Response, PageResponse]


def structures_from_har(har_path: Path) -> list[StructureType]:
    structures = []
    with open(har_path, "rb") as f:
        entries = ijson.items(f, "log.entries.item")
        for entry in entries:
            try:
                # GraphQL
                if "graphql/query" in entry["request"]["url"]:
                    res_json = entry["response"]["content"].get("text")
                    if not res_json:
                        continue
                    structure = extract_data_from_graphql_entry(json.loads(res_json), HarRequest(**entry["request"]))
                    if structure:
                        structures.append(structure)
                # API v1
                elif "instagram.com/api/v1/media/" in entry["request"]["url"] and not entry["response"]["content"].get("mimeType", "").startswith("text/html"):
                    res_json = entry["response"]["content"].get("text")
                    if not res_json:
                        continue
                    structure = extract_data_from_api_v1_entry(json.loads(res_json), HarRequest(**entry["request"]))
                    if structure:
                        structures.append(structure)
                # HTML
                elif entry["response"]["content"].get("mimeType", "").startswith("text/html"):
                    html_text = entry["response"]["content"].get("text")
                    if not html_text:
                        continue
                    structure = extract_data_from_html_entry(html_text, HarRequest(**entry["request"]))
                    if structure:
                        structures.append(structure)
            except Exception as e:
                print(f"Error processing entry: {e}")
                traceback.print_exc()
                pass
    return structures


def keep_only_requests_for_instagram_structures(har_path: Path, clean_original: bool = False):
    with open(har_path, "rb") as f:
        entries = ijson.items(f, "log.entries.item")
        relevant_entries = []
        for entry in entries:
            is_relevant = False
            try:
                # GraphQL
                if "graphql/query" in entry["request"]["url"]:
                    res_json = entry["response"]["content"].get("text")
                    if not res_json:
                        continue
                    structure = extract_data_from_graphql_entry(json.loads(res_json), HarRequest(**entry["request"]))
                    if structure:
                        is_relevant = True
                # API v1
                elif "instagram.com/api/v1/media/" in entry["request"]["url"] and not entry["response"]["content"].get("mimeType", "").startswith("text/html"):
                    res_json = entry["response"]["content"].get("text")
                    if not res_json:
                        continue
                    structure = extract_data_from_api_v1_entry(json.loads(res_json), HarRequest(**entry["request"]))
                    if structure:
                        is_relevant = True
                # HTML
                elif entry["response"]["content"].get("mimeType", "").startswith("text/html"):
                    html_text = entry["response"]["content"].get("text")
                    if not html_text:
                        continue
                    structure = extract_data_from_html_entry(html_text, HarRequest(**entry["request"]))
                    if structure:
                        is_relevant = True
            except Exception as e:
                print(f"Error processing entry: {e}")
                traceback.print_exc()
                pass
            if is_relevant:
                relevant_entries.append(entry)
        # Write the filtered entries back to a new HAR file
        filtered_har_path = har_path.with_name(har_path.stem + "_filtered.har")

    with open(har_path, "rb") as f_meta:
        with open(filtered_har_path, "w", encoding="utf-8") as f_filtered:
            har_data = {
                "log": dict()
            }
            for key, value in ijson.kvitems(f_meta, 'log'):
                if key == "entries":
                    har_data["log"]["entries"] = relevant_entries
                else:
                    har_data["log"][key] = value
            json.dump(har_data, f_filtered, indent=2, default=str)
    if clean_original:
        # Optionally remove the original HAR file
        har_path.unlink()
        print(f"Original HAR file {har_path} removed.")


def main(har_path):
    structures = structures_from_har(har_path)
    print(f"Extracted {len(structures)} posts.")
    keep_only_requests_for_instagram_structures(har_path)


if __name__ == '__main__':
    # Provide the path to your .har file and desired output folder
    har_file = input("Input path to HAR file: ")  # Replace with your actual HAR file
    har_file = har_file.strip().strip('"').strip("'")
    main(Path(har_file))