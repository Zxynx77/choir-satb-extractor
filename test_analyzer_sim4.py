from music21 import *

s = stream.Score()
p = stream.Part()
p.insert(0, key.KeySignature(4)) # E major

n1 = note.Note('B4')
n2 = note.Note(71)

p.append(n1)
p.append(n2)

s.append(p)
s = s.makeMeasures()
s.write('musicxml', fp='test_analyzer_sim4.xml')
