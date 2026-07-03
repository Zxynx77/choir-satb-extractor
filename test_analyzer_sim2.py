from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(4)) # E major

for pitch_val in [68.0, 64.0, 61.0, 66.0, 71.0, 61.0, 64.0, 68.0]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)
s = s.makeMeasures()
s.write('musicxml', fp='test_analyzer_sim2.xml')
