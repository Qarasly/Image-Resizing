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
import time
import os
from google import genai

# --- 1. SECURE CONFIGURATION ---
IMGBB_API_KEY = st.secrets.get("IMGBB_API_KEY")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

if not IMGBB_API_KEY:
    st.error("🚨 **ImgBB API Key Missing!** Please add `IMGBB_API_KEY` to your Streamlit Secrets.")
    st.stop()

# --- HELPER FUNCTIONS ---
def get_direct_url(url):
    if pd.isna(url): return ""
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
    """Uploads image to ImgBB and extracts specific server errors if it fails."""
    # Pass the key in the URL directly to ensure ImgBB catches authentication
    url = f"https://api.imgbb.com/1/upload?key={IMGBB_API_KEY}"
    
    b64_img = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
    payload = {
        "image": b64_img,
        "name": str(psku)[:50] # Keep names short to prevent character limits
    }
    
    res = requests.post(url, data=payload)
    
    if not res.ok:
        # Extract the exact reason ImgBB rejected it
        error_msg = res.text
        try:
            error_msg = res.json().get("error", {}).get("message", res.text)
        except:
            pass
        raise Exception(f"ImgBB API Rejected: {error_msg}")
        
    return res.json()["data"]["url"]

def generate_product_info(img):
    if not GEMINI_API_KEY:
        return {}
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
    Analyze this product image. Provide the following information in a valid JSON object:
    {
      "product_name": "A professional and catchy name for this product",
      "product_type": "The main category (e.g., Apparel, Electronics, Home Goods, Furniture)",
      "product_subtype": "The specific sub-category (e.g., V-Neck T-Shirt, Wireless Headphones, Sofa)",
      "description": "A compelling product description ready for an e-commerce website (2-3 sentences)."
    }
    Provide accurate information. Return ONLY the raw JSON object. Do not wrap it in markdown code blocks.
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=[img, prompt])
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
            return {"error": f"AI Error: {str(e)}"}
            
    return {"error": "AI Error: Server busy after multiple retries"}

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Catalog Studio", layout="wide")

# --- EMERGENCY RECOVERY BLOCK ---
if os.path.exists("recovery_backup.csv"):
    st.error("⚠️ **Interrupted Session Detected!**")
    st.write("It looks like your previous run crashed or the page was refreshed before finishing. You can download the partially completed file below.")
    with open("recovery_backup.csv", "rb") as file:
        st.download_button(
            label="🚑 Download Emergency Backup",
            data=file,
            file_name="recovered_catalog_partial.csv",
            mime="text/csv"
        )
    st.divider()

st.title("🏭 Catalog Studio")

st.markdown("### 🛠️ Step 1: Select Your Workflow")
tool_mode = st.radio(
    "Active Mode:", 
    ["🖼️ Image Resizer Only", "✨ AI Content Generation (Includes Resizer)"],
    horizontal=True
)

use_resizer = True 
use_ai = "AI" in tool_mode

# --- CONDITIONAL UI BLOCKS ---
with st.container(border=True):
    st.subheader("⚙️ Image Resizer Configuration")
    s1, s2 = st.columns(2)
    with s1:
        target_w = st.number_input("Width (px)", min_value=10, value=660)
        target_h = st.number_input("Height (px)", min_value=10, value=900)
        bg_mode = st.toggle("AI Background Removal (rembg)", value=False, help="Isolates the product image.")
    with s2:
        st.write("**Canvas Background Fill**")
        color_type = st.radio("Style:", ["Standard White", "Automatic (Match Image)", "Custom Color"], horizontal=True)
        if color_type == "Custom Color": 
            final_color_rgb = hex_to_rgb(st.color_picker("Pick color", "#FFFFFF"))
        elif color_type == "Standard White": 
            final_color_rgb = (255, 255, 255)
        else: 
            final_color_rgb = "AUTO"

ai_liability_accepted = False
if use_ai:
    with st.container(border=True):
        st.subheader("🤖 AI Content Configuration")
        st.info("The AI will analyze the image and generate 4 columns: Name, Type, Subtype, and Description.")
        st.markdown("<h5 style='color: #d9534f;'>⚠️ Mandatory AI Liability & Accuracy Disclaimer</h5>", unsafe_allow_html=True)
        ai_liability_accepted = st.checkbox(
            "I acknowledge that AI models may produce inaccurate text. "
            "Our team accepts full responsibility for verifying the generated content before use.",
            value=False
        )

st.divider()

# --- INPUT PREPARATION ---
st.markdown("### 📂 Step 2: Upload Target Data")
i1, i2 = st.columns(2)
with i1: input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])
with i2: output_mode = st.selectbox("Output Format", ["Links (Excel Sheet)", "Images (ZIP File)"])

smart_skip = False
if input_mode == "Links (Excel/CSV Sheet)":
    smart_skip = st.toggle("⏭️ Smart Resume (Skip processed items)", value=True, help="If you re-upload a partially completed sheet, this will ignore rows that already have a Resized Link.")

data_to_process = []
df_original = None

