import os

def load_r_outputs(save_dir):

    outputs = {}
    for file_name in os.listdir(save_dir):
        if file_name.endswith(".txt"):
            name = os.path.splitext(file_name)[0]  # 去掉 .txt
            file_path = os.path.join(save_dir, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                outputs[name] = f.read()
            print(f"📂 loaded {file_name}")

    print(f"\n✅ Loaded {len(outputs)} files from: {save_dir}")
    return outputs
