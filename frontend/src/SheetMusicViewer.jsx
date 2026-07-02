import React, { useEffect, useRef } from 'react';
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay';

const SheetMusicViewer = ({ xmlUrl }) => {
  const containerRef = useRef(null);

  useEffect(() => {
    let osmd = null;
    let isMounted = true;

    if (containerRef.current && xmlUrl) {
      osmd = new OpenSheetMusicDisplay(containerRef.current, {
        autoResize: true,
        backend: "svg",
        drawingParameters: "default",
        drawTitle: false,
        drawPartNames: true,
        drawPartAbbreviations: false,
      });
      osmd.load(xmlUrl).then(() => {
        if (isMounted) {
          osmd.render();
        }
      }).catch(err => {
        console.error("OSMD Error:", err);
      });
    }

    return () => {
      isMounted = false;
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [xmlUrl]);

  return (
    <div style={{ 
      width: '100%', 
      maxHeight: '600px', 
      overflowY: 'auto', 
      background: '#fff', 
      borderRadius: '8px',
      padding: '20px 0',
      boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.1)'
    }}>
      <div 
        ref={containerRef} 
        style={{ 
          width: '100%',
          minHeight: '200px'
        }} 
      />
    </div>
  );
};

export default SheetMusicViewer;
