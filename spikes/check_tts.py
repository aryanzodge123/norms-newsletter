# spikes/check_tts.py
import os
from dotenv import load_dotenv
from google import genai
load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
models = [m.name for m in client.models.list() if "tts" in m.name.lower()]
print("TTS-capable models visible:", models or "none found, check docs")