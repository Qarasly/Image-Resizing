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
    """Resizes image with specific RGB padding."""
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", (tw, th), final_color)
    paste_pos = ((tw - img.size[0]) // 2, (th - img.size[1]) // 2)
    new_img.paste(img, paste_pos)
    return new_img

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide")
st.title("🖼️ Bulk Image Resizing Pro")

# --- SETTINGS PANEL ---
with st.container(border=True):
    st.subheader("⚙️ Step 1: Configuration")
    s1, s2, s3 = st.columns([1, 1.2, 1.2])
    
    with s1:
        st.write("**Dimensions**")
        target_w = st.number_input("Width (px)", min_value=10, value=660)
        target_h = st.number_input("Height (px)", min_value=10, value=900)
        st.caption("💡 Recommended for NIS: 660 x 900")
    
    with s2:
        st.write("**I/O Options**")
        input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])
        output_mode = st.selectbox("Output Format", ["Links (Excel Sheet)", "Images (ZIP File)"])
        bg_mode = st.toggle("AI Background Replacement", help="Removes original background. Uses Cloudinary credits.")

    with s3:
        st.write("**Background Color**")
        # Easy Selector for the team
        color_type = st.radio(
            "Choose Background Style:",
            ["Standard White", "Automatic (Match Image)", "Custom Color"],
            horizontal=True
        )
        
        final_color_rgb = (255, 255, 255) # Default
        
        if color_type == "Custom Color":
            hex_color = st.color_picker("Pick a brand color", "#FFFFFF")
            final_color_rgb = hex_to_rgb(hex_color)
        elif color_type == "Standard White":
            final_color_rgb = (255, 255, 255)
        elif color_type == "Automatic (Match Image)":
            st.info("✨ AI will sample the image edges.")
            final_color_rgb = "AUTO"

st.divider()

# --- DATA PREP ---
data_to_process = []

if input_mode == "Links (Excel/CSV Sheet)":
    uploaded_file = st.file_uploader("Upload Sheet", type=["csv", "xlsx"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        c1, c2 = st.columns(2)
        with c1: sku_col = st.selectbox("SKU/Barcode Column", df.columns)
        with c2: url_cols = st.multiselect("Image Link Columns", [c for c in df.columns if c != sku_col])
        if url_cols:
            for _, row in df.iterrows():
                for col in url_cols:
                    data_to_process.append({"sku": str(row[sku_col]), "content": row[col], "col_name": col, "row_idx": _})

else:
    uploaded_imgs = st.file_uploader("Upload Images (No Limit)", type=["jpg", "png", "webp"], accept_multiple_files=True)
    if uploaded_imgs:
        for img_file in uploaded_imgs:
            data_to_process.append({"sku": img_file.name.split('.')[0], "content": Image.open(img_file), "col_name": "uploaded", "filename": img_file.name})

# --- EXECUTION ---
if st.button("🚀 Run Bulk Process") and data_to_process:
    pb = st.progress(0)
    st_txt = st.empty()
    total = len(data_to_process)
    
    if output_mode == "Links (Excel Sheet)":
        results_df = df.copy() if input_mode == "Links (Excel/CSV Sheet)" else pd.DataFrame([{"SKU": i['sku']} for i in data_to_process])
        
        for i, item in enumerate(data_to_process):
            st_txt.text(f"Processing Cloud Upload: {i+1}/{total}")
            try:
                # Prepare Image Source
                if isinstance(item['content'], Image.Image):
                    # For File -> Link mode, we process color locally then upload
                    current_color
