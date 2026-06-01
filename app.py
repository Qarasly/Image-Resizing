import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageStat
import requests
from io import BytesIO
import re
import zipfile
import base64
from rembg import remove

# --- 1. SECURE CONFIGURATION ---
try:
    # Pulls the secret API key from Streamlit Cloud Settings -> Secrets
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
except KeyError:
    st.error("🚨 **API Key Missing!** Please add `IMGBB_API_KEY = \"your_key_here\"` to your Streamlit Secrets vault.")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_direct_url(url):
    """Cleans URLs and converts Google Drive links for direct downloading."""
    if pd.isna(url): return url
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def detect_background_color(img):
    """Samples corners of the image to find the average edge color."""
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
    """Handles AI removal, resizing, and color padding locally."""
    # 1. AI Background Removal (Free Local Model)
    if bg_mode:
        img = remove(img)
    
    # 2. Determine Background Canvas Color
    curr_color = detect_background_color(img) if final_color_rgb == "AUTO" else final_color_rgb
    
    # 3. Resize Image (keep aspect ratio)
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    
    # 4. Create solid background canvas
    new_img = Image.new("RGB", (tw, th), curr_color)
    paste_pos = ((tw - img.size[0]) // 2, (th - img.size[1]) // 2)
    
    # 5. Paste image (uses alpha channel mask if background was removed)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        # Convert to RGBA just to be safe before masking
        img = img.convert("RGBA")
        new_img.paste(img, paste_pos, img)
    else:
        new_img.paste(img, paste_pos)
        
    return new_img

def upload_to_imgbb(img_buffer, psku):
    """Uploads to ImgBB using your secure API key."""
    url = "https://api.imgbb.com/1/upload"
    payload = {
        "key": IMGBB_API_KEY,
        "image": base64.b64encode(img_buffer.getvalue()).decode("utf-8"),
        "name": f"sku_{psku}"
    }
    res = requests.post(url, data=payload)
    res.raise_for_status()
    return res.json()["data"]["url"]

@st.cache_data(show_spinner=False)
def process_and_upload_url(src_url, psku, tw, th, final_color_rgb, bg_mode):
    """Pipeline for downloading a URL, processing, and re-uploading."""
    try:
        resp = requests.get(get_direct_url(src_url), timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
        
        proc_img = process_image_pipeline(img, tw, th, final_color_rgb, bg_mode)
        
        buf = BytesIO()
        proc_img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        
        return upload_to_imgbb(buf, psku)
    except Exception as e:
        return f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide")
st.title("🖼️ Bulk Image Resizing Pro (Unlimited)")

with st.container(border=True):
    st.subheader("⚙️ Step 1: Configuration")
    s1, s2, s3 = st.columns([3, 4, 4])
    
    with s1:
        st.write("**Dimensions**")
        target_w = st.number_input("Width (px)", min_value=10, value=660)
        target_h = st.number_input("Height (px)", min_value=10, value=900)
        st.info("💡 Recommended for NIS: 660 x 900")
    
    with s2:
        st.write("**I/O Options**")
        input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])
        output_mode = st.selectbox("Output Format", ["Links (Excel Sheet)", "Images (ZIP File)"])
        bg_mode = st.toggle("AI Background Replacement", help="Removes background using free local AI (rembg).")

    with s3:
        st.write("**Background Color**")
        color_type = st.radio("Style:", ["Standard White", "Automatic (Match Image)", "Custom Color"], horizontal=True)
        
        if color_type == "Custom Color":
            hex_color = st.color_picker("Pick color", "#FFFFFF")
            final_color_rgb = hex_to_rgb(hex_color)
        elif color_type == "Standard White":
            final_color_rgb = (255, 255, 255)
        else:
            final_color_rgb = "AUTO"

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
            psku_name = img_file.name.rsplit('.', 1)[0]
            data_to_process.append({"sku": psku_name, "content": Image.open(img_file), "col_name": "file", "type": "file"})

# --- EXECUTION ---
if st.button("🚀 Start Bulk Process") and data_to_process:
    pb = st.progress(0)
    st_txt = st.empty()
    total = len(data_to_process)
    
    if output_mode == "Links (Excel Sheet)":
        # Folder upload => clean 2 column dataframe
        if input_mode == "Local Image Files":
            results_df = pd.DataFrame(columns=["psku", "resized_link"])
        else:
            results_df = df_original.copy()
        
        for i, item in enumerate(data_to_process):
            st_txt.text(f"Processing & Uploading {i+1}/{total}: {item['sku']}")
            try:
                if item['type'] == "file":
                    proc_img = process_image_pipeline(item['content'], target_w, target_h, final_color_rgb, bg_mode)
                    buf = BytesIO()
                    proc_img.save(buf, format="JPEG", quality=90)
                    buf.seek(0)
                    res_link = upload_to_imgbb(buf, item['sku'])
                else:
                    res_link = process_and_upload_url(item['content'], item['sku'], target_w, target_h, final_color_rgb, bg_mode)
                
                # Append to dataframe
                if input_mode == "Local Image Files":
                    results_df.loc[len(results_df)] = [item['sku'], res_link]
                else:
                    results_df.at[item['row_idx'], item['col_name']] = res_link
            except Exception as e:
                st.error(f"Error on {item['sku']}: {e}")
                
            pb.progress((i + 1) / total)

        st.success("✅ Excel Sheet Ready!")
        out_excel = BytesIO()
        with pd.ExcelWriter(out_excel, engine='openpyxl') as writer:
            results_df.to_excel(writer, index=False)
        st.download_button("📥 Download Excel Results", out_excel.getvalue(), "Resized_Links.xlsx")

    else:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_f:
            for i, item in enumerate(data_to_process):
                st_txt.text(f"Processing & Zipping {i+1}/{total}: {item['sku']}")
                try:
                    if item['type'] == "file":
                        img = item['content']
                    else:
                        resp = requests.get(get_direct_url(item['content']), timeout=15)
                        img = Image.open(BytesIO(resp.content))
                    
                    proc_img = process_image_pipeline(img, target_w, target_h, final_color_rgb, bg_mode)
                    img_buf = BytesIO()
                    proc_img.save(img_buf, format="JPEG", quality=90)
                    zip_f.writestr(f"{item['sku']}.jpg", img_buf.getvalue())
                except:
                    pass
                pb.progress((i + 1) / total)
        
        st.success("✅ ZIP Completed!")
        st.download_button("📥 Download ZIP", zip_buffer.getvalue(), "resized_images.zip")
