import os
import uuid
import copy
import urllib.request
import logging
import traceback
import subprocess
import shutil
from music21 import converter, stream, note, chord, tempo, meter, key, pitch, instrument, clef, analysis, harmony, tie, duration

logging.basicConfig(level=logging.INFO)

def ensure_soundfont(sf_path="default.sf2"):
    """Downloads a soundfont if it doesn't exist."""
    if not os.path.exists(sf_path):
        logging.info("Downloading soundfont...")
        url = "https://github.com/npatfez/sf2/raw/master/SGM-v2.01-NiceLevelTwo.sf2"
        urllib.request.urlretrieve(url, sf_path)
    return sf_path

def export_midi_to_audio(midi_path, output_path, sf_path="default.sf2"):
    """Converts a MIDI file to an audio file using fluidsynth."""
    ensure_soundfont(sf_path)
    cmd = ["fluidsynth", "-ni", sf_path, midi_path, "-F", output_path, "-g", "1.0"]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as e:
        logging.error(f"Failed to render audio: {e}")

def get_key_of_score(score):
    """
    Holistic Key Detection Algorithm
    Evaluates all 24 keys based on melodic context, durations, cadences, and harmonic function.
    """
    notes_data = []
    # Use recurse() instead of flatten() to preserve the measure hierarchy.
    # This makes n.beat extremely fast O(1) and correctly handles pickup measures.
    flat_notes = score.recurse().notes
    if not flat_notes:
        return key.Key('C')
        
    for n in flat_notes:
        try:
            beat = float(n.beat)
        except:
            beat = float((n.offset % 4) + 1.0)
            
        if isinstance(n, note.Note):
            notes_data.append({
                'pc': n.pitch.pitchClass,
                'dur': n.duration.quarterLength,
                'beat': beat
            })
        elif isinstance(n, chord.Chord):
            for p in n.pitches:
                notes_data.append({
                    'pc': p.pitchClass,
                    'dur': n.duration.quarterLength,
                    'beat': beat
                })
                
    if not notes_data:
        return key.Key('C')
        
    first_pc = notes_data[0]['pc']
    last_pc = notes_data[-1]['pc']
    
    candidate_keys = []
    for i in range(12):
        p = pitch.Pitch(i)
        candidate_keys.append(key.Key(p.name, 'major'))
        candidate_keys.append(key.Key(p.name, 'minor'))
        
    scores = {}
    
    for k in candidate_keys:
        k_score = 0.0
        tonic_pc = k.tonic.pitchClass
        dom_pc = (tonic_pc + 7) % 12
        
        scale_pcs = set(p.pitchClass for p in k.getScale().getPitches('C2', 'B2'))
        
        for nd in notes_data:
            if nd['pc'] in scale_pcs:
                # 1. Diatonic Fit: Base points for belonging to the scale
                k_score += nd['dur'] * 3.0
                
                # 2. Strong Beat Bonus: Structural notes define the key
                # Give extra weight if tonic or dominant falls on a strong beat (1 or 3)
                if (nd['beat'] == 1.0 or nd['beat'] == 3.0) and nd['pc'] in [tonic_pc, dom_pc]:
                    k_score += nd['dur'] * 4.0
            else:
                # Penalty for non-diatonic notes
                k_score -= nd['dur'] * 2.0
                
        # 3. Final Cadence (The "Home" note)
        if last_pc == tonic_pc:
            k_score += 30.0
        elif last_pc == dom_pc:
            k_score += 5.0
        else:
            k_score -= 15.0
            
        # 4. Phrase Beginnings
        if first_pc == tonic_pc:
            k_score += 15.0
        elif first_pc == dom_pc:
            k_score += 5.0
            
        # 5. Harmonic Function: Leading Tone Check for Minor Keys
        if k.mode == 'minor':
            lt_pc = (tonic_pc + 11) % 12
            has_lt = any(nd['pc'] == lt_pc for nd in notes_data)
            
            if not has_lt:
                # Without a leading tone, it's highly unlikely to be the true minor key
                k_score -= 40.0
            else:
                k_score += 15.0
                
        scores[k] = k_score
        
    # Sort keys by confidence score
    sorted_keys = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # Log scores as requested for debugging
    print("\n=== Key Detection Confidence Scores ===")
    for k, s in sorted_keys[:5]:
        print(f"{k.name.replace('-', 'b'):2} {k.mode:5} : {s:.1f}")
    print("=======================================\n")
    
    return sorted_keys[0][0]

def get_scale_pitches(k):
    """Get the pitch classes belonging to this key's scale."""
    sc = k.getScale()
    return set(p.pitchClass for p in sc.getPitches('C2', 'C7'))

def generate_candidate_chords(melody_pitch, scale_key):
    """
    Given a melody note pitch class and a key, generate candidate triads
    built on scale degrees that contain this melody note.
    Returns list of (root_pc, chord_type, chord_pcs) tuples.
    """
    mode = scale_key.mode
    tonic_pc = scale_key.tonic.pitchClass
    
    if mode == 'minor':
        # Natural minor scale intervals
        intervals = [0, 2, 3, 5, 7, 8, 10]
    else:
        # Major scale intervals
        intervals = [0, 2, 4, 5, 7, 9, 11]
    
    scale_pcs = [(tonic_pc + i) % 12 for i in intervals]
    
    # For each scale degree, build a diatonic triad
    candidates = []
    for degree_idx in range(7):
        root_pc = scale_pcs[degree_idx]
        third_pc = scale_pcs[(degree_idx + 2) % 7]
        fifth_pc = scale_pcs[(degree_idx + 4) % 7]
        
        chord_pcs = {root_pc, third_pc, fifth_pc}
        is_chord_tone = (melody_pitch.pitchClass in chord_pcs)
        
        # Determine chord quality for cost purposes
        third_interval = (third_pc - root_pc) % 12
        fifth_interval = (fifth_pc - root_pc) % 12
        
        if third_interval == 4 and fifth_interval == 7:
            quality = 'major'
        elif third_interval == 3 and fifth_interval == 7:
            quality = 'minor'
        elif third_interval == 3 and fifth_interval == 6:
            quality = 'diminished'
        else:
            quality = 'other'
        
        candidates.append({
            'root_pc': root_pc,
            'quality': quality,
            'pcs': chord_pcs,
            'degree': degree_idx, # 0=I, 1=II, etc.
            'is_chord_tone': is_chord_tone
        })
    
    return candidates

