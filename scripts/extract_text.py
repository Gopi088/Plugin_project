import os
from pdfminer.high_level import extract_text
from docx import Document
import textract

# -------------------------
# DOCX TEXT EXTRACTOR
# -------------------------

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    text = []

    for para in doc.paragraphs:
        text.append(para.text)

    return "\n".join(text)

def extract_text_from_doc(file_path):
    text = textract.process(file_path)
    return text.decode("utf-8")

# -------------------------
# PATH SETUP
# -------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

input_folder = "/mnt/c/Users/Gopi Gedar/Desktop/resume"
output_folder = os.path.join(BASE_DIR, "dataset", "text")

os.makedirs(output_folder, exist_ok=True)

# -------------------------
# MAIN LOOP
# -------------------------

for file in os.listdir(input_folder):

    file_path = os.path.join(input_folder, file)

    try:

        # PDF
        if file.endswith(".pdf"):
            text = extract_text(file_path)

        # DOCX
        elif file.endswith(".docx"):
            try:
                text = extract_text_from_docx(file_path)
            except:
                print(f"❌ Corrupted DOCX skipped: {file}")
                continue

        # SKIP DOC FILES (IMPORTANT)
        elif file.endswith(".doc"):
            print(f"⚠️ Skipped .doc file: {file}")
            continue

        else:
            print(f"⚠️ Unsupported file: {file}")
            continue

        txt_name = file.rsplit(".", 1)[0] + ".txt"
        txt_path = os.path.join(output_folder, txt_name)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        print("✅ Converted:", file)

    except Exception as e:
        print(f"❌ Failed:", file)
        print("Error:", e)

    file_path = os.path.join(input_folder, file)

    # 🔥 PDF
    if file.endswith(".pdf"):
        text = extract_text(file_path)

    # 🔥 DOCX
    elif file.endswith(".docx"):
        text = extract_text_from_docx(file_path)

    elif file.endswith(".doc"):
        text = extract_text_from_doc(file_path)    

    else:
        print(f"Skipped (unsupported): {file}")
        continue

    txt_name = file.rsplit(".", 1)[0] + ".txt"
    txt_path = os.path.join(output_folder, txt_name)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    print("Converted:", file)

print("\n✅ All resumes converted successfully")