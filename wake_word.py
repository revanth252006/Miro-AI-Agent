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

        # Initialize Porcupine with "Jarvis" (Built-in)
        # You can change keywords=['picovoice'] or ['computer'] if you prefer.
        try:
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=['jarvis'] 
            )
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