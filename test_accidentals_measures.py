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

for m in s.recurse().getElementsByClass('Measure'):
    m.makeAccidentals(overrideStatus=True, inPlace=True, searchKeySignatureByContext=True)

s.write('musicxml', fp='test_accidentals_measures.xml')
