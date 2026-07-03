from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, clef.BassClef())
p.insert(0, key.KeySignature(4)) # E major

n = note.Note(68) # G#4
n.pitch.accidental = pitch.Accidental('sharp')
n.pitch.accidental.displayStatus = True
p.append(n)
s.append(p)

s = s.makeMeasures()

s2 = s.makeAccidentals(useKeySignature=True, overrideStatus=True)
s2.write('musicxml', fp='test_accidentals_assigned.xml')

s.makeAccidentals(useKeySignature=True, overrideStatus=True, inPlace=True)
s.write('musicxml', fp='test_accidentals_inplace.xml')
