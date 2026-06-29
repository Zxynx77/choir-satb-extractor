from analyzer import process_midi
from music21 import converter

ranges = {
    'soprano_min': 'C4', 'soprano_max': 'A5',
    'alto_min': 'A3', 'alto_max': 'E5',
    'tenor_min': 'D3', 'tenor_max': 'A4',
    'bass_min': 'F2', 'bass_max': 'D4'
}

res = process_midi('test_melody.mid', ranges, '.', harmony_style='close', tempo_bpm=100)

# Check MusicXML part names
if 'musicxml' in res['files']:
    score = converter.parse(res['files']['musicxml'])
    print("MusicXML Part Names:")
    for i, part in enumerate(score.parts):
        print(f"  Part {i+1}: partName='{part.partName}', id='{part.id}'")
    print("\nFixed!" if len(score.parts) == 4 else "\nIssue remains")
