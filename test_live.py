import requests
import json

url = "https://choir-satb-extractor.onrender.com/analyze"
print("Uploading test file to the live Render backend...")

# We need a dummy midi file to upload. 
# Let's create a tiny one.
from music21 import stream, note, midi
s = stream.Stream()
s.append(note.Note('C4'))
s.write('midi', fp='test.mid')

files = {'file': ('test.mid', open('test.mid', 'rb'), 'audio/midi')}
response = requests.post(url, files=files)

print("Status Code:", response.status_code)
try:
    print(json.dumps(response.json(), indent=2))
except:
    print("Response Text:", response.text)
