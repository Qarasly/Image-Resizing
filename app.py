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
    
    with s1:
        st.write("**Dimensions**")
        target_w = st.number_input("Width (px)", min_value=10, value=660)
        target_h = st.number_input("Height (px)", min_value=10, value=900)
        st.info("💡 Recommended for NIS: 660 x 900")
    
    with s2:
        st.write("**I/O Options**")
        input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])
        output_mode = st.selectbox("Output Format", ["Links (Excel Sheet)", "Images (ZIP File)"])
        bg_mode = st.toggle("AI Background Replacement", help="Removes background using Cloudinary AI.")

    with s3:
        st.write("**Background Color**")
        color_type = st.radio("Style:", ["Standard White", "Automatic (Match Image)", "Custom Color"], horizontal=True)
        
        if color_type == "Custom Color":
            hex_color = st.color_picker("Pick color", "#FFFFFF")
            final_color_rgb = hex_to_rgb(hex_color)
            cloudinary_bg = f"rgb:{hex_color.lstrip('#')}"
        elif color_type == "Standard White":
            final_color_rgb = (255, 255, 255)
            cloudinary_bg = "white"
        else:
            final_color_rgb = "AUTO"
            cloudinary_bg = "auto"

st.divider()

# --- DATA PREPARATION ---
data_to_process = []
df_original = None

if input_mode == "Links (Excel/CSV Sheet)":
    uploaded_file = st.file_uploader("Upload Sheet", type=["csv", "xlsx"])
    if uploaded_file:
        df_original = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        c1, c2 = st.columns(2)
        with c1: sku_col = st.selectbox("Select SKU Column", df_original.columns)
        with c2: url_cols = st.multiselect("Select URL Column(s)", [c for c in df_original.columns if c != sku_col])
        if url_cols:
            for idx, row in df_original.iterrows():
                for col in url_cols:
                    data_to_process.append({"sku": str(row[sku_col]), "content": row[col], "col_name": col, "row_idx": idx, "type": "url"})
else:
    uploaded_imgs = st.file_uploader("Upload Images", type=["jpg", "png", "webp"], accept_multiple_files=True)
    if uploaded_imgs:
        for img_file in uploaded_imgs:
            psku_name = img_file.name.
