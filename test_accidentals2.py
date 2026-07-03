from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(4)) # E major

n = note.Note(68) # G#4
n.pitch.accidental = accidental.Accidental('sharp')
n.pitch.accidental.displayStatus = True
p.append(n)

s.append(p)
s.write('musicxml', fp='test_accidentals_before.xml')

s2 = s.makeMeasures()
s2.makeAccidentals(useKeySignature=True, overrideStatus=True)
s2.write('musicxml', fp='test_accidentals_after.xml')
