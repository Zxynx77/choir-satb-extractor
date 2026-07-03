from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(4)) # E major

for pitch_val in [68, 64, 61, 66, 71, 61, 64, 68]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)
s = s.makeMeasures()
s.write('musicxml', fp='test_analyzer_sim3.xml')
