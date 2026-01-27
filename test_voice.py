# test_voices.py
import os
import json
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
ELEVEN_API_KEY = "sk_01e07b00dd902550788c2ffc74617ec0573e6ffc3c6d00d5"

response = requests.get(
    "https://api.elevenlabs.io/v1/voices",
    headers={"xi-api-key": ELEVEN_API_KEY},
    params={"show_legacy": "true"},
    timeout=30,
)

data = response.json()
voices = data.get("voices", [])

# Save the full response to a JSON file
output_file = "available_voices.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"✅ Saved full API response to: {output_file}")
print(f"✅ Your API key has access to {len(voices)} voices:\n")

for v in voices:
    voice_id = v.get("voice_id", "")
    name = v.get("name", "Unknown")
    category = v.get("category", "Unknown")
    labels = v.get("labels", {})
    gender = labels.get("gender", "unknown")
    
    print(f"  • {name:30} | ID: {voice_id:25} | Gender: {gender:10} | Category: {category}")

print(f"\n📋 Full details saved to '{output_file}'")
print("📋 Copy one of the IDs above to use in your voice_id fields")