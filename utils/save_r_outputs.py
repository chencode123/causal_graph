import os

def save_r_outputs(save_dir, **kwargs):
    os.makedirs(save_dir, exist_ok=True)
    for name, content in kwargs.items():
        output_path = os.path.join(save_dir, f"{name}.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ saved to {output_path}")