def get_leading_tone_pc(scale_key):
    """Get the pitch class of the leading tone (7th scale degree) in a key."""
    tonic_pc = scale_key.tonic.pitchClass
    if scale_key.mode == 'minor':
        return (tonic_pc + 11) % 12  # Raised 7th in harmonic minor
    else:
        return (tonic_pc + 11) % 12  # 7th degree of major scale

def generate_voicings_for_chord(chord_info, fixed_parts, ranges, scale_key=None, harmony_style='close'):
    """
    Generate all valid SATB voicings where the provided fixed_parts are locked,
    and missing parts are drawn from the chord's pitch classes within their ranges.
    Enforces PartWriter rules for doubling and spacing.
    """
    pcs = chord_info['pcs']
    root_pc = chord_info['root_pc']
    
    # Identify leading tone for this key
    leading_tone_pc = get_leading_tone_pc(scale_key) if scale_key else None
    
    # Identify the 3rd of the chord
    third_interval = None
    for pc in pcs:
        ivl = (pc - root_pc) % 12
        if ivl in [3, 4]:  # minor 3rd or major 3rd
            third_interval = pc
            break
    
    # Generate candidates for all voices
    # If a voice is fixed, its only candidate is the fixed pitch
    s_cands = [fixed_parts['Soprano'].ps] if 'Soprano' in fixed_parts else [p for p in range(int(ranges['Soprano'][0]), int(ranges['Soprano'][1]) + 1) if p % 12 in pcs]
    a_cands = [fixed_parts['Alto'].ps] if 'Alto' in fixed_parts else [p for p in range(int(ranges['Alto'][0]), int(ranges['Alto'][1]) + 1) if p % 12 in pcs]
    t_cands = [fixed_parts['Tenor'].ps] if 'Tenor' in fixed_parts else [p for p in range(int(ranges['Tenor'][0]), int(ranges['Tenor'][1]) + 1) if p % 12 in pcs]
    b_cands = [fixed_parts['Bass'].ps] if 'Bass' in fixed_parts else [p for p in range(int(ranges['Bass'][0]), int(ranges['Bass'][1]) + 1) if p % 12 in pcs]
    
    # Tag bass candidates: root gets bonus (handled via penalty later)
    b_has_root = any(p % 12 == root_pc for p in b_cands)
    
    voicings = []
    
    for s in s_cands:
        for a in a_cands:
            if s < a: continue  # No voice crossing
            if s - a > 12: continue  # Spacing: S-A within octave
            
            for t in t_cands:
                if a < t: continue  # No voice crossing
                if a - t > 12: continue  # Spacing: A-T within octave
                
                for b in b_cands:
                    if t < b: continue  # No voice crossing
                    if t - b > 19: continue  # Spacing: T-B within P12
                    
                    voicing = (s, a, t, b)
                    voicing_pcs = set(p % 12 for p in voicing)
                    pc_list = [p % 12 for p in voicing]
                    
                    # Must cover all 3 pitch classes of the triad
                    if not pcs.issubset(voicing_pcs):
                        fifth_pc = None
                        for pc in pcs:
                            if pc != root_pc and (pc - root_pc) % 12 not in [3, 4]:
                                fifth_pc = pc
                        missing = pcs - voicing_pcs
                        if missing and missing != {fifth_pc}:
                            continue
                    
                    penalty = 0
                    doubled = [pc for pc in set(pc_list) if pc_list.count(pc) > 1]
                    
                    # === PARTWRITER RULE: Leading tone never doubled ===
                    if leading_tone_pc is not None:
                        lt_count = pc_list.count(leading_tone_pc)
                        if lt_count > 1:
                            penalty += 100  # Strictly forbidden
                    
                    # === PARTWRITER RULE: Root doubling preferred ===
                    for d in doubled:
                        if d == root_pc:
                            if harmony_style in ['traditional', 'strict']: penalty -= 2 # Reward root doubling
                        elif d == third_interval:
                            penalty += 20 if harmony_style in ['traditional', 'strict'] else 5  # Doubling 3rd is strictly forbidden in traditional
                        else:
                            penalty += 5 if harmony_style in ['traditional', 'strict'] else 3  # Doubling 5th is less bad
                    
                    # === PARTWRITER RULE: 2nd inversion — double the bass (5th) ===
                    if chord_info.get('quality') != 'diminished':
                        # Check if bass has the 5th of the chord
                        fifth_pc_check = None
                        for pc in pcs:
                            if (pc - root_pc) % 12 == 7:
                                fifth_pc_check = pc
                        if fifth_pc_check is not None and b % 12 == fifth_pc_check:
                            # This is 2nd inversion — reward doubling the 5th (bass note)
                            if pc_list.count(fifth_pc_check) >= 2:
                                penalty -= 3  # Good: double bass in 6/4
                    
                    # === Voice separation penalties ===
                    sa_gap = s - a
                    at_gap = a - t
                    tb_gap = t - b
                        
                    if sa_gap == 0: penalty += 8
                    if at_gap == 0: penalty += 8
                    if tb_gap == 0: penalty += 12
                    
                    if 0 < sa_gap <= 2: penalty += 3
                    if 0 < at_gap <= 2: penalty += 3
                    if 0 < tb_gap <= 2: penalty += 6
                    
                    # === TRADITIONAL STYLE: Heavy Major Triad Bias ===
                    if harmony_style in ['traditional', 'strict']:
                        q = chord_info.get('quality', 'other')
                        if q == 'minor':
                            penalty += 3  # Minor chords are natural in hymns (ii, iii, vi)
                        elif q == 'diminished':
                            penalty += 25
                        elif q == 'other':
                            penalty += 50
                    
                    # Harmony style spread preference
                    total_span = s - b
                    if harmony_style == 'close':
                        if 12 <= total_span <= 19:
                            penalty -= 3
                        elif total_span > 24:
                            penalty += 5
                        elif total_span < 7:
                            penalty += 5
                    else:  # wide/traditional/advanced
                        # 1. Bass: Keep bass in comfortable reading/singing register (G2 to G3 is sweet spot)
                        if b < 43:  # Below G2 (bottom line of bass staff)
                            penalty += 5
                        elif b > 55:  # Above G3
                            penalty += 2
                        
                        # 2. Alto: Prefer C4-A4 (60 to 69)
                        if a < 60:
                            penalty += 4  # Avoid dropping below C4
                        elif a > 69:
                            penalty += 2
                        
                        # 3. Tenor: Prefer E3-E4 (52 to 64)
                        if t < 52:
                            penalty += 5  # Strong penalty for dropping below E3 (too muddy)
                        elif t >= 60:
                            penalty -= 2  # Reward keeping Tenor above Middle C when possible
                            
                        # 4. Alto-Soprano Proximity
                        # Prefer Alto to remain within a 3rd to 6th below Soprano (3 to 9 semitones)
                        if 3 <= sa_gap <= 9:
                            penalty -= 3
                            
                        # 5. Avoid Tenor doubling the Bass
                        if t % 12 == b % 12:
                            penalty += 8  # Tenor should function as independent melodic voice
                            
                        if 18 <= total_span <= 30:
                            penalty -= 2
                        elif total_span < 12:
                            penalty += 5
                    
                    voicings.append((voicing, chord_info, penalty))
    
    voicings.sort(key=lambda x: x[2])
    return voicings[:80]

