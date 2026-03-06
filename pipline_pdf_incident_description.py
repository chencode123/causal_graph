import sys
from pathlib import Path
from openai import OpenAI
import time
import utils.prompt_manager as prompt_manager

# Initialize client
client = OpenAI()

# ================================================================
# CONFIG
# ================================================================
batch_folder = Path(r"runs/test_batch/batch_1")
model_name = "gpt-5"

# load prompts
all_prompts = prompt_manager.prompts.load_all()
identify_incident_prompt = all_prompts["identify_incident"]

# ================================================================
# Pretty Colors (optional)
# ================================================================
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


# ================================================================
# FUNCTION — process one folder
# ================================================================
def process_one_case(case_folder: Path, index: int, total: int):
    print(f"\n{C.HEADER}=== [{index}/{total}] Processing: {case_folder.name} ==={C.END}")
    start_time = time.time()

    # 1. Find PDF
    pdf_files = list(case_folder.glob("*.pdf"))
    if len(pdf_files) == 0:
        print(f"{C.RED}⚠️ No PDF found in {case_folder}{C.END}")
        return
    pdf_path = pdf_files[0]

    print(f"{C.BLUE}→ Step 1/4: Uploading PDF...{C.END}")
    uploaded_pdf = client.files.create(
        file=open(pdf_path, "rb"),
        purpose="assistants",
    )
    print(f"   Uploaded file_id: {uploaded_pdf.id}")

    # 2. Build input messages
    print(f"{C.BLUE}→ Step 2/4: Preparing model input...{C.END}")
    input_messages = [
        {"role": "system", "content": [{"type": "input_text", "text": identify_incident_prompt}]},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "The document is uploaded. Please perform the identify_incident task."},
                {"type": "input_file", "file_id": uploaded_pdf.id},
            ],
        },
    ]

    # 3. Call model
    print(f"{C.BLUE}→ Step 3/4: Calling model...{C.END}")
    response = client.responses.create(
        model=model_name,
        input=input_messages,
    )
    result_text = response.output_text
    print(f"{C.GREEN}   Model response received.{C.END}")

    # 4. Save output
    print(f"{C.BLUE}→ Step 4/4: Saving result...{C.END}")
    output_path = case_folder / "identify_incident_output.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result_text)
    print(f"{C.GREEN}   Saved to: {output_path}{C.END}")

    # Time
    duration = time.time() - start_time
    print(f"{C.YELLOW}✔ Completed {case_folder.name} in {duration:.2f} sec{C.END}")


# ================================================================
# MAIN
# ================================================================
def main():
    print(f"{C.HEADER}Scanning batch folder: {batch_folder}{C.END}")

    case_folders = [child for child in batch_folder.iterdir() if child.is_dir()]
    total = len(case_folders)

    if total == 0:
        print(f"{C.RED}No case folders found.{C.END}")
        return

    print(f"{C.GREEN}Found {total} case folders. Starting processing...{C.END}")

    for idx, folder in enumerate(case_folders, start=1):
        process_one_case(folder, idx, total)

    print(f"\n{C.HEADER}=== ALL DONE: {total} cases processed ==={C.END}")


if __name__ == "__main__":
    main()
