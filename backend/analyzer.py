import os
import uuid
from music21 import converter, stream, note, chord, tempo, meter, key, pitch, instrument, clef, analysis, harmony, tie

def get_key_of_score(score):
    """Analyze the key of the input score."""
    try:
        k = score.analyze('key')
        return k
    except:
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
        
        # Only keep chords that contain our melody note's pitch class
        if melody_pitch.pitchClass in chord_pcs:
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
                'degree': degree_idx  # 0=I, 1=II, etc.
            })
    
    # If no diatonic chord contains this note, fall back to just using it as root of major triad
    if not candidates:
        root_pc = melody_pitch.pitchClass
        candidates.append({
            'root_pc': root_pc,
            'quality': 'major',
            'pcs': {root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12},
            'degree': 0
        })
    
    return candidates

def get_leading_tone_pc(scale_key):
    """Get the pitch class of the leading tone (7th scale degree) in a key."""
    tonic_pc = scale_key.tonic.pitchClass
    if scale_key.mode == 'minor':
        return (tonic_pc + 11) % 12  # Raised 7th in harmonic minor
    else:
        return (tonic_pc + 11) % 12  # 7th degree of major scale

def generate_voicings_for_chord(chord_info, melody_midi, ranges, scale_key=None, harmony_style='close'):
    """
    Generate all valid SATB voicings where Soprano = melody_midi exactly,
    and Alto, Tenor, Bass are drawn from the chord's pitch classes within their ranges.
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
    
    s = int(melody_midi)  # Soprano is FIXED to the melody note
    
    # Generate candidates for Alto, Tenor, Bass from chord pitch classes
    a_cands = [p for p in range(int(ranges['Alto'][0]), int(ranges['Alto'][1]) + 1) if p % 12 in pcs]
    t_cands = [p for p in range(int(ranges['Tenor'][0]), int(ranges['Tenor'][1]) + 1) if p % 12 in pcs]
    b_cands = [p for p in range(int(ranges['Bass'][0]), int(ranges['Bass'][1]) + 1) if p % 12 in pcs]
    
    # Tag bass candidates: root gets bonus (handled via penalty later)
    b_has_root = any(p % 12 == root_pc for p in b_cands)
    
    voicings = []
    
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
                        penalty += 15
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
                    # Reward bass in lower register
                    bass_mid = (ranges['Bass'][0] + ranges['Bass'][1]) / 2
                    if b < bass_mid:
                        penalty -= 2
                    elif b > bass_mid + 6:
                        penalty += 3
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
    """
    bass_part = parts['Bass']
    scale_pcs = get_scale_pitches(scale_key) if scale_key else set()
    
    # 1. Bass Passing Tones
    # Create a new stream for the modified bass
    new_bass = stream.Part()
    for el in bass_part:
        if not isinstance(el, note.Note):
            new_bass.append(el)
            continue
            
        new_bass.append(el)
    
    # We need to iterate by index to look ahead
    notes = [n for n in new_bass if isinstance(n, note.Note)]
    for i in range(len(notes) - 1):
        n1 = notes[i]
        n2 = notes[i+1]
        
        if n1.quarterLength >= 1.0:
            interval = n2.pitch.ps - n1.pitch.ps
            if abs(interval) in [3, 4]:  # Leap of a 3rd
                # Split n1
                half_dur = n1.quarterLength / 2.0
                n1.quarterLength = half_dur
                
                # Find diatonic passing tone
                step = 1 if interval > 0 else -1
                passing_ps = n1.pitch.ps
                for j in range(1, 3):
                    test_ps = n1.pitch.ps + (j * step)
                    if (test_ps % 12) in scale_pcs:
                        passing_ps = test_ps
                        break
                
                passing_note = note.Note(passing_ps)
                passing_note.quarterLength = half_dur
                passing_note.volume.velocity = 60
                
                # Insert it right after n1 using offset
                new_bass.insert(n1.offset + half_dur, passing_note)

    parts['Bass'] = new_bass

    # 2. Cadential Suspensions (Alto & Tenor)
    for p_name in ['Alto', 'Tenor']:
        part = parts[p_name]
        new_part = stream.Part()
        for el in part:
            if not isinstance(el, note.Note):
                new_part.append(el)
            else:
                new_part.append(el)
        
        notes = [n for n in new_part if isinstance(n, note.Note)]
        for i in range(len(notes) - 1):
            n1 = notes[i]
            n2 = notes[i+1]
            
            # Look for downward step into a long note (potential cadence)
            if n1.quarterLength >= 1.0 and n2.quarterLength >= 1.0:
                interval = n1.pitch.ps - n2.pitch.ps
                if interval in [1, 2]: # Downward step (minor or major 2nd)
                    # Create suspension: delay n2 by taking the first half of it 
                    # and making it a continuation of n1's pitch
                    half_dur = n2.quarterLength / 2.0
                    n2.quarterLength = half_dur
                    
                    suspension_note = note.Note(n1.pitch.ps)
                    suspension_note.quarterLength = half_dur
                    suspension_note.volume.velocity = n2.volume.velocity
                    
                    # Tie them together so the synth doesn't choke/retrigger
                    n1.tie = tie.Tie('start')
                    suspension_note.tie = tie.Tie('stop')
                    
                    new_part.insert(n2.offset, suspension_note)
                    n2.offset += half_dur # Push the resolution back
        
        parts[p_name] = new_part

