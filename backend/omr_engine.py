"""
Optical Music Recognition (OMR) Engine
Converts images of sheet music into MusicXML that music21 can read.

This uses OpenCV for image processing and a heuristic-based approach
to detect staff lines, note heads, and their positions on the staff.
"""
import os
import uuid
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from music21 import stream, note, meter, tempo, key, clef, pitch


# Staff line and note detection constants
STAFF_LINE_THRESHOLD = 0.6  # % of image width a horizontal line must span
NOTE_HEAD_MIN_AREA = 50
NOTE_HEAD_MAX_AREA = 800
NOTE_HEAD_ASPECT_RATIO_MAX = 2.5  # Width/Height ratio

# Map staff position (line/space number from bottom) to pitch
# In treble clef: bottom line = E4, top line = F5
# Positions: 0=E4, 1=F4, 2=G4, 3=A4, 4=B4, 5=C5, 6=D5, 7=E5, 8=F5
# Ledger lines below: -2=C4, -1=D4
# Ledger lines above: 9=G5, 10=A5
TREBLE_CLEF_PITCHES = {
    -4: 'A3', -3: 'B3', -2: 'C4', -1: 'D4',
    0: 'E4', 1: 'F4', 2: 'G4', 3: 'A4', 4: 'B4',
    5: 'C5', 6: 'D5', 7: 'E5', 8: 'F5',
    9: 'G5', 10: 'A5', 11: 'B5', 12: 'C6'
}

BASS_CLEF_PITCHES = {
    -4: 'C2', -3: 'D2', -2: 'E2', -1: 'F2',
    0: 'G2', 1: 'A2', 2: 'B2', 3: 'C3', 4: 'D3',
    5: 'E3', 6: 'F3', 7: 'G3', 8: 'A3',
    9: 'B3', 10: 'C4', 11: 'D4', 12: 'E4'
}


def preprocess_image(img_path):
    """Load and preprocess the sheet music image."""
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError(f"Could not read image: {img_path}")
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Adaptive threshold to handle varying lighting
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 15, 10
    )
    
    return img, gray, binary


