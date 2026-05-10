import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps, ImageStat
import requests
from io import BytesIO
import re

# --- 1. CONFIGURATION ---
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

def get_direct_url(url):
    """Clean the URL and convert Google Drive sharing links."""
    if pd.isna(url): return url
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def detect_background_color(img):
    """Detects the average color at the edges of the image."""
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    corners = [img.crop((0,0,5,5)), img.crop((w-5,0,w,5)), img.crop((0,h-5,5,h)), img.crop((w-5,h-5,w,h))]
    r, g, b = 0, 0, 0
    for corner in corners:
        stat = ImageStat.Stat(corner)
        r += stat.mean[0]; g += stat.mean[1]; b += stat.mean[2]
    return (int(r/4), int(g/4), int(b/4))

@st.cache_data(show_spinner=False)
def cached_process_upload(image_url, psku, suffix, main_mode, color_choice):
    try:
        if pd.isna(image_url) or str(image_url).strip().lower() in ["", "nan", "none"]:
            return "No Link"
            
        direct_url = get_direct_url(image_url)
        clean_suffix = "".join(filter(str.isalnum, suffix))
        
        # --- MODE 1: FULL AI REPLACEMENT ---
        if main_mode == "Background Replacement (AI)":
            bg_hex = "white" if color_choice == "White" else "black"
            upload_result = cloudinary.uploader.upload(
                direct_url, 
                public_id = f"sku_{psku}_{clean_suffix}",
                folder = "team_uploads",
                overwrite = True,
                background_removal = "cloudinary_ai", # Requires Cloudinary AI Add-on
                transformation = [
                    {"width": 660, "height": 900, "crop": "pad", "background": bg_hex}
                ]
            )
            return upload_result.get("secure_url")

        # --- MODE 2: BACKGROUND FILL (PADDING) ---
        else:
            response = requests.get(direct_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            img = Image.open(BytesIO(response.content))
            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            
            # Color Logic
            if color_choice == "Automatic":
                final_bg = detect_background_color(img)
            elif color_choice == "White":
                final_bg = (255, 255, 255)
            else:
                final_bg = (0, 0, 0)
                
            img.thumbnail((660, 900), Image.Resampling.LANCZOS)
            new_img = Image.new("RGB", (660, 900), final_bg)
            paste_pos = ((660 - img.size[0]) // 2, (900 - img.size[1]) // 2)
            new_img.paste(img, paste_pos)
            
            buf = BytesIO()
            new_img.save(buf, format="JPEG", quality=90)
            buf.seek(0)
            
            upload_result = cloudinary.uploader.upload(buf, public_id=f"sku_{psku}_{clean_suffix}", folder="team_uploads", overwrite=True)
            return upload_result.get("secure_url")

    except Exception as e:
        return f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide")
st.title("🖼️ Bulk Image Resizing")

uploaded_file = st.file_uploader("Upload product sheet", type=["csv", "xlsx"])

if uploaded_file:
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    
    st.subheader("Configuration")
    c1, c2 = st.columns(2)
    with c1:
        sku_col = st.selectbox("SKU Column", df.columns)
        url_cols = st.multiselect("Image Link Column(s)", [c for c in df.columns if c != sku_col])
    with c2:
        main_mode = st.radio("Processing Mode", ["Background Fill (Padding)", "Background Replacement (AI)"])
        
        color_options = ["White", "Black", "Automatic"] if main_mode == "Background Fill (Padding)" else ["White", "Black"]
        color_choice = st.selectbox("Target Color", color_options)

    if st.button("🚀 Start Bulk Processing"):
        if not url_cols:
            st.error("Select image columns first.")
        else:
            df_res = df.copy()
            pb = st.progress(0)
            st_txt = st.empty()
            total = len(df) * len(url_cols); count = 0
            
            for url_col in url_cols:
                links = []
                for i, row in df.iterrows():
                    count += 1
                    st_txt.markdown(f"**Processing {count}/{total}:** SKU `{row[sku_col]}`")
                    pb.progress(count / total)
                    links.append(cached_process_upload(row[url_col], row[sku_col], url_col, main_mode, color_choice))
                df_res[url_col] = links

            st.success("✅ Done!")
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Original Links', index=False)
                df_res.to_excel(writer, sheet_name='Resized Links', index=False)
            
            st.download_button("📥 Download Results", output.getvalue(), f"Resized_{color_choice}.xlsx")
