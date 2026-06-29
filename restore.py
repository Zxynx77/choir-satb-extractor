import json
import os

log_path = r"C:\Users\Zxynx\.gemini\antigravity\brain\abd96fab-66a9-4a03-b351-813d12eed780\.system_generated\logs\transcript_full.jsonl"

with open(log_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for tc in data['tool_calls']:
                    if tc.get('name') == 'default_api:write_to_file':
                        args = tc.get('arguments', {})
                        if args.get('TargetFile', '').endswith('analyzer.py'):
                            code = args.get('CodeContent', '')
                            # Look for the version that has S-A < 12 and the new ranges (Alto: A3-E5)
                            # but does NOT have harmony_style parameter
                            if "def process_midi(input_path, ranges_str, output_dir):" in code and "pitch.Pitch('A3')" in code or "'A3'" in code:
                                if "harmony_style=" not in code:
                                    print("FOUND EXACT VERSION!")
                                    with open(r"C:\Users\Zxynx\.gemini\antigravity\scratch\choir-satb-extractor\backend\analyzer.py", "w", encoding='utf-8') as out:
                                        out.write(code)
                                    print("Wrote to analyzer.py")
                                    exit(0)
        except Exception as e:
            pass

print("Not found exactly.")