def check_parallels(prev_v, curr_v):
    """Check for parallel 5ths and octaves between two voicings."""
    errors = []
    names = ['Soprano', 'Alto', 'Tenor', 'Bass']
    for i in range(4):
        for j in range(i + 1, 4):
            prev_ivl = abs(prev_v[i] - prev_v[j])
            curr_ivl = abs(curr_v[i] - curr_v[j])
            
            if prev_v[i] != curr_v[i] or prev_v[j] != curr_v[j]:
                s_dir = curr_v[i] - prev_v[i]
                l_dir = curr_v[j] - prev_v[j]
                
                if (s_dir > 0 and l_dir > 0) or (s_dir < 0 and l_dir < 0):
                    if curr_ivl % 12 == 7 and prev_ivl % 12 == 7:
                        errors.append(f"Parallel 5th: {names[i]}-{names[j]}")
                    elif curr_ivl % 12 == 0 and prev_ivl % 12 == 0 and curr_ivl > 0:
                        errors.append(f"Parallel 8ve: {names[i]}-{names[j]}")
    return errors

def decorate_chorale(parts, scale_key):
    """
    Post-processes the generated SATB parts to add Bach Chorale fingerprints:
    1. Diatonic passing tones in the bass.
    2. Cadential suspensions (delaying the resolution).
    
    Uses append-based stream construction to prevent overlapping notes.
    """
    scale_pcs = get_scale_pitches(scale_key) if scale_key else set()
    
    # 1. Bass Passing Tones
    bass_part = parts['Bass']
    bass_notes = [el for el in bass_part if isinstance(el, note.Note)]
    bass_other = [el for el in bass_part if not isinstance(el, note.Note)]
    
    new_bass = stream.Part()
    for el in bass_other:
        new_bass.append(copy.deepcopy(el))
    
    for i, n1 in enumerate(bass_notes):
        if i < len(bass_notes) - 1:
            n2 = bass_notes[i + 1]
            interval = n2.pitch.ps - n1.pitch.ps
            
            # Only add passing tone if note is long enough and leap is a 3rd
            if n1.quarterLength >= 2.0 and abs(interval) in [3, 4]:
                half_dur = n1.quarterLength / 2.0
                
                # First half: original pitch
                first_note = copy.deepcopy(n1)
                first_note.quarterLength = half_dur
                new_bass.append(first_note)
                
                # Second half: diatonic passing tone
                step = 1 if interval > 0 else -1
                passing_ps = n1.pitch.ps  # fallback
                for j in range(1, 3):
                    test_ps = n1.pitch.ps + (j * step)
                    if (test_ps % 12) in scale_pcs:
                        passing_ps = test_ps
                        break
                
                passing_note = note.Note(passing_ps)
                passing_note.quarterLength = half_dur
                passing_note.volume.velocity = 60
                new_bass.append(passing_note)
            else:
                new_bass.append(copy.deepcopy(n1))
        else:
            new_bass.append(copy.deepcopy(n1))
    
    parts['Bass'] = new_bass

    # 2. Cadential Suspensions (Alto & Tenor)
    for p_name in ['Alto', 'Tenor']:
        part = parts[p_name]
        part_notes = [el for el in part if isinstance(el, note.Note)]
        part_other = [el for el in part if not isinstance(el, note.Note)]
        
        new_part = stream.Part()
        for el in part_other:
            new_part.append(copy.deepcopy(el))
        
        i = 0
        while i < len(part_notes):
            n1 = part_notes[i]
            
            if i < len(part_notes) - 1:
                n2 = part_notes[i + 1]
                interval = n1.pitch.ps - n2.pitch.ps
                
                # Downward step into a long note = potential cadence
                if n1.quarterLength >= 2.0 and n2.quarterLength >= 1.0 and interval in [1, 2]:
                    # Append n1 as-is
                    new_part.append(copy.deepcopy(n1))
                    
                    # Split n2: first half is suspension (holds n1's pitch), second half resolves
                    half_dur = n2.quarterLength / 2.0
                    
                    suspension = note.Note(n1.pitch.ps)
                    suspension.quarterLength = half_dur
                    suspension.volume.velocity = n2.volume.velocity if hasattr(n2.volume, 'velocity') and n2.volume.velocity else 70
                    new_part.append(suspension)
                    
                    resolution = copy.deepcopy(n2)
                    resolution.quarterLength = half_dur
                    new_part.append(resolution)
                    
                    i += 2  # Skip n2 since we already handled it
                    continue
            
            new_part.append(copy.deepcopy(n1))
            i += 1
        
        parts[p_name] = new_part

