from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(0))

# Try with floats
for pitch_val in [64.0, 67.0, 72.0, 71.0, 69.0]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)
s.write('musicxml', fp='test_float.xml')

s2 = stream.Score()
p2 = stream.Part()
p2.insert(0, key.KeySignature(0))

# Try with ints
for pitch_val in [64, 67, 72, 71, 69]:
    n = note.Note(pitch_val)
    p2.append(n)

s2.append(p2)
s2.write('musicxml', fp='test_int.xml')
