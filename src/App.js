import React, { useState, useEffect } from 'react';

function App() {
  const [mode, setMode] = useState("sleeping"); // sleeping | listening | speaking

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws");

    ws.onmessage = (event) => {
      // 1. Python hears "Hey Miro"
      if (event.data === "WAKE_UP") {
        console.log("⚡ Wake Word Detected!");
        
        // 2. Switch to LISTENING (Green)
        setMode("listening");

        // 3. AUTOMATIC TEST SEQUENCE (To check animations)
        // After 3 seconds, pretend the AI is thinking/speaking
        setTimeout(() => {
          setMode("speaking"); // Switch to BLUE
          
          // After 4 seconds of speaking, go back to sleep
          setTimeout(() => {
            setMode("sleeping");
          }, 4000);
          
        }, 3000);
      }
    };

    return () => ws.close();
  }, []);

  // --- ANIMATION STYLES ---
  const getOrbStyle = () => {
    switch (mode) {
      case "listening": // 🟢 GREEN PULSE
        return {
          ...styles.orb,
          background: "radial-gradient(circle, #00ff88 0%, #004422 100%)",
          boxShadow: "0 0 40px #00ff88, 0 0 80px #00ff88",
          transform: "scale(1.2)",
          border: "2px solid #fff"
        };
      case "speaking": // 🔵 BLUE WAVE
        return {
          ...styles.orb,
          background: "radial-gradient(circle, #0088ff 0%, #002244 100%)",
          boxShadow: "0 0 40px #0088ff, 0 0 80px #0088ff",
          transform: "scale(1.1)",
          animation: "pulse 1s infinite alternate" // Makes it breathe
        };
      default: // ⚫ SLEEPING GREY
        return {
          ...styles.orb,
          background: "#333",
          boxShadow: "none",
          transform: "scale(1)",
          opacity: 0.8
        };
    }
  };

  return (
    <div style={styles.container}>
      {/* WINDOW CONTROLS */}
      <div style={styles.header}>
        <span style={styles.status}>MIRO AGENT • {mode.toUpperCase()}</span>
        <button style={styles.closeBtn} onClick={() => window.close()}>×</button>
      </div>

      {/* THE GLOWING ORB */}
      <div style={styles.body}>
        <div style={getOrbStyle()}>
          <span style={{fontSize: '40px'}}>
            {mode === "listening" ? "🎤" : mode === "speaking" ? "💬" : "💤"}
          </span>
        </div>
        
        <h2 style={styles.text}>
          {mode === "listening" ? "I'm listening..." : 
           mode === "speaking" ? "Speaking..." : 
           "Say 'Hey Miro'"}
        </h2>
      </div>
      
      {/* CSS FOR BREATHING ANIMATION */}
      <style>{`
        @keyframes pulse {
          0% { transform: scale(1); }
          100% { transform: scale(1.15); }
        }
      `}</style>
    </div>
  );
}

// --- STYLES ---
const styles = {
  container: {
    height: '100vh',
    background: 'rgba(10, 10, 10, 0.95)', // Dark Glass
    color: 'white',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: 'Segoe UI, sans-serif',
    border: '1px solid #333',
    borderRadius: '16px',
    overflow: 'hidden'
  },
  header: {
    padding: '15px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    WebkitAppRegion: 'drag', // DRAGGABLE
    background: 'rgba(255,255,255,0.05)'
  },
  status: { fontSize: '10px', letterSpacing: '2px', color: '#888' },
  closeBtn: {
    background: 'none', border: 'none', color: '#666', 
    fontSize: '24px', cursor: 'pointer', WebkitAppRegion: 'no-drag'
  },
  body: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    alignItems: 'center',
  },
  orb: {
    width: '120px',
    height: '120px',
    borderRadius: '50%',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    transition: 'all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275)', // Bouncy transition
    marginBottom: '30px',
  },
  text: {
    color: '#eee',
    fontSize: '20px',
    fontWeight: '300',
    letterSpacing: '1px'
  }
};

export default App;