def transition_cost(prev_voicing, prev_chord, curr_voicing, curr_chord, next_melody_pitch=None, scale_key=None, harmony_style='close'):
    """
    Calculate the voice-leading cost between two voicings.
    Enforces all PartWriter rules for transitions.
    """
    cost = 0.0
    errors = []
    names = ['Soprano', 'Alto', 'Tenor', 'Bass']
    
    # 1. Stepwise motion preference — graduated penalties for ALL voices
    for i in range(4):  # Soprano, Alto, Tenor, Bass
        leap = abs(curr_voicing[i] - prev_voicing[i])
        
        if i in [1, 2]:  # Alto & Tenor: strictest stepwise constraint
            if leap <= 2:
                cost -= 1  # Reward stepwise motion
            elif leap <= 4:
                cost += 3  # Minor 3rd / Major 3rd: mild penalty
            elif leap <= 5:
                cost += 40  # Perfect 4th: strong penalty
            elif leap <= 7:
                cost += 200  # 5th range: very heavy
            else:
                cost += 10000  # Anything larger: effectively forbidden
        elif i == 3:  # Bass: more freedom, but not unlimited
            if leap <= 2:
                cost -= 1  # Reward stepwise bass
            elif leap in [5, 7]:  # P4 or P5 leap in bass
                cost -= 3  # Reward strong root motion leaps
            elif leap <= 7:
                cost += 2  # Other leaps up to a 5th: small penalty
            elif leap <= 12:
                cost += 8  # Up to an octave: moderate
            else:
                cost += 80  # Larger than octave: heavy penalty
        else:  # Soprano (i == 0)
            if leap <= 2:
                cost -= 1
            elif leap <= 4:
                cost += 1
            elif leap <= 7:
                cost += 4
            else:
                cost += 15
    
    # 1b. Voice crossing detection in transitions
    # Voices must not cross between consecutive beats
    if curr_voicing[0] < curr_voicing[1]:  # Soprano below Alto
        cost += 10000
    if curr_voicing[1] < curr_voicing[2]:  # Alto below Tenor
        cost += 10000
    if curr_voicing[2] < curr_voicing[3]:  # Tenor below Bass
        cost += 10000

    # 2. Parallel 5ths/8ves (STRICTLY FORBIDDEN — all styles)
    parallels = check_parallels(prev_voicing, curr_voicing)
    if parallels:
        cost += 1000000
        errors.extend(parallels)
    
    # 2b. Consecutive unisons (two voices on same note two beats in a row)
    for i in range(4):
        for j in range(i + 1, 4):
            if curr_voicing[i] == curr_voicing[j] and prev_voicing[i] == prev_voicing[j]:
                cost += 500
                errors.append(f"Consecutive unison: {names[i]}-{names[j]}")
    
    # 3. === PARTWRITER RULE: Direct/Hidden 5ths & 8ves ===
    # When soprano and bass move in the same direction to a P5 or P8,
    # the soprano must move by step.
    s_dir = curr_voicing[0] - prev_voicing[0]
    b_dir = curr_voicing[3] - prev_voicing[3]
    if s_dir != 0 and b_dir != 0:
        same_direction = (s_dir > 0 and b_dir > 0) or (s_dir < 0 and b_dir < 0)
        if same_direction:
            outer_interval = abs(curr_voicing[0] - curr_voicing[3]) % 12
            soprano_step = abs(curr_voicing[0] - prev_voicing[0])
            if outer_interval in [0, 7]:  # P8 or P5
                if soprano_step > 2:  # Soprano didn't move by step
                    cost += 200
                    errors.append(f"Direct {'5th' if outer_interval == 7 else '8ve'}: Soprano-Bass")
    
    # 4. === PARTWRITER RULE: Leading tone resolves UP to tonic ===
    if scale_key:
        lt_pc = get_leading_tone_pc(scale_key)
        tonic_pc = scale_key.tonic.pitchClass
        for i in range(4):
            if prev_voicing[i] % 12 == lt_pc:
                # This voice had the leading tone — it should resolve up by half step
                expected = prev_voicing[i] + 1  # Up by semitone to tonic
                if curr_voicing[i] % 12 == tonic_pc:
                    cost -= 3  # Reward proper resolution
                elif curr_voicing[i] != prev_voicing[i]:  # It moved but not to tonic
                    cost += 30
                    errors.append(f"{names[i]}: Leading tone did not resolve up")
    
    # 5. === PARTWRITER RULE: Common tone retention ===
    # If two chords share a pitch class, at least one voice should keep it
    prev_pcs = set(v % 12 for v in prev_voicing)
    curr_pcs = set(v % 12 for v in curr_voicing)
    common_pcs = prev_pcs & curr_pcs
    if common_pcs:
        retained = False
        for i in range(4):
            if prev_voicing[i] == curr_voicing[i] and prev_voicing[i] % 12 in common_pcs:
                retained = True
                break
        if retained:
            cost -= 2  # Reward common tone retention
        else:
            cost += 3  # Penalty for not retaining common tones
    
    # 6. === PARTWRITER RULE: Avoid augmented 2nds ===
    for i in range(4):
        interval = abs(curr_voicing[i] - prev_voicing[i])
        if interval == 3:  # Augmented 2nd = 3 semitones
            # Check if it's actually an augmented 2nd (not minor 3rd)
            # In minor keys, moving between b6 and #7 creates augmented 2nd
            cost += 8
            
    # 6.5 === CONTRARY MOTION PREFERENCES ===
    dirs = []
    for i in range(4):
        if curr_voicing[i] > prev_voicing[i]: dirs.append(1)
        elif curr_voicing[i] < prev_voicing[i]: dirs.append(-1)
        else: dirs.append(0)
        
    # Penalize block-chord writing (all 4 voices moving in the exact same direction)
    if all(d == 1 for d in dirs) or all(d == -1 for d in dirs):
        cost += 15
        
    # Reward contrary motion between outer voices (Soprano and Bass)
    if dirs[0] != 0 and dirs[3] != 0 and dirs[0] != dirs[3]:
        cost -= 4
    
    # 7. Root motion preferences (favor functional progressions in traditional style)
    root_motion = abs(curr_chord['root_pc'] - prev_chord['root_pc'])
    root_motion = min(root_motion, 12 - root_motion)
    
    if harmony_style in ['traditional', 'strict']:
        prev_deg = prev_chord.get('degree', 0)
        # Strong functional progressions (I-V, IV-I, etc.)
        if root_motion == 5 or root_motion == 7:
            cost -= 5  # Strong progression
        elif root_motion == 2 or root_motion == 10:
            cost -= 2  # Stepwise (often good)
        elif root_motion == 0:
            cost -= 3  # Reward staying on the same chord to encourage stable harmonic rhythm across sub-beats
    else:
        if root_motion == 5 or root_motion == 7:
            cost -= 2  # Strong progression (motion by 4th/5th)
        elif root_motion == 0:
            cost -= 1  # Small reward for staying on the same chord
            
    # 8. Non-Chord Tone Penalty (Contextual Passing Tone Handling)
    is_chord_tone = curr_chord.get('is_chord_tone', True)
    if not is_chord_tone:
        curr_mel_ps = curr_voicing[0]
        prev_mel_ps = prev_voicing[0]
        
        # Check if approached by step
        approached_by_step = abs(curr_mel_ps - prev_mel_ps) <= 2 and curr_mel_ps != prev_mel_ps
        
        # Check if resolved by step in same direction (if next note exists)
        resolved_by_step = False
        if next_melody_pitch:
            next_mel_ps = next_melody_pitch.ps
            resolved_by_step = abs(next_mel_ps - curr_mel_ps) <= 2 and next_mel_ps != curr_mel_ps
            
            # For a true passing tone, it should continue in the same direction
            if approached_by_step and resolved_by_step:
                dir1 = curr_mel_ps - prev_mel_ps
                dir2 = next_mel_ps - curr_mel_ps
                if (dir1 > 0 and dir2 < 0) or (dir1 < 0 and dir2 > 0):
                    # It's a neighbor tone (returns to previous pitch), which is also valid!
                    pass
        
        # If it's approached by step, we give it a very small penalty so it's allowed
        # If it's approached by step AND resolved by step, it's a true passing/neighbor tone
        if approached_by_step:
            if root_motion == 0:
                cost += 5  # Small penalty, but offset by the -3 reward for root_motion == 0
            else:
                cost += 50 # Changing chords ON a passing tone is heavily penalized
        else:
            # Leapt to a non-chord tone (appoggiatura / escape tone). Needs a heavy penalty
            # so the AI prefers to just change the chord to match it.
            cost += 100
    
    # 8. Contrary motion bonus (soprano vs bass)
    if (s_dir > 0 and b_dir < 0) or (s_dir < 0 and b_dir > 0):
        cost -= 1  # Reward contrary motion
    
    return cost, errors

