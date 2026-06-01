import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageStat
import requests
from io import BytesIO
import re
import zipfile
import base64
from rembg import remove
import json
from google import genai

# --- 1. SECURE CONFIGURATION ---
IMGBB_API_KEY = st.secrets.get("IMGBB_API_KEY")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

if not IMGBB_API_KEY:
    st.error("🚨 **ImgBB API Key Missing!** Please add `IMGBB_API_KEY` to your Streamlit Secrets.")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_direct_url(url):
    if pd.isna(url): return url
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url

def detect_background_color(img):
    if img.mode != 'RGB': img = img.convert('RGB')
    w, h = img.size
    corners = [img.crop((0,0,5,5)), img.crop((w-5,0,w,5)), img.crop((0,h-5,5,h)), img.crop((w-5,h-5,w,h))]
    r, g, b = 0, 0, 0
    for corner in corners:
        stat = ImageStat.Stat(corner)
        r += stat.mean[0]; g += stat.mean[1]; b += stat.mean[2]
    return (int(r/4), int(g/4), int(b/4))

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def process_image_pipeline(img, tw, th, final_color_rgb, bg_mode):
    if bg_mode: img = remove(img)
    curr_color = detect_background_color(img) if final_color_rgb == "AUTO" else final_color_rgb
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", (tw, th), curr_color)
    paste_pos = ((tw - img.size[0]) // 2, (th - img.size[1]) // 2)
    
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        new_img.paste(img, paste_pos, img)
    else:
        new_img.paste(img, paste_pos)
    return new_img

def upload_to_imgbb(img_buffer, psku):
    url = "https://api.imgbb.com/1/upload"
    payload = {
        "key": IMGBB_API_KEY,
        "image": base64.b64encode(img_buffer.getvalue()).decode("utf-8"),
        "name": f"sku_{psku}"
    }
    res = requests.post(url, data=payload)
    res.raise_for_status()
    return res.json()["data"]["url"]

def generate_dynamic_content(img, selected_fields, mapping_context=""):
    """Sends the image, user chosen fields, and mapping tab data to Gemini."""
    if not GEMINI_API_KEY:
        return {}
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Construct a schema dynamically based on what the user checked
    fields_schema = {field: f"Value/content generated specifically for {field}" for field in selected_fields}
    
    prompt = f"""
    You are an e-commerce catalog AI. Analyze this product image.
    
    Here is the global background mapping rules/context for this project:
    {mapping_context}
    
    Based on the image and context, fill out the following requested fields and return them as a valid JSON object matching this exact structure:
    {json.dumps(fields_schema, indent=2)}
    
    Provide accurate information. Return ONLY the raw JSON object. Do not wrap it in markdown block tags like ```json.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[img, prompt]
        )
        raw = response.text.strip()
        if raw.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

Push this to GitHub, click **Reboot App** on your Streamlit Cloud platform, and you will have your fully custom, Row 8 tab-selectable catalog wizard!
