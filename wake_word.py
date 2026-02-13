import pvporcupine
import pyaudio
import struct
import os
from dotenv import load_dotenv

load_dotenv()

class WakeWordListener:
    def __init__(self):
        self.access_key = os.getenv("PICOVOICE_API_KEY") # Add this to your .env
        if not self.access_key:
            raise ValueError("❌ Missing PICOVOICE_API_KEY in .env file")

        # Initialize Porcupine with custom "Hey Miro" model if available, else fallback to "Jarvis"
        try:
            custom_ppn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Hey-miro_en_windows_v4_0_0.ppn")
            if os.path.exists(custom_ppn):
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keyword_paths=[custom_ppn]
                )
                print("✅ Wake word loaded: Hey Miro (custom model)")
            else:
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=['jarvis']
                )
                print("⚠️ Custom wake word not found, using built-in 'Jarvis'")
        except Exception as e:
            print(f"❌ Porcupine Error: {e}")
            raise

        self.pa = pyaudio.PyAudio()
        self.audio_stream = self.pa.open(
            rate=self.porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.porcupine.frame_length
        )

    def listen(self):
        """
        Listens for the wake word. Returns True when heard.
        """
        try:
            pcm = self.audio_stream.read(self.porcupine.frame_length)
            pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm)
            keyword_index = self.porcupine.process(pcm)

            if keyword_index >= 0:
                return True
        except Exception as e:
            print(f"🎤 Audio Error: {e}")
            
        return False

    def close(self):
        if self.audio_stream: self.audio_stream.close()
        if self.pa: self.pa.terminate()
        self.porcupine.delete()