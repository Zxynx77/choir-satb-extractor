import json
import os

log_path = r"C:\Users\Zxynx\.gemini\antigravity\brain\abd96fab-66a9-4a03-b351-813d12eed780\.system_generated\logs\transcript_full.jsonl"
target_file = r"C:\Users\Zxynx\.gemini\antigravity\scratch\choir-satb-extractor\backend\analyzer.py"

versions = []

with open(log_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for tc in data['tool_calls']:
                    if tc.get('name') == 'default_api:write_to_file' or tc.get('name') == 'default_api:multi_replace_file_content':
                        args = tc.get('arguments', {})
                        if args.get('TargetFile') == target_file:
                            versions.append({
                                'step_index': data.get('step_index'),
                                'tool': tc.get('name'),
                                'args': args
                            })
        except:
            pass

print(f"Found {len(versions)} modifications to analyzer.py.")
for idx, v in enumerate(versions):
    print(f"Version {idx}: Step {v['step_index']}, Tool: {v['tool']}")
    if 'CodeContent' in v['args']:
        print(f"  Content length: {len(v['args']['CodeContent'])}")
    if 'ReplacementChunks' in v['args']:
        print(f"  Replacements: {len(v['args']['ReplacementChunks'])}")

# Save all versions to a JSON file for easy inspection
with open(r"C:\Users\Zxynx\.gemini\antigravity\scratch\choir-satb-extractor\analyzer_versions.json", "w", encoding='utf-8') as out:
    json.dump(versions, out, indent=2)
