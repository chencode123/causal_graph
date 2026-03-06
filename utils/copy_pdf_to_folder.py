import shutil
from pathlib import Path

def copy_pdf_to_folder(pdf_path: str, folder_path: Path) -> Path:
    """
    Copy a PDF file into the target folder with its original filename.

    Args:
        pdf_path (str): Path to the source PDF file.
        folder_path (Path): Destination folder (Path object).

    Returns:
        Path: Full path of the copied PDF file.
    """
    pdf_path = Path(pdf_path)
    folder_path = Path(folder_path)

    # Ensure source PDF exists
    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")

    # Ensure destination folder exists
    folder_path.mkdir(parents=True, exist_ok=True)

    # Keep original filename
    destination = folder_path / pdf_path.name

    # Copy file (overwrite if already exists)
    shutil.copy2(pdf_path, destination)

    print(f"📄 Copied PDF to: {destination}")
    return destination
