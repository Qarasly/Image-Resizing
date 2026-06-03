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
import openpyxl
import time
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
    """Sends the image, fields, and mapping data to Gemini with an auto-retry loop for 503 errors."""
    if not GEMINI_API_KEY:
        return {}
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    fields_schema = {field: f"Value generated for {field}" for field in selected_fields}
    
    prompt = f"""
    You are an e-commerce catalog AI. Analyze this product image.
    
    Here is the global background mapping rules/context for this project:
    {mapping_context}
    
    Based on the image and context, fill out the following requested fields and return them as a valid JSON object matching this exact structure:
    {json.dumps(fields_schema, indent=2)}
    
    Provide accurate information. Return ONLY the raw JSON object. Do not wrap it in markdown code blocks or triple backticks.
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[img, prompt]
            )
            raw = response.text.strip()
            
            backticks = chr(96) * 3
            if raw.startswith(backticks):
                raw = re.sub(r"^" + re.escape(backticks) + r"(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*" + re.escape(backticks) + r"$", "", raw)
                
            return json.loads(raw.strip())
            
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(2 + attempt * 2)
                    continue
            return {field: f"AI Error: {str(e)}" for field in selected_fields}
            
    return {field: "AI Error: Server busy after multiple retries" for field in selected_fields}

@st.cache_data(show_spinner=False)
def process_url_full(src_url, psku, tw, th, final_color_rgb, bg_mode):
    try:
        resp = requests.get(get_direct_url(src_url), timeout=15)
        resp.raise_for_status()
        raw_img = Image.open(BytesIO(resp.content))
        proc_img = process_image_pipeline(raw_img, tw, th, final_color_rgb, bg_mode)
        
        buf = BytesIO(); proc_img.save(buf, format="JPEG", quality=90); buf.seek(0)
        link = upload_to_imgbb(buf, psku)
        return proc_img, link
    except Exception as e:
        return None, f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Resizing & Dynamic AI", layout="wide")
st.title("🏭 Bulk Image Studio & Template-Driven AI")

# STEP 1: GLOBAL CONFIG
with st.container(border=True):
    st.subheader("⚙️ Step 1: Mode & Image Configuration")
    s1, s2, s3 = st.columns([3, 4, 4])
    
    with s1:
        st.write("**Task Features**")
        use_resizer = st.checkbox("Run Image Resizer & Paddin", value=True)
        use_ai_content = st.checkbox("Run Gemini AI Content Generation", value=False)
        
        if not use_resizer and not use_ai_content:
            st.warning("⚠️ Please choose at least one option above to continue.")
            
    with s2:
        st.write("**Processing Options**")
        input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])
        output_mode = st.selectbox("Output Format", ["Links (Excel Sheet)", "Images (ZIP File)"])
        bg_mode = st.toggle("AI Background Removal (rembg)", value=False, disabled=not use_resizer, help="Isolates the product image.")
        
    with s3:
        st.write("**Canvas Background Fill**")
        color_type = st.radio("Style:", ["Standard White", "Automatic (Match Image)", "Custom Color"], horizontal=True, disabled=not use_resizer)
        if color_type == "Custom Color": 
            final_color_rgb = hex_to_rgb(st.color_picker("Pick color", "#FFFFFF"))
        elif color_type == "Standard White": 
            final_color_rgb = (255, 255, 255)
        else: 
            final_color_rgb = "AUTO"
            
        target_w, target_h = 660, 900
        if use_resizer:
            with st.expander("Adjust Dimensions"):
                target_w = st.number_input("Width (px)", min_value=10, value=660)
                target_h = st.number_input("Height (px)", min_value=10, value=900)

# STEP 1B: MANDATORY AI DISCLAIMER SCREEN
ai_liability_accepted = False
if use_ai_content:
    with st.container(border=True
