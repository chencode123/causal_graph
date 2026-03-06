import sys
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
client = OpenAI()

import time
from pathlib import Path
from tqdm import tqdm

# === Custom modules ===
import utils.prompt_manager as prompt_manager
import utils.pdf_to_text as pdf_to_text
import model.model as model

# === Global ===
model_name = "gpt-5"    # 建议这样写
base_dir = Path("runs/test_batch")  # 你的 batch 根目录

# === Load prompts ===
print("⚙️ Loading prompts...")
all_prompts = prompt_manager.prompts.load_all()
identify_incident_prompt = all_prompts["identify_incident"]
print("✅ Loaded identify_incident prompt.\n")


def process_single_pdf(pdf_path: Path):
    """对单个 PDF 执行 identify_incident，并将输出保存到同目录"""
    print(f"\n📘 Processing: {pdf_path}")

    # 提取文本
    report_text = pdf_to_text.pdf_to_text(str(pdf_path))
    if not report_text.strip():
        print(f"⚠️ Skipped empty PDF: {pdf_path}")
        return

    # 调用 identify_incident
    try:
        output = model.run_prompt(
            prompt=identify_incident_prompt,
            variables={"report_text": report_text},
            output_dir=None,                 # 不创建文件夹
            model_name=model_name,
            prompt_key="identify_incident"
        )

        # === 保存到同目录 ===
        output_path = pdf_path.parent / "identify_incident_output.txt"
        output_path.write_text(output, encoding="utf-8")

        print(f"💾 Saved: {output_path}")

        time.sleep(2)  # 限制请求速率，避免被限流

    except Exception as e:
        print(f"❌ Error processing {pdf_path}: {e}")


def run_batch():
    print(f"📚 Searching for PDFs under: {base_dir}")

    pdf_list = list(base_dir.rglob("*.pdf"))
    print(f"🔍 Found {len(pdf_list)} PDF files.\n")

    for pdf_path in tqdm(pdf_list, desc="Running identify_incident"):
        process_single_pdf(pdf_path)
        time.sleep(1)

    print("\n All PDFs processed!\n")


if __name__ == "__main__":
    run_batch()
