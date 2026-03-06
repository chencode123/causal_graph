import re
import unicodedata
from pathlib import Path

def create_sanitized_folder(name: str, content: str = None, base_dir: str = ".", replacement: str = "_") -> Path:
    """
    Sanitize a string and create a corresponding safe-named folder.
    Optionally save provided text content (e.g., model output) as a .txt file inside.

    Args:
        name (str): Original folder name (may contain illegal characters).
        content (str, optional): Text content to save (e.g., model output). Default is None.
        base_dir (str): Parent directory where the folder should be created.
        replacement (str): Replacement character for illegal characters.

    Returns:
        Path: Path object of the created (or existing) folder.
    """
    # Normalize unicode (e.g., remove accents)
    sanitized = unicodedata.normalize("NFKD", name)

    # Replace illegal characters
    sanitized = re.sub(r'[\\/*?:"<>|]', replacement, sanitized)

    # Remove control characters and extra spaces
    sanitized = re.sub(r"[\r\n\t ]+", replacement, sanitized).strip(replacement)

    # Keep only safe ASCII characters
    sanitized = re.sub(r"[^A-Za-z0-9._-]", replacement, sanitized)

    # Avoid consecutive underscores
    sanitized = re.sub(r"__+", "_", sanitized)

    # Truncate to safe length
    sanitized = sanitized[:100]

    # Build full path and create folder
    folder_path = Path(base_dir) / sanitized
    folder_path.mkdir(parents=True, exist_ok=True)
    print(f"📁 Folder created (safe name): {folder_path}")

    # If content provided, save it as a txt file
    if content:
        txt_path = folder_path / f"identify_name_output.txt"
        txt_path.write_text(content, encoding="utf-8")
        print(f"📝 Saved content to: {txt_path}")

    return folder_path
