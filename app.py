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

def process_image_locally(img, target_w, target_h, color_choice):
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    if color_choice == "Automatic": bg = detect_background_color(img)
    elif color_choice == "White": bg = (255, 255, 255)
    else: bg = (0, 0, 0)
    
    img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", (target_w, target_h), bg)
    paste_pos = ((target_w - img.size[0]) // 2, (target_h - img.size[1]) // 2)
    new_img.paste(img, paste_pos)
    return new_img

@st.cache_data(show_spinner=False)
def cloud_upload_logic(image_url, psku, suffix, main_mode, color_choice, tw, th):
    try:
        direct_url = get_direct_url(image_url)
        clean_suffix = "".join(filter(str.isalnum, suffix))
        
        # Determine background for Cloudinary transformation
        bg_hex = "white" if color_choice == "White" else ("black" if color_choice == "Black" else "auto")
        
        # Transformation Settings
        xform = [{"width": tw, "height": th, "crop": "pad", "background": bg_hex}]
        
        params = {
            "public_id": f"sku_{psku}_{clean_suffix}",
            "folder": "team_uploads",
            "overwrite": True,
            "transformation": xform
        }
        
        if main_mode == "Background Replacement (AI)":
            params["background_removal"] = "cloudinary_ai"

        res = cloudinary.uploader.upload(direct_url, **params)
        return res.get("secure_url")
    except Exception as e: return f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide")

st.title("🖼️ Bulk Image Resizing Pro")

# Settings Panel
with st.expander("⚙️ Processing & Dimension Settings", expanded=True):
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("**1. Dimensions**")
        target_w = st.number_input("Width (px)", value=660)
        target_h = st.number_input("Height (px)", value=900)
        st.info("💡 Recommended for NIS: **660 x 900**")
    with s2:
        st.markdown("**2. Method**")
        main_mode = st.radio("Strategy", ["Background Fill (Padding)", "Background Replacement (AI)"], help="AI Replacement removes the original background entirely.")
    with s3:
        st.markdown("**3. Color**")
        color_opts = ["White", "Black", "Automatic"] if main_mode == "Background Fill (Padding)" else ["White", "Black"]
        color_choice = st.selectbox("Background Fill Color", color_opts)

st.divider()

# Input Method Toggle
input_type = st.radio("Select Input Source:", ["Excel/CSV Sheet (Generates Links)", "Multiple Image Files (Generates ZIP)"], horizontal=True)

if input_type == "Excel/CSV Sheet (Generates Links)":
    uploaded_file = st.file_uploader("Upload Sheet", type=["csv", "xlsx"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        st.caption(f"Loaded {len(df)} rows.")
        
        c1, c2 = st.columns(2)
        with c1: sku_col = st.selectbox("SKU/Barcode Column", df.columns)
        with c2: url_cols = st.multiselect("Select Image URL Columns", [c for c in df.columns if c != sku_col])
        
        if st.button("🚀 Process & Generate Links") and url_cols:
            df_res = df.copy()
            total_tasks = len(df) * len(url_cols)
            pb = st.progress(0); st_txt = st.empty(); count = 0
            
            for url_col in url_cols:
                links = []
                for i, row in df.iterrows():
                    count += 1
                    st_txt.text(f"Processing Image {count}/{total_tasks}...")
                    pb.progress(count / total_tasks)
                    links.append(cloud_upload_logic(row[url_col], row[sku_col], url_col, main_mode, color_choice, target_w, target_h))
                df_res[url_col] = links
            
            st.success("✅ Sheet Processing Complete!")
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name="Original", index=False)
                df_res.to_excel(writer, sheet_name="Resized Links", index=False)
            st.download_button("📥 Download Result Excel", output.getvalue(), "Resized_Catalog.xlsx")

else:
    # --- UNLIMITED IMAGE UPLOADER ---
    uploaded_imgs = st.file_uploader("Drop images here (Unlimited)", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    if uploaded_imgs:
        if st.button(f"🚀 Process {len(uploaded_imgs)} Images"):
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                pb = st.progress(0); st_txt = st.empty()
                for i, img_file in enumerate(uploaded_imgs):
                    st_txt.text(f"Resizing {img_file.name}...")
                    img = Image.open(img_file)
                    processed = process_image_locally(img, target_w, target_h, color_choice)
                    
                    buf = BytesIO()
                    processed.save(buf, format="JPEG", quality=90)
                    zip_file.writestr(f"resized_{img_file.name}", buf.getvalue())
                    pb.progress((i + 1) / len(uploaded_imgs))
            
            st.success(f"✅ Finished! {len(uploaded_imgs)} images ready.")
            st.download_button("📥 Download Resized ZIP", zip_buffer.getvalue(), "Bulk_Resized_Images.zip")