def transition_cost(prev_voicing, prev_chord, curr_voicing, curr_chord, scale_key=None, harmony_style='close'):
    """
    Calculate the voice-leading cost between two voicings.
    Enforces all PartWriter rules for transitions.
    """
    cost = 0.0
    errors = []
    names = ['Soprano', 'Alto', 'Tenor', 'Bass']
    
    # 1. Stepwise motion preference (penalize leaps in inner voices)
    for i in range(1, 4):  # Alto, Tenor, Bass
        leap = abs(curr_voicing[i] - prev_voicing[i])
        if leap <= 2:
            cost += 0  # Step or unison: free
        elif leap <= 4:
            cost += 2  # Small leap: minor penalty
        elif leap <= 7:
            cost += 5  # Larger leap
        else:
            cost += 25 if harmony_style in ['traditional', 'strict'] else 15  # Big leap: heavy penalty
    
    # 2. Parallel 5ths/8ves (STRICTLY FORBIDDEN)
    parallels = check_parallels(prev_voicing, curr_voicing)
    if parallels:
        cost += 10000 if harmony_style in ['traditional', 'strict'] else 500
        errors.extend(parallels)
    
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
            cost += 1
    else:
        if root_motion == 5 or root_motion == 7:
            cost -= 2  # Strong progression (motion by 4th/5th)
        elif root_motion == 0:
            cost += 1  # Slight penalty for staying on same chord
    
    # 8. Contrary motion bonus (soprano vs bass)
    if (s_dir > 0 and b_dir < 0) or (s_dir < 0 and b_dir > 0):
        cost -= 1  # Reward contrary motion
    
    return cost, errors

