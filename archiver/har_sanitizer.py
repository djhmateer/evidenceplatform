import json
from pathlib import Path

def sanitize_har(har_path: Path, output_path: Path):
    with open(har_path, 'r', encoding='utf-8') as f:
        har = json.load(f)

    for entry in har.get('log', {}).get('entries', []):
        # Remove sensitive headers from request
        entry['request']['headers'] = [
            h for h in entry['request']['headers']
            if h['name'].lower() not in ['cookie', 'authorization']
        ]
        # Remove sensitive headers from response
        entry['response']['headers'] = [
            h for h in entry['response']['headers']
            if h['name'].lower() not in ['set-cookie']
        ]
        # Optionally redact postData
        if 'postData' in entry['request']:
            entry['request']['postData']['text'] = '[REDACTED]'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(har, f, indent=2)

    print(f"Sanitized HAR file saved to {output_path}")