def detect_staff_lines(binary, img_width):
    """
    Detect horizontal staff lines using morphological operations.
    Returns list of staff groups, each containing 5 y-coordinates.
    """
    # Use a wide horizontal kernel to detect staff lines
    kernel_width = img_width // 3
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    detected_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    
    # Find contours of detected lines
    contours, _ = cv2.findContours(detected_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Get y-coordinates of each line (center of bounding box)
    line_ys = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > img_width * STAFF_LINE_THRESHOLD:
            line_ys.append(y + h // 2)
    
    line_ys.sort()
    
    if len(line_ys) < 5:
        raise ValueError(f"Could not detect enough staff lines. Found {len(line_ys)}, need at least 5. "
                        "Make sure the image is a clear photo of sheet music with visible staff lines.")
    
    # Group lines into staves (groups of 5)
    staves = []
    current_staff = [line_ys[0]]
    
    for i in range(1, len(line_ys)):
        # If this line is close to the previous one, it's part of the same staff
        expected_gap = (current_staff[-1] - current_staff[0]) / max(len(current_staff) - 1, 1) if len(current_staff) > 1 else 20
        if expected_gap == 0:
            expected_gap = 20
            
        if line_ys[i] - line_ys[i-1] < expected_gap * 2.5:
            current_staff.append(line_ys[i])
        else:
            if len(current_staff) >= 5:
                staves.append(current_staff[:5])
            current_staff = [line_ys[i]]
    
    if len(current_staff) >= 5:
        staves.append(current_staff[:5])
    
    if not staves:
        raise ValueError("Could not group staff lines into staves. The image may be unclear.")
    
    return staves


def detect_note_heads(binary, staves, img_width):
    """
    Detect note heads by removing staff lines first, then finding elliptical blobs.
    Returns list of (x, y, is_filled) for each detected note head.
    """
    # Remove staff lines to isolate note heads
    cleaned = binary.copy()
    line_removal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (img_width // 4, 1))
    lines_only = cv2.morphologyEx(binary, cv2.MORPH_OPEN, line_removal_kernel, iterations=1)
    cleaned = cv2.subtract(cleaned, lines_only)
    
    # Dilate slightly to reconnect broken note heads
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.dilate(cleaned, dilate_kernel, iterations=1)
    
    # Find contours
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    note_heads = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < NOTE_HEAD_MIN_AREA or area > NOTE_HEAD_MAX_AREA:
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = w / max(h, 1)
        
        # Note heads are roughly circular/elliptical
        if aspect_ratio > NOTE_HEAD_ASPECT_RATIO_MAX or aspect_ratio < 0.4:
            continue
        
        center_x = x + w // 2
        center_y = y + h // 2
        
        # Check if filled (black) or hollow (white inside)
        mask = np.zeros_like(cleaned)
        cv2.drawContours(mask, [cnt], -1, 255, -1)
        mean_val = cv2.mean(binary, mask=mask)[0]
        is_filled = mean_val > 128  # Filled notes have more black pixels
        
        note_heads.append((center_x, center_y, is_filled))
    
    # Sort by x-coordinate (left to right = temporal order)
    note_heads.sort(key=lambda n: n[0])
    
    return note_heads


def map_note_to_pitch(note_y, staff_lines, use_treble=True):
    """
    Map a note head's y-coordinate to a pitch based on its position
    relative to the staff lines.
    """
    if len(staff_lines) < 5:
        return 'C4'  # Fallback
    
    # Calculate the gap between staff lines
    line_gap = (staff_lines[4] - staff_lines[0]) / 4.0
    half_gap = line_gap / 2.0
    
    # Bottom line is position 0, each line up is +2, each space is +1
    # Position relative to bottom line
    bottom_line_y = staff_lines[4]  # Staff lines are top-to-bottom, so index 4 = bottom
    
    # Distance from bottom line (negative = above, positive = below)
    distance = bottom_line_y - note_y
    
    # Convert to staff position (each half_gap = 1 position)
    position = round(distance / half_gap)
    
    pitch_map = TREBLE_CLEF_PITCHES if use_treble else BASS_CLEF_PITCHES
    
    # Clamp position to available range
    position = max(min(position, 12), -4)
    
    return pitch_map.get(position, 'C4')


def image_to_musicxml(img_path, output_dir):
    """
    Main OMR pipeline: image -> detected notes -> MusicXML file.
    Returns path to the generated MusicXML file.
    """
    if cv2 is None:
        raise ImportError("OpenCV (cv2) is required for image OMR. Install it with: pip install opencv-python-headless")
    
    print(f"OMR: Processing image {img_path}")
    
    img, gray, binary = preprocess_image(img_path)
    img_height, img_width = binary.shape
    
    print(f"OMR: Image size {img_width}x{img_height}")
    
    # Detect staff lines
    staves = detect_staff_lines(binary, img_width)
    print(f"OMR: Detected {len(staves)} staff/staves")
    
    # Detect note heads
    note_heads = detect_note_heads(binary, staves, img_width)
    print(f"OMR: Detected {len(note_heads)} note heads")
    
    if not note_heads:
        raise ValueError("No notes detected in the image. Make sure the image is a clear, "
                        "well-lit photo of sheet music with black notes on white background.")
    
    # Map each note head to the nearest staff and determine its pitch
    melody_notes = []
    
    for nx, ny, is_filled in note_heads:
        # Find the nearest staff
        best_staff = None
        best_dist = float('inf')
        
        for staff in staves:
            staff_center = (staff[0] + staff[4]) / 2
            dist = abs(ny - staff_center)
            if dist < best_dist:
                best_dist = dist
                best_staff = staff
        
        if best_staff is None:
            continue
        
        # Determine pitch from position on staff
        pitch_name = map_note_to_pitch(ny, best_staff, use_treble=True)
        
        # Duration: filled = quarter note, hollow = half note
        duration = 1.0 if is_filled else 2.0
        
        melody_notes.append((pitch_name, duration))
    
    print(f"OMR: Mapped {len(melody_notes)} notes: {[n[0] for n in melody_notes]}")
    
    # Build a music21 stream and export as MusicXML
    s = stream.Score()
    p = stream.Part()
    p.insert(0, clef.TrebleClef())
    p.insert(0, meter.TimeSignature('4/4'))
    p.insert(0, tempo.MetronomeMark(number=100))
    
    for pitch_name, duration in melody_notes:
        n = note.Note(pitch_name, quarterLength=duration)
        p.append(n)
    
    s.insert(0, p)
    
    # Save as MusicXML
    unique_id = str(uuid.uuid4())[:8]
    output_path = os.path.join(output_dir, f"omr_result_{unique_id}.musicxml")
    s.write('musicxml', fp=output_path)
    
    print(f"OMR: Saved MusicXML to {output_path}")
    return output_path
