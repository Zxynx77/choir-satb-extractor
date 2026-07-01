import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from analyzer import process_midi

app = FastAPI(title="Choir SATB AI Part Writer")

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = os.path.join(tempfile.gettempdir(), "choir_satb")
os.makedirs(TEMP_DIR, exist_ok=True)

SUPPORTED_MUSIC_FORMATS = ('.mid', '.midi', '.musicxml', '.xml', '.mxl')
SUPPORTED_IMAGE_FORMATS = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif')
SUPPORTED_DOC_FORMATS = ('.pdf',)

ALL_SUPPORTED = SUPPORTED_MUSIC_FORMATS + SUPPORTED_IMAGE_FORMATS + SUPPORTED_DOC_FORMATS

def cleanup_old_files(directory="output", age_hours=24):
    """Deletes files in the given directory older than age_hours."""
    if not os.path.exists(directory):
        return
    import time
    current_time = time.time()
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            file_age = current_time - os.path.getmtime(filepath)
            if file_age > (age_hours * 3600):
                try:
                    os.remove(filepath)
                except Exception as e:
                    print(f"Failed to delete old file {filepath}: {e}")

@app.post("/analyze")
async def analyze_midi(
    file: UploadFile = File(...),
    soprano_min: str = Form("C4"),
    soprano_max: str = Form("A5"),
    alto_min: str = Form("A3"),
    alto_max: str = Form("E5"),
    tenor_min: str = Form("D3"),
    tenor_max: str = Form("A4"),
    bass_min: str = Form("F2"),
    bass_max: str = Form("D4"),
    harmony_style: str = Form("close"),
    tempo_bpm: int = Form(None),
    instrument_type: str = Form('choir'),
    chord_overrides: str = Form(''),
    keep_parts: str = Form(''),
    key_override: str = Form('')
):
    """
    Receives a music file (MIDI, MusicXML, image of sheet music, or PDF),
    processes it, applies the Viterbi SATB harmonization, and returns 
    the generated individual parts, a combined MIDI, and a MusicXML score.
    """
    # Clean up old generated files to save disk space
    cleanup_old_files(TEMP_DIR, 1)
    
    ext = os.path.splitext(file.filename)[1].lower()
    
    if ext not in ALL_SUPPORTED:
        return JSONResponse(
            status_code=400, 
            content={"message": f"Unsupported file type '{ext}'. Supported: MIDI (.mid), MusicXML (.musicxml, .xml, .mxl), Images (.png, .jpg), PDF (.pdf)"}
        )

    ranges = {
        'soprano_min': soprano_min, 'soprano_max': soprano_max,
        'alto_min': alto_min, 'alto_max': alto_max,
        'tenor_min': tenor_min, 'tenor_max': tenor_max,
        'bass_min': bass_min, 'bass_max': bass_max,
    }

    input_path = os.path.join(TEMP_DIR, f"input_{file.filename}")
    with open(input_path, "wb") as buffer:
        buffer.write(await file.read())

    try:
        converted_path = input_path
        
        # If it's an image, run OMR to convert to MusicXML first
        if ext in SUPPORTED_IMAGE_FORMATS:
            from omr_engine import image_to_musicxml
            converted_path = image_to_musicxml(input_path, TEMP_DIR)
            print(f"OMR converted image to: {converted_path}")
        
        # Process through the harmonizer
        user_tempo = tempo_bpm if tempo_bpm > 0 else None
        keep_parts_list = [p.strip() for p in keep_parts.split(',')] if keep_parts else []
        result = process_midi(converted_path, ranges, TEMP_DIR, harmony_style, user_tempo, instrument_type, chord_overrides, keep_parts_list, key_override)
        
        return JSONResponse(content={
            "success": True,
            "message": "Analysis successful",
            "files": result["files"],
            "errors": result["errors"],
            "key": result.get("key", "Unknown"),
            "tempo": result.get("tempo"),
            "audio_error": result.get("audio_error", "None"),
            "input_type": "image_omr" if ext in SUPPORTED_IMAGE_FORMATS else "direct"
        })
    except ImportError as e:
        return JSONResponse(
            status_code=500, 
            content={"message": f"OMR dependencies not installed. Run: pip install opencv-python-headless numpy. Error: {str(e)}"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"message": str(e)})
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        # Clean up converted file if different from input
        if converted_path != input_path and os.path.exists(converted_path):
            pass  # Keep it for now, cleanup later

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="audio/midi", filename=filename)
    return JSONResponse(status_code=404, content={"message": "File not found."})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