if input_mode == "Links (Excel/CSV Sheet)":
    uploaded_file = st.file_uploader("Upload Product Target Sheet", type=["csv", "xlsx"])
    if uploaded_file:
        df_original = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        c1, c2 = st.columns(2)
        with c1: sku_col = st.selectbox("Select Target SKU Column", df_original.columns)
        with c2: url_cols = st.multiselect("Select Target URL Column(s)", [c for c in df_original.columns if c != sku_col])
        if url_cols:
            for idx, row in df_original.iterrows():
                for col in url_cols:
                    if smart_skip and "Resized Link" in df_original.columns:
                        existing_link = str(df_original.at[idx, "Resized Link"]).strip()
                        if existing_link.startswith("http"):
                            continue 
                            
                    data_to_process.append({"sku": str(row[sku_col]), "content": row[col], "col_name": col, "row_idx": idx, "type": "url"})
else:
    uploaded_imgs = st.file_uploader("Upload Target Images", type=["jpg", "png", "webp"], accept_multiple_files=True)
    if uploaded_imgs:
        for img_file in uploaded_imgs:
            data_to_process.append({"sku": img_file.name.rsplit('.', 1)[0], "content": Image.open(img_file), "col_name": "file", "type": "file"})

# --- EXECUTION LOOP ---
if st.button("🚀 Start Production Loop") and data_to_process:
    if use_ai and not ai_liability_accepted:
        st.error("🚨 Execution Blocked: You must read and check the AI Liability Disclaimer box to use content features.")
        st.stop()
        
    pb = st.progress(0)
    st_txt = st.empty()
    total = len(data_to_process)
    
    if output_mode == "Links (Excel Sheet)":
        results_df = df_original.copy() if input_mode == "Links (Excel/CSV Sheet)" else pd.DataFrame(columns=["psku"])
            
        for i, item in enumerate(data_to_process):
            st_txt.text(f"Processing Loop {i+1}/{total}: {item['sku']}")
            try:
                if item['type'] == "url":
                    link_val = str(item['content']).strip()
                    if not link_val.startswith("http"):
                        raise ValueError(f"Skipped: Not a valid URL link ('{link_val}')")
                    resp = requests.get(get_direct_url(link_val), timeout=15)
                    resp.raise_for_status()
                    raw_img = Image.open(BytesIO(resp.content))
                else:
                    raw_img = item['content']

                proc_img = process_image_pipeline(raw_img, target_w, target_h, final_color_rgb, bg_mode)
                buf = BytesIO()
                proc_img.save(buf, format="JPEG", quality=90)
                buf.seek(0)
                
                res_link = upload_to_imgbb(buf, item['sku'])
                
                target_idx = i if input_mode == "Local Image Files" else item['row_idx']
                if input_mode == "Local Image Files":
                    results_df.at[target_idx, "psku"] = item['sku']
                results_df.at[target_idx, "Resized Link"] = res_link
                
                if use_ai and GEMINI_API_KEY:
                    st_txt.text(f"🤖 Gemini analyzing product {i+1}/{total}: {item['sku']}")
                    ai_outputs = generate_product_info(proc_img)
                    
                    results_df.at[target_idx, "Generated Name"] = ai_outputs.get("product_name", "")
                    results_df.at[target_idx, "Generated Type"] = ai_outputs.get("product_type", "")
                    results_df.at[target_idx, "Generated Subtype"] = ai_outputs.get("product_subtype", "")
                    results_df.at[target_idx, "Generated Description"] = ai_outputs.get("description", "")
                    if "error" in ai_outputs:
                        results_df.at[target_idx, "AI Diagnostics"] = ai_outputs.get("error")
                            
            except Exception as e: 
                target_idx = i if input_mode == "Local Image Files" else item['row_idx']
                results_df.at[target_idx, "Resized Link"] = f"Error: {str(e)}"
            
            results_df.to_csv("recovery_backup.csv", index=False)
            pb.progress((i + 1) / total)

        if os.path.exists("recovery_backup.csv"):
            os.remove("recovery_backup.csv")
            
        st.success("✅ Automation completed successfully!")
        out_excel = BytesIO()
        with pd.ExcelWriter(out_excel, engine='openpyxl') as writer:
            results_df.to_excel(writer, index=False)
        st.download_button("📥 Download Final Results", out_excel.getvalue(), "Completed_Catalog.xlsx")

    else:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_f:
            for i, item in enumerate(data_to_process):
                st_txt.text(f"Zipping {i+1}/{total}: {item['sku']}")
                try:
                    if item['type'] == "url":
                        link_val = str(item['content']).strip()
                        if not link_val.startswith("http"):
                            raise ValueError("Invalid URL")
                        raw_img = Image.open(BytesIO(requests.get(get_direct_url(link_val), timeout=15).content))
                    else:
                        raw_img = item['content']
                    
                    proc_img = process_image_pipeline(raw_img, target_w, target_h, final_color_rgb, bg_mode)
                    img_buf = BytesIO()
                    proc_img.save(img_buf, format="JPEG", quality=90)
                    zip_f.writestr(f"{item['sku']}.jpg", img_buf.getvalue())
                    
                    if use_ai and GEMINI_API_KEY:
                        ai_outputs = generate_product_info(proc_img)
                        zip_f.writestr(f"{item['sku']}_metadata.json", json.dumps(ai_outputs, indent=4))
                except: pass
                pb.progress((i + 1) / total)
        st.success("✅ ZIP Generated!")
        st.download_button("📥 Download ZIP Package", zip_buffer.getvalue(), "processed_images.zip")