def process_midi(input_path, ranges_str, output_dir, harmony_style='close', tempo_bpm=None, instrument_type='choir', chord_overrides='', practice_volume=90):
    """
    Takes a MIDI melody and generates full SATB harmony.
    The input melody becomes the Soprano line.
    Alto, Tenor, and Bass are generated automatically.
    """
    print(f"Harmonizing melody: {input_path}")
    score = converter.parse(input_path)
    
    # Detect key
    detected_key = get_key_of_score(score)
    print(f"Detected key: {detected_key}")
    
    # Convert ranges
    ranges = {
        'Soprano': (pitch.Pitch(ranges_str['soprano_min']).ps, pitch.Pitch(ranges_str['soprano_max']).ps),
        'Alto': (pitch.Pitch(ranges_str['alto_min']).ps, pitch.Pitch(ranges_str['alto_max']).ps),
        'Tenor': (pitch.Pitch(ranges_str['tenor_min']).ps, pitch.Pitch(ranges_str['tenor_max']).ps),
        'Bass': (pitch.Pitch(ranges_str['bass_min']).ps, pitch.Pitch(ranges_str['bass_max']).ps),
    }
    
    # Extract melody notes (chordify combines all simultaneous parts, then we take the highest note)
    melody_events = []
    for element in score.chordify().flatten().notesAndRests:
        if element.isRest:
            melody_events.append(('rest', element.duration, None))
        elif element.isNote:
            melody_events.append(('note', element.duration, element.pitch))
        elif element.isChord:
            # If input has chords, take the highest note as melody
            melody_events.append(('note', element.duration, max(element.pitches, key=lambda p: p.ps)))
    
    if not melody_events:
        raise Exception("No notes found in the MIDI file.")
        
    print(f"Found {len(melody_events)} melody events")
    
    # ===== VITERBI ALGORITHM =====
    # State = (voicing_tuple, chord_info_dict)
    # dp[i] = { state_key: (cost, prev_state_key, errors) }
    
    dp = []
    state_data = []  # Parallel list: state_data[i][state_key] = (voicing, chord_info)
    
    for i, (etype, dur, mel_pitch) in enumerate(melody_events):
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

        # Generate candidate chords for this melody note
        if forced_chords:
            idx = int( (i / len(melody_events)) * len(forced_chords) )
            fc = forced_chords[idx]
            root_pc = fc.root().pitchClass
            quality = 'major' if 'major' in fc.quality else 'minor' if 'minor' in fc.quality else 'diminished' if 'diminished' in fc.quality else 'other'
            pcs = set(p.pitchClass for p in fc.pitches)
            candidate_chords = [{'root_pc': root_pc, 'quality': quality, 'pcs': pcs, 'degree': 0}]
        else:
            candidate_chords = generate_candidate_chords(mel_pitch, detected_key)
        
        # Generate all valid voicings across all candidate chords
        all_voicings = []
        for ch in candidate_chords:
            voicings = generate_voicings_for_chord(ch, mel_pitch.ps, ranges, detected_key, harmony_style)
            all_voicings.extend(voicings)
        
        if not all_voicings:
            # Emergency fallback — still enforce spacing rules
            s = int(mel_pitch.ps)
            # Alto: within 1 octave below soprano, within alto range
            a = max(s - 7, int(ranges['Alto'][0]))   # Perfect 5th below soprano
            a = min(a, int(ranges['Alto'][1]))
            if s - a > 12: a = s - 12  # Enforce S-A ≤ octave
            
            # Tenor: within 1 octave below alto, within tenor range
            t = max(a - 7, int(ranges['Tenor'][0]))
            t = min(t, int(ranges['Tenor'][1]))
            if a - t > 12: t = a - 12  # Enforce A-T ≤ octave
            
            # Bass: within P12 below tenor, within bass range
            b = max(t - 12, int(ranges['Bass'][0]))
            b = min(b, int(ranges['Bass'][1]))
            if t - b > 19: b = t - 19  # Enforce T-B ≤ P12
            
            fallback_chord = {'root_pc': mel_pitch.pitchClass, 'quality': 'major', 'pcs': {mel_pitch.pitchClass}, 'degree': 0}
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
                
                for prev_key, (prev_cost, _, prev_errors) in dp[i - 1].items():
                    if prev_key == 'rest':
                        tc = doubling_penalty
                        new_errors = []
                    else:
                        prev_voicing, prev_chord = state_data[i - 1][prev_key]
                        tc, new_errors = transition_cost(prev_voicing, prev_chord, voicing, chord_info, detected_key, harmony_style)
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
    
    for idx, (etype, dur, mel_pitch) in enumerate(melody_events):
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
                
    if harmony_style == 'traditional':
        decorate_chorale(parts, detected_key)
    
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
        satb_score.append(parts[p_name])
    
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
                n.volume.velocity = practice_volume if is_target else 25
            
            practice_score.append(part_copy)
            
        p_filename = f"practice_{target_part_name.lower()}_{unique_id}.mid"
        p_filepath = os.path.join(output_dir, p_filename)
        practice_score.write('midi', fp=p_filepath)
        output_files[f"practice_{target_part_name.lower()}"] = p_filename
    
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
        "tempo": tempo_bpm
    }
