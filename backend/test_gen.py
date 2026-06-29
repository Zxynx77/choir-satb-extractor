from music21 import converter, stream, note, chord
import os

# Create and parse test melody
s = stream.Stream()
melody_notes = ['C5', 'D5', 'E5', 'F5', 'G5', 'A5', 'G5', 'F5', 'E5', 'D5', 'C5']
for n in melody_notes:
    s.append(note.Note(n, quarterLength=1.0))
s.write('midi', fp='test_melody.mid')

# Now parse it back like the analyzer does
score = converter.parse('test_melody.mid')
print("Elements via flatten().notesAndRests:")
for i, el in enumerate(score.flatten().notesAndRests):
    if el.isRest:
        print(f"  [{i}] REST dur={el.duration.quarterLength}")
    elif el.isNote:
        print(f"  [{i}] NOTE {el.nameWithOctave} midi={el.pitch.ps} dur={el.duration.quarterLength}")
    elif el.isChord:
        print(f"  [{i}] CHORD {[p.nameWithOctave for p in el.pitches]} dur={el.duration.quarterLength}")
