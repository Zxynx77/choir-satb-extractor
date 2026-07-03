from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, clef.BassClef())
p.insert(0, key.KeySignature(4)) # E major

# G#4, E4, C#4
for pitch_val in [68, 64, 61]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)

try:
    s = s.makeMeasures()
    s.makeAccidentals(useKeySignature=True, overrideStatus=True)
    print("makeMeasures succeeded")
except Exception as e:
    print("makeMeasures failed:", e)
