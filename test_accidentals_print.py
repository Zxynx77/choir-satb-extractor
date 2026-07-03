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

print("Before:", s.recurse().notes[0].pitch.accidental.displayStatus)
for m in s.recurse().getElementsByClass('Measure'):
    m.makeAccidentals(overrideStatus=True, inPlace=True, searchKeySignatureByContext=True)

print("After:", s.recurse().notes[0].pitch.accidental.displayStatus)
