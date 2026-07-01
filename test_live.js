const fs = require('fs');

async function runTest() {
  try {
    const formData = new FormData();
    // Assuming test.mid exists
    const fileBlob = new Blob([fs.readFileSync('test.mid')], { type: 'audio/midi' });
    formData.append('file', fileBlob, 'test.mid');
    
    console.log("Sending POST to https://choir-satb-extractor.onrender.com/analyze ...");
    const response = await fetch('https://choir-satb-extractor.onrender.com/analyze', {
      method: 'POST',
      body: formData
    });
    
    console.log(`Status: ${response.status} ${response.statusText}`);
    const text = await response.text();
    try {
      console.log(JSON.stringify(JSON.parse(text), null, 2));
    } catch (e) {
      console.log("Raw Response (not JSON):", text);
    }
  } catch (error) {
    console.error("Fetch failed:", error);
  }
}
runTest();
