import React, { useState, useRef } from 'react';
import { Upload, Music, Image, FileText, Download, Loader, CheckCircle, AlertTriangle, Play, Pause, X, Square, Settings, FileBox } from 'lucide-react';
import SheetMusicViewer from './SheetMusicViewer';
import 'html-midi-player';
import './index.css';

const ACCEPTED_EXTENSIONS = ['.mid', '.midi', '.musicxml', '.xml', '.mxl', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.pdf'];
const ACCEPT_STRING = '.mid,.midi,.musicxml,.xml,.mxl,.png,.jpg,.jpeg,.bmp,.tiff,.tif,.pdf';

// Use environment variable for production API, default to localhost for development
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function getFileType(filename) {
  const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase();
  if (['.mid', '.midi'].includes(ext)) return 'midi';
  if (['.musicxml', '.xml', '.mxl'].includes(ext)) return 'musicxml';
  if (['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'].includes(ext)) return 'image';
  if (['.pdf'].includes(ext)) return 'pdf';
  return null;
}

function getFileTypeLabel(type) {
  switch (type) {
    case 'midi': return '🎹 MIDI File';
    case 'musicxml': return '🎼 MusicXML Sheet Music';
    case 'image': return '📷 Sheet Music Image';
    case 'pdf': return '📄 PDF Sheet Music';
    default: return '📁 File';
  }
}

function isValidFile(filename) {
  const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

function App() {
  const [file, setFile] = useState(null);
  const [fileType, setFileType] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [results, setResults] = useState(null);
  const [errorLogs, setErrorLogs] = useState([]);
  const [error, setError] = useState(null);
  const [inputType, setInputType] = useState(null);
  const [detectedKey, setDetectedKey] = useState(null);
  const [playingPart, setPlayingPart] = useState(null);
  const [activeTrack, setActiveTrack] = useState(null); // { node: DOMElement, title: string, isPlaying: boolean }
  const dismissedPlayerRef = useRef(null); // Tracks the player node the user explicitly dismissed
  const audioRef = useRef(null);

  // Settings
  const [harmonyStyle, setHarmonyStyle] = useState('strict');
  const [tempoBpm, setTempoBpm] = useState(100);
  const [keepParts, setKeepParts] = useState([]);
  const [showSettings, setShowSettings] = useState(false);
  const [instrumentType, setInstrumentType] = useState('choir');
  const [chordOverrides, setChordOverrides] = useState('');
  const [keyOverride, setKeyOverride] = useState('');
  const [showKeyDropdown, setShowKeyDropdown] = useState(false);

  const [ranges] = useState({
    soprano_min: 'C4', soprano_max: 'G5',
    alto_min: 'G3', alto_max: 'C5',
    tenor_min: 'C3', tenor_max: 'G4',
    bass_min: 'E2', bass_max: 'C4'
  });

  // Global Player Tracker
  React.useEffect(() => {
    const interval = setInterval(() => {
      let foundPlaying = false;
      document.querySelectorAll('midi-player').forEach(player => {
        if (player.playing) {
          // Skip this player if the user explicitly dismissed it
          if (dismissedPlayerRef.current === player) return;
          foundPlaying = true;
          const title = player.getAttribute('data-track-title') || 'Playing Audio';
          setActiveTrack({ node: player, title, isPlaying: true });
        }
      });
      
      if (!foundPlaying) {
        setActiveTrack(prev => {
          if (prev && prev.isPlaying) {
            // Music just stopped naturally (finished playing) — clear the dismissed ref too
            dismissedPlayerRef.current = null;
            return { ...prev, isPlaying: false };
          }
          return prev;
        });
      }
    }, 300);
    return () => clearInterval(interval);
  }, []);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFile = e.dataTransfer.files[0];
      if (isValidFile(droppedFile.name)) {
        setFile(droppedFile);
        setFileType(getFileType(droppedFile.name));
        setError(null);
        setResults(null);
      } else {
        setError('Unsupported file. Please upload MIDI, MusicXML, an image of sheet music, or a PDF.');
      }
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      setFileType(getFileType(selectedFile.name));
      setError(null);
      setResults(null);
    }
  };

  const toggleKeepPart = (part) => {
    setKeepParts(prev => 
      prev.includes(part) ? prev.filter(p => p !== part) : [...prev, part]
    );
  };

  const handleStartOver = () => {
    // Stop any playing audio before clearing
    document.querySelectorAll('midi-player').forEach(player => {
      try { player.stop(); } catch(e) {}
    });
    dismissedPlayerRef.current = null;
    setActiveTrack(null);
    setResults(null);
  };

  const handleAnalyze = async () => {
    if (!file) return;
    
    setIsAnalyzing(true);
    setError(null);
    setResults(null);
    setErrorLogs([]);
    setInputType(null);
    setDetectedKey(null);

    const formData = new FormData();
    formData.append('file', file);
    Object.entries(ranges).forEach(([key, val]) => {
      formData.append(key, val);
    });
    formData.append('harmony_style', harmonyStyle);
    formData.append('tempo_bpm', tempoBpm.toString());
    formData.append('instrument_type', instrumentType);
    formData.append('chord_overrides', chordOverrides);
    formData.append('keep_parts', keepParts.join(','));
    formData.append('key_override', keyOverride);

    try {
      const response = await fetch(`${API_URL}/analyze`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Analysis failed');
      }

      const data = await response.json();
      setResults(data.files);
      setInputType(data.input_type);
      setDetectedKey(data.key || null);
      if (data.errors) {
        setErrorLogs(data.errors);
      }
    } catch (err) {
      setError(err.message || 'An error occurred during analysis. Make sure the backend is running.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handlePlay = async (filename) => {
    // Stop any currently playing audio
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }

    if (playingPart === filename) {
      setPlayingPart(null);
      return;
    }

    try {
      const response = await fetch(`${API_URL}/download/${filename}`);
      if (!response.ok) throw new Error('File not found');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      
      // Use the MIDI file URL with an audio element (browsers with MIDI support)
      // Fallback: just download the file
      setPlayingPart(filename);
      
      // Auto-stop after a timeout (since we can't actually play MIDI natively in all browsers)
      // We'll indicate which file is "selected" for the user
      setTimeout(() => {
        setPlayingPart(null);
      }, 3000);
    } catch (err) {
      console.error('Playback error:', err);
      setPlayingPart(null);
    }
  };

  const getAnalyzingText = () => {
    if (fileType === 'image') return 'Scanning Sheet Music & Generating Parts...';
    if (fileType === 'musicxml' || fileType === 'pdf') return 'Reading Sheet Music & Generating Parts...';
    return 'Analyzing Melody & Generating Harmony...';
  };

  const partLabels = {
    'Soprano': '🎵 Soprano',
    'Alto': '🎵 Alto',
    'Tenor': '🎵 Tenor',
    'Bass': '🎵 Bass',
    'practice_soprano': '🎧 Soprano Practice Track',
    'practice_alto': '🎧 Alto Practice Track',
    'practice_tenor': '🎧 Tenor Practice Track',
    'practice_bass': '🎧 Bass Practice Track',
    'combined': '🎶 Full SATB Score',
    'musicxml': '📄 MusicXML Score',
    'pdf': '📄 PDF Score'
  };

  return (
    <div className="app-container">
      <header className="mb-8" style={{ textAlign: 'center' }}>
        <h1 className="text-gradient" style={{ fontSize: '3rem', marginBottom: '1rem' }}>KBC Ebenezer Choir</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '1.2rem', maxWidth: '700px', margin: '0 auto' }}>
          Upload a MIDI file, MusicXML sheet music, or even a <strong>photo of sheet music</strong>. 
          The AI engine will read the melody and generate a full 4-part SATB choir arrangement.
        </p>
      </header>

      <div style={{ maxWidth: '700px', margin: '0 auto' }}>
        <div className="glass-panel">
          <h2 className="flex items-center gap-2 mb-4"><Upload size={24} /> Upload Music</h2>
          
          {/* Input type buttons */}
          <div className="flex gap-2 mb-4" style={{ flexWrap: 'wrap' }}>
            <button className="badge badge-btn" onClick={() => { document.getElementById('fileMidi').click(); }}>🎹 MIDI</button>
            <input type="file" id="fileMidi" accept=".mid,.midi" style={{ display: 'none' }} onChange={handleFileChange} />

            <button className="badge badge-btn" onClick={() => { document.getElementById('fileXml').click(); }}>🎼 MusicXML</button>
            <input type="file" id="fileXml" accept=".musicxml,.xml,.mxl" style={{ display: 'none' }} onChange={handleFileChange} />

            <button className="badge badge-btn badge-new" onClick={() => { document.getElementById('fileImg').click(); }}>📷 Sheet Music Image</button>
            <input type="file" id="fileImg" accept=".png,.jpg,.jpeg,.bmp,.tiff,.tif" style={{ display: 'none' }} onChange={handleFileChange} />

            <button className="badge badge-btn" onClick={() => { document.getElementById('filePdf').click(); }}>📄 PDF</button>
            <input type="file" id="filePdf" accept=".pdf" style={{ display: 'none' }} onChange={handleFileChange} />
          </div>

          <div 
            className={`upload-zone ${isDragging ? 'active' : ''}`}
            style={{ marginTop: '1.5rem' }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => document.getElementById('fileUpload').click()}
          >
            <input 
              type="file" 
              id="fileUpload" 
              accept={ACCEPT_STRING}
              style={{ display: 'none' }} 
              onChange={handleFileChange}
            />
            {fileType === 'image' ? <Image className="upload-icon" /> : <Music className="upload-icon" />}
            {file ? (
              <div>
                <h3 style={{ color: 'var(--success-color)' }}>{file.name}</h3>
                <p className="text-secondary">{getFileTypeLabel(fileType)} — Ready for processing</p>
              </div>
            ) : (
              <div>
                <h3>Drag & Drop your file here</h3>
                <p className="text-secondary">MIDI, MusicXML, Image (PNG/JPG), or PDF</p>
              </div>
            )}
          </div>

          {/* Image preview */}
          {file && fileType === 'image' && (
            <div className="mt-4" style={{ borderRadius: '12px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)' }}>
              <img 
                src={URL.createObjectURL(file)} 
                alt="Sheet music preview" 
                style={{ width: '100%', maxHeight: '300px', objectFit: 'contain', background: '#fff' }}
              />
            </div>
          )}

          {/* Settings Toggle */}
          <button 
            className="btn mt-4" 
            onClick={() => setShowSettings(!showSettings)}
            style={{ padding: '0.6rem 1rem', fontSize: '0.9rem', width: '100%', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}
          >
            <Settings size={16} style={{ marginRight: '8px', display: 'inline' }} />
            {showSettings ? 'Hide Settings' : 'Show Settings'}
          </button>

          {/* Settings Panel */}
          {showSettings && (
            <div className="mt-4" style={{ padding: '1.2rem', background: 'rgba(255,255,255,0.03)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.08)' }}>
              
              {/* Harmony Style Toggle */}
              <div style={{ marginBottom: '1.2rem' }}>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.5rem' }}>
                  Harmony Style
                </label>
                <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                  <button 
                    className={`badge badge-btn ${harmonyStyle === 'close' ? 'badge-active' : ''}`}
                    onClick={() => setHarmonyStyle('close')}
                  >
                    🎵 Close Harmony
                  </button>
                  <button 
                    className={`badge badge-btn ${harmonyStyle === 'wide' ? 'badge-active' : ''}`}
                    onClick={() => setHarmonyStyle('wide')}
                  >
                    🎶 Wide Harmony
                  </button>
                  <button 
                    className={`badge badge-btn ${harmonyStyle === 'traditional' ? 'badge-active' : ''}`}
                    onClick={() => setHarmonyStyle('traditional')}
                  >
                    🏛️ Traditional Hymns
                  </button>
                  <button 
                    className={`badge badge-btn ${harmonyStyle === 'strict' ? 'badge-active' : ''}`}
                    onClick={() => setHarmonyStyle('strict')}
                  >
                    🎹 Strict Block Chords
                  </button>
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.4rem' }}>
                  {harmonyStyle === 'close' 
                    ? 'Voices stay tight together (1–1.5 octaves apart)' 
                    : harmonyStyle === 'wide'
                    ? 'Bass sings deep, creating a full organ-like church choir sound'
                    : harmonyStyle === 'traditional'
                    ? 'Strict Bach Chorale rules with independent rhythms (passing tones and suspensions)'
                    : 'Strict Bach Chorale rules, but strictly follows the soprano rhythm (no passing tones or suspensions)'}
                </p>
              </div>

              {/* Instrument Toggle */}
              <div style={{ marginBottom: '1.2rem' }}>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.5rem' }}>
                  Instrument
                </label>
                <div className="flex gap-2">
                  <button 
                    className={`badge badge-btn ${instrumentType === 'choir' ? 'badge-active' : ''}`}
                    onClick={() => setInstrumentType('choir')}
                  >
                    🎤 Choir Aahs
                  </button>
                  <button 
                    className={`badge badge-btn ${instrumentType === 'piano' ? 'badge-active' : ''}`}
                    onClick={() => setInstrumentType('piano')}
                  >
                    🎹 Piano
                  </button>
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.4rem' }}>
                  {instrumentType === 'choir' 
                    ? 'Choir Aahs — warm vocal sound for church choir' 
                    : 'Piano — classic keyboard sound for rehearsal'}
                </p>
              </div>

              {/* Tempo Slider */}
              <div style={{ marginBottom: '1.2rem' }}>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.5rem' }}>
                  Tempo: <span style={{ color: 'var(--accent-color)', fontWeight: 'bold' }}>{tempoBpm} BPM</span>
                </label>
                <input 
                  type="range" 
                  min="40" 
                  max="200" 
                  value={tempoBpm} 
                  onChange={(e) => setTempoBpm(parseInt(e.target.value))}
                  className="tempo-slider"
                  style={{ width: '100%' }}
                />
                <div className="flex" style={{ justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                  <span>40 (Slow)</span>
                  <span>120 (Medium)</span>
                  <span>200 (Fast)</span>
                </div>
              </div>

              {/* Chord Overrides */}
              <div>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.5rem' }}>
                  Manual Chord Overrides (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. C, F, G, C or C, Am, Dm, G7"
                  value={chordOverrides}
                  onChange={(e) => setChordOverrides(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.8rem',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '6px',
                    color: '#fff',
                    outline: 'none',
                    boxSizing: 'border-box'
                  }}
                />
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.4rem' }}>
                  Leave blank for automatic AI harmonization. If provided, the AI will strictly follow these chords.
                </p>
              </div>

              {/* Key Override */}
              <div style={{ marginBottom: '1.2rem', position: 'relative' }}>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.5rem' }}>
                  Key Override (Optional)
                </label>
                
                <div 
                  onClick={() => setShowKeyDropdown(!showKeyDropdown)}
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.8rem',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '6px',
                    color: 'var(--text-primary)',
                    fontFamily: 'inherit',
                    boxSizing: 'border-box',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    transition: 'all 0.2s ease'
                  }}
                  className="dropdown-toggle hover-bright"
                >
                  <span style={{ fontSize: '0.9rem', fontWeight: keyOverride ? '600' : 'normal', color: keyOverride ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                    {keyOverride === '' ? '🔍 Auto-Detect (default)' : 
                     keyOverride === 'C' ? 'C Major' : keyOverride === 'c' ? 'C Minor' :
                     keyOverride === 'C#' ? 'C♯ Major / D♭ Major' : keyOverride === 'c#' ? 'C♯ Minor / D♭ Minor' :
                     keyOverride === 'D' ? 'D Major' : keyOverride === 'd' ? 'D Minor' :
                     keyOverride === 'E-' ? 'E♭ Major' : keyOverride === 'e-' ? 'E♭ Minor' :
                     keyOverride === 'E' ? 'E Major' : keyOverride === 'e' ? 'E Minor' :
                     keyOverride === 'F' ? 'F Major' : keyOverride === 'f' ? 'F Minor' :
                     keyOverride === 'F#' ? 'F♯ Major / G♭ Major' : keyOverride === 'f#' ? 'F♯ Minor / G♭ Minor' :
                     keyOverride === 'G' ? 'G Major' : keyOverride === 'g' ? 'G Minor' :
                     keyOverride === 'A-' ? 'A♭ Major' : keyOverride === 'a-' ? 'A♭ Minor' :
                     keyOverride === 'A' ? 'A Major' : keyOverride === 'a' ? 'A Minor' :
                     keyOverride === 'B-' ? 'B♭ Major' : keyOverride === 'b-' ? 'B♭ Minor' :
                     keyOverride === 'B' ? 'B Major' : 'B Minor'}
                  </span>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: showKeyDropdown ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }}>
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </div>
                
                {showKeyDropdown && (
                  <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    marginTop: '8px',
                    background: 'rgba(15, 23, 42, 0.85)',
                    backdropFilter: 'blur(16px)',
                    WebkitBackdropFilter: 'blur(16px)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    fontFamily: 'inherit',
                    boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
                    zIndex: 100,
                    maxHeight: '250px',
                    overflowY: 'auto',
                    padding: '0.5rem'
                  }}
                  className="custom-scrollbar"
                >
                    {[
                      { val: '', label: '🔍 Auto-Detect (default)' },
                      { val: 'C', label: 'C Major' }, { val: 'c', label: 'C Minor' },
                      { val: 'C#', label: 'C♯ Major / D♭ Major' }, { val: 'c#', label: 'C♯ Minor / D♭ Minor' },
                      { val: 'D', label: 'D Major' }, { val: 'd', label: 'D Minor' },
                      { val: 'E-', label: 'E♭ Major' }, { val: 'e-', label: 'E♭ Minor' },
                      { val: 'E', label: 'E Major' }, { val: 'e', label: 'E Minor' },
                      { val: 'F', label: 'F Major' }, { val: 'f', label: 'F Minor' },
                      { val: 'F#', label: 'F♯ Major / G♭ Major' }, { val: 'f#', label: 'F♯ Minor / G♭ Minor' },
                      { val: 'G', label: 'G Major' }, { val: 'g', label: 'G Minor' },
                      { val: 'A-', label: 'A♭ Major' }, { val: 'a-', label: 'A♭ Minor' },
                      { val: 'A', label: 'A Major' }, { val: 'a', label: 'A Minor' },
                      { val: 'B-', label: 'B♭ Major' }, { val: 'b-', label: 'B♭ Minor' },
                      { val: 'B', label: 'B Major' }, { val: 'b', label: 'B Minor' }
                    ].map(opt => (
                      <div 
                        key={opt.val}
                        onClick={() => { setKeyOverride(opt.val); setShowKeyDropdown(false); }}
                        style={{
                          padding: '0.6rem 1rem',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          background: keyOverride === opt.val ? 'rgba(217, 70, 239, 0.15)' : 'transparent',
                          border: 'none',
                          color: keyOverride === opt.val ? 'var(--text-primary)' : 'var(--text-secondary)',
                          fontWeight: keyOverride === opt.val ? '500' : 'normal',
                          boxShadow: 'none',
                          marginBottom: '2px',
                          transition: 'all 0.1s ease'
                        }}
                        onMouseEnter={(e) => { 
                          if (keyOverride !== opt.val) {
                            e.target.style.background = 'rgba(255,255,255,0.1)'; 
                            e.target.style.color = 'var(--text-primary)';
                          } 
                        }}
                        onMouseLeave={(e) => { 
                          if (keyOverride !== opt.val) {
                            e.target.style.background = 'transparent'; 
                            e.target.style.color = 'var(--text-secondary)';
                          } 
                        }}
                      >
                        {opt.label}
                      </div>
                    ))}
                  </div>
                )}
                
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.5rem' }}>
                  Leave on Auto-Detect for most hymns. Use this to manually force a key if the AI gets it wrong.
                </p>
              </div>
              
              {/* Keep Parts Checkboxes */}
              <div style={{ marginBottom: '1.2rem' }}>
                <label style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'block', marginBottom: '0.8rem' }}>
                  Keep Original Parts (Optional)
                </label>
                <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                  {['Soprano', 'Alto', 'Tenor', 'Bass'].map(part => (
                    <button 
                      key={part}
                      onClick={() => toggleKeepPart(part)}
                      className={`badge badge-btn ${keepParts.includes(part) ? 'badge-active' : ''}`}
                    >
                      {keepParts.includes(part) ? (
                        <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" style={{ marginRight: '6px', display: 'inline' }}><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>
                      ) : (
                        <span style={{ display: 'inline-block', width: '20px' }}></span>
                      )}
                      {part}
                    </button>
                  ))}
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.6rem' }}>
                  Select the parts included in your MIDI file. The AI will preserve them and only generate the missing parts. Leave all blank to generate everything from scratch.
                </p>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4" style={{ padding: '1rem', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--error-color)', borderRadius: '8px', color: 'var(--error-color)' }}>
              {error}
            </div>
          )}

          <button 
            className="btn btn-primary w-full mt-4" 
            onClick={handleAnalyze}
            disabled={!file || isAnalyzing}
            style={{ padding: '1rem', fontSize: '1.2rem' }}
          >
            {isAnalyzing ? <><Loader className="spinner" /> {getAnalyzingText()}</> : 'Generate SATB Arrangement'}
          </button>
        </div>
      </div>

      {results && (
        <div className="mt-8" style={{ maxWidth: '700px', margin: '2rem auto 0' }}>
          
          {inputType === 'image_omr' && (
            <div className="glass-panel mb-4" style={{ border: '1px solid rgba(168, 85, 247, 0.4)', background: 'rgba(168, 85, 247, 0.05)' }}>
              <p style={{ color: '#c084fc', margin: 0 }}>
                📷 <strong>OMR Scan Complete</strong> — Notes were read from your sheet music image and harmonized into 4 parts.
              </p>
            </div>
          )}

          <div className="glass-panel" style={{ border: '1px solid var(--success-color)' }}>
            <h2 className="flex items-center gap-2 mb-4 text-gradient"><CheckCircle size={28} /> Arrangement Generated</h2>
            
            {/* Key & Style Info */}
            <div className="flex gap-2 mb-4" style={{ flexWrap: 'wrap' }}>
              {detectedKey && (
                <span className="badge" style={{ background: 'rgba(16, 185, 129, 0.15)', borderColor: 'rgba(16, 185, 129, 0.3)', color: '#6ee7b7' }}>
                  🔑 Key: {detectedKey}
                </span>
              )}
              <span className="badge">
                🎵 {harmonyStyle === 'close' ? 'Close Harmony' : harmonyStyle === 'wide' ? 'Wide Harmony' : harmonyStyle === 'traditional' ? 'Traditional Hymns' : 'Strict Block Chords'}
              </span>
              <span className="badge">
                🎛️ {tempoBpm} BPM
              </span>
            </div>

            <p className="mb-4">Download each voice part below. Open in any MIDI player to hear the choir arrangement.</p>
            
            <div className="grid grid-cols-1 gap-4" style={{ display: 'flex', flexDirection: 'column' }}>
              {Object.entries(results).map(([part, filename]) => (
                <div key={part} className="flex gap-2 items-center" style={{ padding: '0.8rem', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  
                  {/* For combined track, show the web player with visualizer */}
                  {part === 'combined' ? (
                    <div style={{ flex: 1 }}>
                      <div className="flex gap-2 items-center mb-2">
                        <span style={{ fontWeight: '500', color: '#fff' }}>{partLabels[part] || part}</span>
                        <a href={`${API_URL}/download/${filename}`} className="btn ml-auto" download>
                          <Download size={16} style={{ display: 'inline', marginRight: '6px' }} /> Download
                        </a>
                      </div>
                      <midi-player 
                        data-track-title="Original Melody (Full Mix)"
                        src={`${API_URL}/download/${filename}`} 
                        sound-font="https://storage.googleapis.com/magentadata/js/soundfonts/sgm_plus" 
                        visualizer="#my-visualizer"
                        style={{ width: '100%', outline: 'none' }}
                      />
                      <midi-visualizer type="waterfall" id="my-visualizer" style={{ width: '100%', height: '150px', marginTop: '10px' }}></midi-visualizer>
                    </div>
                  ) : (
                    <div className="flex gap-4 items-center w-full" style={{ flexWrap: 'wrap' }}>
                      <div className="flex items-center gap-2" style={{ minWidth: '150px' }}>
                        {filename.endsWith('.pdf') && <FileBox size={16} />}
                        <span style={{ fontWeight: '500', color: '#fff' }}>{partLabels[part] || part}</span>
                      </div>
                      
                      {/* Real MIDI Player for individual parts */}
                      {filename.endsWith('.mid') && (
                        <div style={{ flex: 1, minWidth: '200px' }}>
                          <midi-player 
                            data-track-title={partLabels[part] || part}
                            src={`${API_URL}/download/${filename}`} 
                            sound-font="https://storage.googleapis.com/magentadata/js/soundfonts/sgm_plus" 
                            style={{ width: '100%', outline: 'none' }}
                          />
                        </div>
                      )}
                      
                      <a href={`${API_URL}/download/${filename}`} className="btn ml-auto" download>
                        <Download size={16} style={{ display: 'inline', marginRight: '6px' }} /> Download
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
            
            {results['musicxml'] && (
              <div className="mt-8">
                <h3 className="mb-4 text-gradient flex items-center gap-2"><FileText size={20} /> Live Sheet Music Preview</h3>
                <SheetMusicViewer xmlUrl={`${API_URL}/download/${results['musicxml']}`} />
              </div>
            )}
            
            <button 
              className="btn w-full" 
              style={{ marginTop: '3rem' }} 
              onClick={handleStartOver}
            >
              Start Over
            </button>
          </div>

          {errorLogs.length > 0 && (
            <div className="glass-panel mt-4" style={{ border: '1px solid var(--error-color)' }}>
              <h2 className="flex items-center gap-2 mb-4" style={{ color: 'var(--error-color)' }}>
                <AlertTriangle size={28} /> Constraint Violations
              </h2>
              <p className="mb-4 text-secondary">
                The algorithm could not find a perfect path without breaking some rules:
              </p>
              <ul style={{ maxHeight: '200px', overflowY: 'auto', paddingLeft: '1.5rem', color: '#fca5a5' }}>
                {errorLogs.map((err, idx) => (
                  <li key={idx} style={{ marginBottom: '0.5rem' }}>{err}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      
      {/* Footer */}
      <footer style={{
        marginTop: '4rem',
        padding: '2rem',
        textAlign: 'center',
        color: 'var(--text-secondary)',
        fontSize: '0.9rem',
        borderTop: '1px solid rgba(255,255,255,0.05)'
      }}>
        <p>&copy; {new Date().getFullYear()} Samir Karki. All Rights Reserved.</p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', marginTop: '1rem' }}>
          <a href="https://www.facebook.com/samirkarki077/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-color)', textDecoration: 'none', fontWeight: '500' }}>
            Facebook
          </a>
          <a href="https://www.instagram.com/samirr0_7/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-color)', textDecoration: 'none', fontWeight: '500' }}>
            Instagram
          </a>
        </div>
        <p style={{ marginTop: '1rem' }}>HEHEHEHEHE!!!!</p>
      </footer>

      {/* Global Now Playing Widget */}
      {activeTrack && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '12px 20px',
          background: 'rgba(15, 23, 42, 0.85)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          border: '1px solid rgba(217, 70, 239, 0.3)',
          borderRadius: '50px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.5), 0 0 15px rgba(217, 70, 239, 0.2)',
          color: '#fff',
          animation: 'slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
          transition: 'all 0.3s ease'
        }}>
          {/* Animated EQ Bars */}
          <div className="flex items-end gap-[3px] h-[16px] overflow-hidden">
            <div className="bg-accent rounded-t-sm" style={{ width: '3px', height: activeTrack.isPlaying ? '100%' : '20%', animation: activeTrack.isPlaying ? 'bounce 1.2s infinite ease-in-out' : 'none' }}></div>
            <div className="bg-accent rounded-t-sm" style={{ width: '3px', height: activeTrack.isPlaying ? '60%' : '20%', animation: activeTrack.isPlaying ? 'bounce 0.9s infinite ease-in-out' : 'none', animationDelay: '0.1s' }}></div>
            <div className="bg-accent rounded-t-sm" style={{ width: '3px', height: activeTrack.isPlaying ? '80%' : '20%', animation: activeTrack.isPlaying ? 'bounce 1.1s infinite ease-in-out' : 'none', animationDelay: '0.2s' }}></div>
          </div>
          
          <div className="flex flex-col mr-2">
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Now Playing</span>
            <span style={{ fontSize: '0.9rem', fontWeight: '600' }}>{activeTrack.title}</span>
          </div>

          <button 
            onClick={() => {
              if (activeTrack.node) {
                activeTrack.node.playing = !activeTrack.isPlaying;
              }
            }}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: 'none',
              borderRadius: '50%',
              width: '36px',
              height: '36px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: '#fff',
              transition: 'background 0.2s'
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
          >
            {activeTrack.isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" style={{ marginLeft: '2px' }} />}
          </button>
          
          <button 
            onClick={() => {
              if (activeTrack.node) {
                // Mark this player as dismissed so the poller won't re-show the widget
                dismissedPlayerRef.current = activeTrack.node;
                try {
                  activeTrack.node.stop();
                } catch(e) {}
              }
              setActiveTrack(null);
            }}
            style={{
              background: 'transparent',
              border: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: '4px',
              transition: 'color 0.2s'
            }}
            onMouseEnter={e => e.currentTarget.style.color = '#fff'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
          >
            <X size={18} />
          </button>
        </div>
      )}
    </div>
  );
}

export default App;
