from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, clef.TrebleClef())
p.insert(0, meter.TimeSignature('4/4'))
p.insert(0, key.KeySignature(0))

for pitch_val in [64.0, 67.0, 72.0, 71.0, 69.0]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)
s.write('musicxml', fp='test.xml')
