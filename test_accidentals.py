from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(4)) # E major (4 sharps: F#, C#, G#, D#)

# G#4, E4, F#4
for pitch_val in [68, 64, 66]:
    n = note.Note(pitch_val)
    p.append(n)

s.append(p)
s.write('musicxml', fp='test_accidentals_before.xml')

# Now apply makeMeasures and makeAccidentals
s2 = s.makeMeasures()
s2.makeAccidentals(useKeySignature=True, overrideStatus=True)
s2.write('musicxml', fp='test_accidentals_after.xml')