def process_midi(input_path, ranges_str, output_dir, harmony_style='close', tempo_bpm=None, instrument_type='choir', chord_overrides='', keep_parts_list=None, key_override=''):
    """
    Takes a MIDI file and generates full SATB harmony.
    If keep_parts_list is provided, it maps the highest to lowest pitches in the file
    to those specific voice parts and generates the remaining parts around them.
    If empty, the highest note is forced to be Soprano.
    """
    print(f"Harmonizing melody: {input_path}")
    score = converter.parse(input_path)
    
    # Key detection: use manual override if provided, otherwise auto-detect
    if key_override and key_override.strip():
        try:
            detected_key = key.Key(key_override.strip())
            print(f"Using manual key override: {detected_key}")
        except Exception:
            print(f"Invalid key override '{key_override}', falling back to auto-detection")
            detected_key = get_key_of_score(score)
            print(f"Auto-detected key: {detected_key}")
    else:
        detected_key = get_key_of_score(score)
        print(f"Auto-detected key: {detected_key}")
    
    # Convert ranges
    ranges = {
        'Soprano': (pitch.Pitch(ranges_str['soprano_min']).ps, pitch.Pitch(ranges_str['soprano_max']).ps),
        'Alto': (pitch.Pitch(ranges_str['alto_min']).ps, pitch.Pitch(ranges_str['alto_max']).ps),
        'Tenor': (pitch.Pitch(ranges_str['tenor_min']).ps, pitch.Pitch(ranges_str['tenor_max']).ps),
        'Bass': (pitch.Pitch(ranges_str['bass_min']).ps, pitch.Pitch(ranges_str['bass_max']).ps),
    }
    
    if keep_parts_list is None:
        keep_parts_list = []
        
    melody_events = []
    for element in score.chordify().flatten().notesAndRests:
        dur_left = element.duration.quarterLength
        
        # In Strict Block Chords style, we do NOT slice the notes into quarter-note harmonic rhythms
        if harmony_style == 'strict':
            chunk_list = [dur_left]
        else:
            chunk_list = []
            while dur_left > 0:
                chunk_dur = 1.0 if dur_left > 1.0 else dur_left
                chunk_list.append(chunk_dur)
                dur_left -= chunk_dur
                
        for chunk_dur in chunk_list:
            chunk_duration_obj = duration.Duration(chunk_dur)
            
            if element.isRest:
                melody_events.append(('rest', chunk_duration_obj, {}))
            elif element.isNote:
                if keep_parts_list:
                    melody_events.append(('note', chunk_duration_obj, {keep_parts_list[0]: element.pitch}))
                else:
                    melody_events.append(('note', chunk_duration_obj, {'Soprano': element.pitch}))
            elif element.isChord:
                pitches = sorted(element.pitches, key=lambda p: p.ps, reverse=True)
                fixed_parts = {}
                if keep_parts_list:
                    for idx, part_name in enumerate(keep_parts_list):
                        if idx < len(pitches):
                            fixed_parts[part_name] = pitches[idx]
                else:
                    fixed_parts['Soprano'] = pitches[0]
                melody_events.append(('note', chunk_duration_obj, fixed_parts))
    
    if not melody_events:
        raise Exception("No notes found in the MIDI file.")
        
    print(f"Found {len(melody_events)} melody events")
    
    # ===== VITERBI ALGORITHM =====
    # State = (voicing_tuple, chord_info_dict)
    # dp[i] = { state_key: (cost, prev_state_key, errors) }
    
    dp = []
    state_data = []  # Parallel list: state_data[i][state_key] = (voicing, chord_info)
    
    for i, (etype, dur, fixed_parts) in enumerate(melody_events):
        if etype == 'rest':
            state_key = 'rest'
            if i == 0 or not dp:
                dp.append({state_key: (0, None, [])})
            else:
                # Carry forward best previous state so backtrack works
                prev_best_key = min(dp[i-1].keys(), key=lambda k: dp[i-1][k][0])
                prev_cost = dp[i-1][prev_best_key][0]
                prev_errors = dp[i-1][prev_best_key][2]
                dp.append({state_key: (prev_cost, prev_best_key, prev_errors)})
            state_data.append({state_key: (None, None)})
            continue
        
        # Parse chord overrides if provided
        forced_chords = []
        if chord_overrides:
            import re
            overrides = [c.strip() for c in chord_overrides.split(',')]
            for o in overrides:
                if not o: continue
                try:
                    ch = harmony.ChordSymbol(o)
                    forced_chords.append(ch)
                except Exception as e:
                    print(f"Failed to parse chord override '{o}': {e}")

        # Get a representative pitch to use for chord generation (topmost pitch)
        top_pitch = list(fixed_parts.values())[0] if fixed_parts else note.Note("C4").pitch
        
        # Generate candidate chords for this note
        if forced_chords:
            idx = int( (i / len(melody_events)) * len(forced_chords) )
            fc = forced_chords[idx]
            root_pc = fc.root().pitchClass
            quality = 'major' if 'major' in fc.quality else 'minor' if 'minor' in fc.quality else 'diminished' if 'diminished' in fc.quality else 'other'
            pcs = set(p.pitchClass for p in fc.pitches)
            candidate_chords = [{'root_pc': root_pc, 'quality': quality, 'pcs': pcs, 'degree': 0}]
        else:
            candidate_chords = generate_candidate_chords(top_pitch, detected_key)
        
        # Generate all valid voicings across all candidate chords
        all_voicings = []
        for ch in candidate_chords:
            voicings = generate_voicings_for_chord(ch, fixed_parts, ranges, detected_key, harmony_style)
            all_voicings.extend(voicings)
        
        if not all_voicings:
            # Emergency fallback — still enforce spacing rules
            s = int(fixed_parts['Soprano'].ps) if 'Soprano' in fixed_parts else int(top_pitch.ps)
            
            if 'Alto' in fixed_parts:
                a = int(fixed_parts['Alto'].ps)
            else:
                a = max(s - 7, int(ranges['Alto'][0]))
                a = min(a, int(ranges['Alto'][1]))
                if s - a > 12: a = s - 12
            
            if 'Tenor' in fixed_parts:
                t = int(fixed_parts['Tenor'].ps)
            else:
                t = max(a - 7, int(ranges['Tenor'][0]))
                t = min(t, int(ranges['Tenor'][1]))
                if a - t > 12: t = a - 12
            
            if 'Bass' in fixed_parts:
                b = int(fixed_parts['Bass'].ps)
            else:
                b = max(t - 12, int(ranges['Bass'][0]))
                b = min(b, int(ranges['Bass'][1]))
                if t - b > 19: b = t - 19
            
            fallback_chord = {'root_pc': top_pitch.pitchClass, 'quality': 'major', 'pcs': {top_pitch.pitchClass}, 'degree': 0}
            all_voicings = [((s, a, t, b), fallback_chord, 50)]
        
        current_states = {}
        current_data = {}
        
        for voicing, chord_info, doubling_penalty in all_voicings:
            state_key = voicing  # Use the voicing tuple as the state key
            
            if i == 0:
                # First note: no transition cost
                cost = doubling_penalty
                current_states[state_key] = (cost, None, [])
                current_data[state_key] = (voicing, chord_info)
            else:
                best_cost = float('inf')
                best_prev = None
                best_errors = []
                
                # Determine next melody pitch for contextual passing tone analysis
                next_melody_pitch = None
                if i + 1 < len(melody_events):
                    next_etype, _, next_fixed = melody_events[i + 1]
                    if next_etype == 'note' and next_fixed:
                        next_melody_pitch = list(next_fixed.values())[0]

                for prev_key, (prev_cost, _, prev_errors) in dp[i - 1].items():
                    if prev_key == 'rest':
                        tc = doubling_penalty
                        new_errors = []
                    else:
                        prev_voicing, prev_chord = state_data[i - 1][prev_key]
                        tc, new_errors = transition_cost(prev_voicing, prev_chord, voicing, chord_info, next_melody_pitch, detected_key, harmony_style)
                        tc += doubling_penalty
                    
                    total = prev_cost + tc
                    if total < best_cost:
                        best_cost = total
                        best_prev = prev_key
                        best_errors = prev_errors + new_errors
                
                if state_key not in current_states or best_cost < current_states[state_key][0]:
                    current_states[state_key] = (best_cost, best_prev, best_errors)
                    current_data[state_key] = (voicing, chord_info)
        
        dp.append(current_states)
        state_data.append(current_data)
    
    # ===== BACKTRACK =====
    # Find best final state
    final_states = dp[-1]
    best_final = min(final_states.keys(), key=lambda k: final_states[k][0])
    
    # Build path from end to start
    path_keys = [None] * len(melody_events)
    path_keys[-1] = best_final
    for i in range(len(melody_events) - 1, 0, -1):
        key_at_i = path_keys[i]
        if key_at_i is not None and key_at_i in dp[i]:
            path_keys[i - 1] = dp[i][key_at_i][1]
        # else path_keys[i-1] stays None
    
    # Collect errors
    all_errors = list(set(dp[-1][best_final][2]))
    
    # ===== BUILD OUTPUT PARTS =====
    parts = {
        'Soprano': stream.Part(),
        'Alto': stream.Part(),
        'Tenor': stream.Part(),
        'Bass': stream.Part()
    }
    
    for p_name in parts:
        parts[p_name].id = p_name
        parts[p_name].partName = p_name
    
    # Set instrument based on user choice
    for p_name in parts:
        inst = instrument.Instrument()
        if instrument_type == 'piano':
            inst.midiProgram = 0  # Acoustic Grand Piano
        else:
            inst.midiProgram = 52 # Choir Aahs
        inst.partName = p_name
        inst.partAbbreviation = p_name[0]
        parts[p_name].insert(0, inst)

    parts['Soprano'].insert(0, clef.TrebleClef())
    parts['Alto'].insert(0, clef.TrebleClef())
    parts['Tenor'].insert(0, clef.Treble8vbClef())
    parts['Bass'].insert(0, clef.BassClef())
    
    # Apply tempo
    if tempo_bpm:
        for p in parts.values():
            p.insert(0, tempo.MetronomeMark(number=tempo_bpm))
    
    # Copy time/key/tempo from original
    import copy
    for el in score.recurse():
        if isinstance(el, meter.TimeSignature):
            for p in parts.values():
                p.insert(0, copy.deepcopy(el))
            break  # Only need first time signature
    for el in score.recurse():
        if isinstance(el, key.KeySignature):
            for p in parts.values():
                p.insert(0, copy.deepcopy(el))
            break
    if not tempo_bpm:
        for el in score.recurse():
            if isinstance(el, tempo.MetronomeMark):
                for p in parts.values():
                    p.insert(0, copy.deepcopy(el))
                break
    
    for idx, (etype, dur, fixed_parts) in enumerate(melody_events):
        sk = path_keys[idx]
        
        if sk is None or sk == 'rest' or etype == 'rest':
            for p in parts.values():
                p.append(note.Rest(duration=dur))
        else:
            voicing = sk  # The state key IS the voicing tuple (S, A, T, B)
            for part_name, note_pitch in zip(['Soprano', 'Alto', 'Tenor', 'Bass'], voicing):
                n = note.Note(note_pitch, duration=dur)
                n.volume.velocity = 70  # Lower velocity to prevent WebAudio compressor clipping
                parts[part_name].append(n)
                

        
    # ===== RHYTHM RESTORATION (LEGATO PASS) =====
    # Merge consecutive identical notes and rests to prevent robotic re-articulations
    # caused by quarter-note slicing. This preserves the Soprano's original rhythm
    # while allowing inner voices to move independently every beat.
    if harmony_style != 'strict':
        for p_name in parts:
            old_part = parts[p_name]
            new_part = stream.Part()
            
            # Copy non-note elements (clefs, tempo, key, etc)
            for element in old_part:
                if not isinstance(element, (note.Note, note.Rest)):
                    new_part.append(copy.deepcopy(element))
                
            current_el = None
            for element in old_part:
                if isinstance(element, (note.Note, note.Rest)):
                    if current_el is None:
                        current_el = copy.deepcopy(element)
                    else:
                        if type(current_el) == type(element):
                            if isinstance(element, note.Note) and current_el.pitch.ps == element.pitch.ps:
                                # Cap merged duration at 4.0 beats (whole note) to prevent
                                # the web synthesizer from running out of sample and going silent
                                if current_el.duration.quarterLength + element.duration.quarterLength <= 4.0:
                                    current_el.duration.quarterLength += element.duration.quarterLength
                                else:
                                    new_part.append(current_el)
                                    current_el = copy.deepcopy(element)
                            elif isinstance(element, note.Rest):
                                current_el.duration.quarterLength += element.duration.quarterLength
                            else:
                                new_part.append(current_el)
                                current_el = copy.deepcopy(element)
                        else:
                            new_part.append(current_el)
                            current_el = copy.deepcopy(element)
            if current_el is not None:
                new_part.append(current_el)
                
            parts[p_name] = new_part
    
    # ===== SAVE FILES =====
    unique_id = str(uuid.uuid4())[:8]
    output_files = {}
    
    for name, p in parts.items():
        filename = f"{name.lower()}_{unique_id}.mid"
        filepath = os.path.join(output_dir, filename)
        p.write('midi', fp=filepath)
        output_files[name] = filename
    
    satb_score = stream.Score()
    for p_name in ['Soprano', 'Alto', 'Tenor', 'Bass']:
        satb_score.insert(0, parts[p_name])
    
    combined_filename = f"satb_full_{unique_id}.mid"
    combined_filepath = os.path.join(output_dir, combined_filename)
    satb_score.write('midi', fp=combined_filepath)
    output_files['combined'] = combined_filename
    
    # Generate Part-Predominant Practice Tracks
    import copy
    for target_part_name in ['Soprano', 'Alto', 'Tenor', 'Bass']:
        practice_score = stream.Score()
        for p_name in ['Soprano', 'Alto', 'Tenor', 'Bass']:
            part_copy = copy.deepcopy(parts[p_name])
            is_target = (p_name == target_part_name)
            
            # Adjust velocity of all notes
            for n in part_copy.recurse().notes:
                # music21 defaults to velocity 90 if not set. 
                n.volume.velocity = 90 if is_target else 45
            
            practice_score.insert(0, part_copy)
            
        p_filename = f"practice_{target_part_name.lower()}_{unique_id}.mid"
        p_filepath = os.path.join(output_dir, p_filename)
        practice_score.write('midi', fp=p_filepath)
        output_files[f"practice_{target_part_name.lower()}"] = p_filename
    
    # ===== AUDIO RENDERING (MP3/WAV) =====
    # We attempt to use fluidsynth to render the MIDI files into actual audio files.
    # This provides perfect playback on the frontend without relying on buggy JS MIDI players.
    has_fluidsynth = True # Force it to true so we get the exact stack trace if it fails
    audio_engine_error = None
    
    if has_fluidsynth:
        try:
            from midi2audio import FluidSynth
            from pydub import AudioSegment
            
            # 1. Use system soundfont if in Docker, otherwise fallback to local download
            sf2_path = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
            if not os.path.exists(sf2_path):
                sf2_path = os.path.join(output_dir, "soundfont.sf2")
                if not os.path.exists(sf2_path):
                    print("Downloading soundfont for backend audio rendering...")
                    sf2_url = "https://raw.githubusercontent.com/fluid-project/fluid-soundfont/master/FluidR3_GM.sf2" # Best effort fallback
                    try:
                        urllib.request.urlretrieve(sf2_url, sf2_path)
                    except Exception as e:
                        print(f"Warning: Failed to download soundfont: {e}")
                        raise Exception("Soundfont download failed. Audio rendering aborted.")
            
            # Initialize FluidSynth with the soundfont and a lower sample rate to double rendering speed
            fs = FluidSynth(sf2_path, sample_rate=22050)
            
            # Convert all MIDI files to MP3 in PARALLEL using all available CPU cores
            audio_files = {}
            import concurrent.futures
            
            def render_one_track(args):
                key_name, mid_filename = args
                if not mid_filename.endswith('.mid'):
                    return key_name, None
                mid_filepath = os.path.join(output_dir, mid_filename)
                wav_filename = mid_filename.replace('.mid', '.wav')
                wav_filepath = os.path.join(output_dir, wav_filename)
                mp3_filename = mid_filename.replace('.mid', '.mp3')
                mp3_filepath = os.path.join(output_dir, mp3_filename)
                
                # Each worker gets its own FluidSynth instance
                track_fs = FluidSynth(sf2_path, sample_rate=22050)
                track_fs.midi_to_audio(mid_filepath, wav_filepath)
                
                try:
                    audio = AudioSegment.from_wav(wav_filepath)
                    audio = audio + 15
                    audio.export(mp3_filepath, format="mp3", bitrate="64k")
                    os.remove(wav_filepath)
                    return key_name + "_audio", mp3_filename
                except Exception as mp3_e:
                    print(f"MP3 conversion failed: {mp3_e}")
                    return key_name + "_audio", wav_filename
            
            midi_items = [(k, v) for k, v in output_files.items() if v.endswith('.mid')]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                results_list = list(executor.map(render_one_track, midi_items))
            
            for result_key, result_val in results_list:
                if result_val:
                    audio_files[result_key] = result_val
            
            # Merge audio files into output_files
            output_files.update(audio_files)
            
        except Exception as e:
            audio_engine_error = str(e)
            print(f"Audio rendering failed: {e}")
    else:
        print("Fluidsynth not found on system. Skipping backend audio rendering.")
    
    # MusicXML export
    musicxml_filename = f"satb_score_{unique_id}.musicxml"
    musicxml_filepath = os.path.join(output_dir, musicxml_filename)
    try:
        satb_score.write('musicxml', fp=musicxml_filepath)
        output_files['musicxml'] = musicxml_filename
    except Exception as e:
        print(f"MusicXML export failed: {e}")
        
    # PDF export (requires MuseScore or Lilypond installed)
    pdf_filename = f"satb_score_{unique_id}.pdf"
    pdf_filepath = os.path.join(output_dir, pdf_filename)
    try:
        satb_score.write('musicxml.pdf', fp=pdf_filepath)
        output_files['pdf'] = pdf_filename
    except Exception as e:
        print(f"PDF export failed: {e}")
    
    print(f"Generated {len(output_files)} files with {len(all_errors)} voice-leading warnings.")
    
    return {
        "files": output_files,
        "errors": all_errors,
        "key": str(detected_key),
        "tempo": tempo_bpm,
        "audio_error": audio_engine_error if audio_engine_error else ("None" if has_fluidsynth else "Missing fluidsynth or soundfont")
    }
