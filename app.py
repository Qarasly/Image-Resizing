import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps, ImageStat
import requests
from io import BytesIO
import re
import zipfile

# --- 1. CONFIGURATION ---
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

# --- HELPER FUNCTIONS ---
def get_direct_url(url):
    if pd.isna(url): return url
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
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

def process_image_logic(img, tw, th, final_color):
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", (tw, th), final_color)
    paste_pos = ((tw - img.size[0]) // 2, (th - img.size[1]) // 2)
    new_img.paste(img, paste_pos)
    return new_img

@st.cache_data(show_spinner=False)
def cached_cloud_upload(src, psku, suffix, bg_mode, tw, th, cloudinary_bg):
    try:
        res = cloudinary.uploader.upload(
            src,
            public_id = f"sku_{psku}_{suffix}",
            folder = "team_uploads",
            overwrite = True,
            background_removal = "cloudinary_ai" if bg_mode else None,
            transformation = [{"width": tw, "height": th, "crop": "pad", "background": cloudinary_bg}]
        )
        return res.get("secure_url")
    except Exception as e:
        return f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide")
st.title("🖼️ Bulk Image Resizing Pro")

with st.container(border=True):
    st.subheader("⚙️ Step 1: Configuration")
    s1, s2, s3 = st.columns([1, 1.2, 1.2])
