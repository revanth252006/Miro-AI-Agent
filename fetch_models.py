import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

with open('models_list.json', 'w') as f:
    json.dump(models, f, indent=4)
