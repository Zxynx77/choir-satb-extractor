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
    try:
        detected_key = score.analyze('key')
        
        # Heuristic: If music21 detected a minor key, check the final note of the melody.
        # If the final note matches the tonic of the relative major, it's almost certainly the relative major.
        if detected_key.mode == 'minor':
            last_note = None
            for n in score.flatten().notes:
                if n.isNote:
                    last_note = n
                elif n.isChord:
                    last_note = n.notes[0] # Just grab the top note if it's a chord
            
            if last_note and last_note.pitch.step == detected_key.relative.tonic.step:
                print(f"Heuristic override: changing {detected_key} to {detected_key.relative} based on final note {last_note.pitch.name}")
                return detected_key.relative
                
        return detected_key
    except Exception as e:
        print(f"Key analysis failed: {e}. Defaulting to C major.")
        return key.Key('C')

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
                        
                    if sa_gap == 0: penalty += 25  # Strongly forbid Soprano-Alto unison
                    if at_gap == 0: penalty += 30  # Strictly forbid Alto-Tenor unison
                    if tb_gap == 0: penalty += 20  # Forbid Tenor-Bass unison
                    
                    if 0 < sa_gap <= 2: penalty += 5
                    if 0 < at_gap <= 2: penalty += 10  # Alto-Tenor within a 2nd = too close
                    if 0 < tb_gap <= 2: penalty += 8
                    
                    # Reward proper Alto-Tenor separation (a 3rd to a 6th apart)
                    if 3 <= at_gap <= 9:
                        penalty -= 4
                    
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
                    
                    # === UNIVERSAL: Bass must stay in bass clef (ALL styles) ===
                    if b < 43:  # Below G2 (too many ledger lines)
                        penalty += 10
                    elif 43 <= b <= 55:  # Sweet spot G2-G3
                        penalty -= 3
                    elif b <= 57:  # A3 — top of bass staff, acceptable
                        penalty += 5
                    elif b <= 60:  # Up to C4 — entering treble territory
                        penalty += 50
                    else:  # Above C4 — bass in treble clef is WRONG
                        penalty += 200
                    
                    # === UNIVERSAL: Alto tessitura (ALL styles) ===
                    # Alto sweet spot: C4-A4 (MIDI 60-69)
                    if a < 60:  # Below C4
                        penalty += 10
                    elif 60 <= a <= 69:  # Sweet spot C4-A4
                        penalty -= 3
                    elif a > 69:
                        penalty += 2
                    
                    # === UNIVERSAL: Tenor tessitura (ALL styles) ===
                    # Tenor sweet spot: E3-B3 (MIDI 52-59) — NO overlap with Alto
                    if t < 52:  # Below E3 (too muddy)
                        penalty += 10
                    elif 52 <= t <= 59:  # Sweet spot E3-B3
                        penalty -= 2
                    elif t <= 64:  # C4-E4: acceptable but not preferred (Alto territory)
                        penalty += 0  # Neutral — no reward, no penalty
                    else:  # Above E4: too high for Tenor
                        penalty += 5
                    
                    # === UNIVERSAL: Alto-Soprano Proximity ===
                    if 3 <= sa_gap <= 9:
                        penalty -= 3
                    elif sa_gap > 14:
                        penalty += 5  # Alto is too far from Soprano
                    
                    # === UNIVERSAL: Avoid Tenor doubling the Bass ===
                    if t % 12 == b % 12 and t != b:
                        penalty += 8  # Tenor should be independent
                    
                    # Harmony style spread preference
                    if harmony_style == 'close':
                        if 12 <= total_span <= 19:
                            penalty -= 3
                        elif total_span > 24:
                            penalty += 5
                        elif total_span < 7:
                            penalty += 5
                    else:  # wide/traditional/advanced
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
        
        if i in [1, 2]:  # Alto & Tenor: allow leaps to reach correct tessitura
            if leap <= 2:
                cost -= 1  # Reward stepwise motion
            elif leap <= 4:
                cost += 2  # Minor 3rd / Major 3rd: very mild
            elif leap <= 5:
                cost += 6  # Perfect 4th: acceptable leap for register correction
            elif leap <= 7:
                cost += 12  # 5th: moderate penalty, but allowed when needed
            elif leap <= 12:
                cost += 40  # Up to an octave: heavy but not forbidden
            else:
                cost += 200  # Larger than octave: effectively forbidden
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
    # Only evaluate the 3 generated voices (Alto=1, Tenor=2, Bass=3)
    # Soprano (0) is fixed/locked, so don't penalize based on its direction
    gen_dirs = []
    for i in [1, 2, 3]:  # Alto, Tenor, Bass only
        if curr_voicing[i] > prev_voicing[i]: gen_dirs.append(1)
        elif curr_voicing[i] < prev_voicing[i]: gen_dirs.append(-1)
        else: gen_dirs.append(0)
        
    # Penalize block-chord writing (all 3 generated voices moving same direction)
    if all(d == 1 for d in gen_dirs if d != 0) and sum(1 for d in gen_dirs if d != 0) >= 3:
        cost += 8
        
    # Reward contrary motion between Soprano (fixed) and Bass (generated)
    s_motion = curr_voicing[0] - prev_voicing[0]
    b_motion = curr_voicing[3] - prev_voicing[3]
    if s_motion != 0 and b_motion != 0:
        if (s_motion > 0 and b_motion < 0) or (s_motion < 0 and b_motion > 0):
            cost -= 3  # Reward contrary motion
    
    # 6.6 === ALTO-TENOR INDEPENDENCE ===
    # This is the key rule that prevents Alto and Tenor from being "the same melody shifted down"
    a_motion = curr_voicing[1] - prev_voicing[1]  # Alto movement
    t_motion = curr_voicing[2] - prev_voicing[2]  # Tenor movement
    
    if a_motion != 0 and t_motion != 0:
        # Both voices are moving
        same_dir = (a_motion > 0 and t_motion > 0) or (a_motion < 0 and t_motion < 0)
        
        if same_dir:
            # Moving same direction by same interval = strict parallel (sounds identical)
            if abs(a_motion) == abs(t_motion):
                cost += 20  # Heavy penalty for strict parallel motion
            # Moving same direction by similar interval = similar motion (still too similar)
            elif abs(abs(a_motion) - abs(t_motion)) <= 1:
                cost += 10  # Moderate penalty
            else:
                cost += 3   # Mild penalty for same direction but different intervals
        else:
            # Contrary motion between Alto and Tenor = independent voices!
            cost -= 5  # Strong reward
    elif (a_motion != 0) != (t_motion != 0):
        # One moves while the other stays = oblique motion (good independence)
        cost -= 3
    
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
    # Apply the key signature from the key we actually used to harmonize!
    # This prevents massive accidental collisions if the MIDI file had a wrong embedded key signature
    for p in parts.values():
        p.insert(0, key.KeySignature(detected_key.sharps))
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
    
    # Force clefs before export (music21's makeNotation can override them)
    for p in satb_score.parts:
        if p.partName == 'Bass' or p.id == 'Bass':
            # Remove any auto-inserted clefs and force BassClef
            for existing_clef in p.recurse().getElementsByClass('Clef'):
                p.remove(existing_clef)
            p.insert(0, clef.BassClef())
        elif p.partName == 'Tenor' or p.id == 'Tenor':
            for existing_clef in p.recurse().getElementsByClass('Clef'):
                p.remove(existing_clef)
            p.insert(0, clef.Treble8vbClef())
            
    # Structure measures and clean up ALL redundant accidentals (sharps/flats/naturals) properly
    try:
        satb_score = satb_score.makeMeasures()
        for p in satb_score.parts:
            p.makeAccidentals(overrideStatus=True, inPlace=True)
        
        # music21's makeAccidentals has a known bug where it occasionally hallucinates 
        # cautionary natural signs on perfectly diatonic notes (especially when notes are initialized from floats).
        # We manually sweep through and force-hide naturals on diatonic pitch classes to fix this visual artifact.
        scale_pcs = get_scale_pitches(detected_key)
        for p in satb_score.parts:
            for n in p.recurse().notes:
                if n.pitch.accidental and n.pitch.accidental.name == 'natural':
                    if n.pitch.pitchClass in scale_pcs:
                        n.pitch.accidental.displayStatus = False
    except Exception as e:
        print(f"Error structuring measures and accidentals: {e}")
    
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
