
"""Minimal PyTorch + experiment-card demo.
- Trains a tiny classifier on synthetic data
- Evaluates and collects failure cases
- Builds a spec.json
- Calls gen_card.py to emit a Markdown experiment card
"""
import os, json, random, torch, torch.nn as nn, torch.utils.data as data
from experiment_logger import make_spec, save_json, generate_card_from_spec

BASE = os.path.dirname(__file__)
OUT = os.path.join(BASE, "runs")
os.makedirs(OUT, exist_ok=True)

class TinyDataset(data.Dataset):
    def __init__(self, n=200):
        xs = torch.randn(n, 2)
        # label = 1 if x0 + x1 > 0 else 0
        ys = (xs.sum(dim=1) > 0).long()
        self.x, self.y = xs, ys
    def __len__(self): return len(self.y)
    def __getitem__(self, i): return self.x[i], self.y[i]

class MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(2, 16), nn.ReLU(),
            nn.Linear(16, 2)
        )
    def forward(self, x): return self.net(x)

def train_one_run(seed=0, epochs=10, lr=1e-2):
    torch.manual_seed(seed); random.seed(seed)
    ds = TinyDataset(400)
    train, val = torch.utils.data.random_split(ds, [300, 100])
    loader = data.DataLoader(train, batch_size=32, shuffle=True)
    model = MLP()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    for _ in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()
    # eval
    model.eval()
    X = torch.stack([val[i][0] for i in range(len(val))])
    Y = torch.tensor([val[i][1].item() for i in range(len(val))])
    with torch.no_grad():
        pred = model(X).argmax(dim=1)
    acc = (pred == Y).float().mean().item()
    # collect a few failures
    failures = []
    for i in range(len(Y)):
        if pred[i] != Y[i] and len(failures) < 5:
            failures.append({
                "x": X[i].tolist(),
                "y_true": int(Y[i].item()),
                "y_pred": int(pred[i].item())
            })
    return acc, failures

if __name__ == "__main__":
    acc, failures = train_one_run(seed=42, epochs=15, lr=1e-2)
    # Build experiment card spec
    params = {
        "model": "PyTorch-MLP(2→16→2)",
        "epochs": 15,
        "optimizer": "Adam",
        "lr": 1e-2,
        "batch_size": 32,
    }
    expected = "- 验证集准确率 ≥ 0.95\n- 失败样例 ≤ 5 个，且集中在边界样本"
    meets = "达标" if acc >= 0.95 else "未达标"
    issues = "" if acc >= 0.95 else f"- 准确率仅 {acc:.3f}；需要增大容量或训练轮次"
    next_steps = "- 增大隐藏层宽度或训练轮次\n- 加入正则/早停对比\n- 固定随机种子做可复现对比"

    spec = make_spec(
        task_name="tiny_mlp_binary_classification",
        version="v001",
        purpose="验证最小可行方案（Tiny MLP）在合成数据上的基准性能",
        task_type="分类/训练",
        dataset_desc="合成二维高斯数据 400 条，随机切分 300/100",
        eval_desc="验证集准确率 + 失败样例检查",
        system_prompt="（非 LLM 实验，此处可留空）",
        user_prompt="（记录关键训练命令/参数或数据说明）",
        params=params,
        expected_criteria=expected,
        actual_outputs=failures,  # 用于卡片中的“实际输出/失败样例”
        meets_expectation=meets,
        issues=issues,
        next_steps=next_steps,
        tools_or_schema=""
    )
    spec_path = os.path.join(OUT, "spec.json")
    save_json(spec, spec_path)
    # 触发生成卡片
    gen_script = os.path.join(BASE, "gen_card.py")
    card_path = generate_card_from_spec(spec_path, os.path.join(OUT, "cards"), gen_script)
    print("Card written to:", card_path)
