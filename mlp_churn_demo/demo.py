# -*- coding: utf-8 -*-
"""
电信用户流失预测 -- 纯 numpy 从零手写 MLP(教学版)
=====================================================
对应概念速查(本文件按此顺序组织): 

  第 1 节  数据准备      -> 特征工程, 标准化(SGD 对量纲敏感)
  第 2 节  网络定义      -> MLP: 输入层 -> 隐藏层(ReLU) -> 输出层(Sigmoid)
  第 3 节  训练循环      -> 前向传播 / 损失(交叉熵) / 反向传播 / mini-batch SGD
  第 4 节  推理预测      -> 参数冻结, 仅一次前向传播
  第 5 节  实验区        -> 改学习率/宽度, 观察收敛行为变化

运行: python3 demo.py     (仅依赖 numpy, 无任何框架)
"""

import numpy as np

np.random.seed(42)

# =====================================================================
# 第 1 节  数据准备
#   模拟 5000 个电信用户, 5 个特征(业务含义一眼可懂), 
#   内埋一条"真实规律"(模型事先不知道, 要自己学出来): 
#     网龄短 + 投诉多 + 合约临期 + 话费偏高 -> 流失风险高
#   标签按概率抽样生成 -> 自带噪声, 74% 准确率即接近上限. 
# =====================================================================
N_FEATURES = 5   # [网龄(月), 月均话费(百元), 投诉次数, 月流量(GB), 合约剩余(月)]

def make_data(n=5000):
    x = np.column_stack([
        np.random.randint(1, 72, n).astype(float),   # 网龄
        np.random.uniform(3, 30, n),                 # 月均话费
        np.random.poisson(1.5, n).astype(float),     # 投诉次数
        np.random.uniform(1, 60, n),                 # 月流量
        np.random.randint(0, 25, n).astype(float),   # 合约剩余
    ])
    risk = (0.03 * (36 - x[:, 0])       # 网龄越短越危险
          + 0.45 * x[:, 2]              # 每次投诉大幅升温
          + 0.10 * (12 - x[:, 4])       # 合约临期危险
          + 0.05 * (x[:, 1] - 15))      # 话费偏高不满
    prob = 1 / (1 + np.exp(-risk))                    # sigmoid -> 流失概率
    y = (np.random.uniform(size=n) < prob).astype(float)
    return x, y.reshape(-1, 1)

x, y = make_data()
print(f"[数据] {x.shape[0]} 个用户 * {x.shape[1]} 个特征, 流失率 {y.mean():.1%}")

# 标准化: 各列拉到均值 0, 方差 1(否则量纲大的特征主导梯度)
MU, SIGMA = x.mean(axis=0), x.std(axis=0)
x = (x - MU) / SIGMA

cut = 4000                                    # 80% 训练 / 20% 测试
x_tr, y_tr, x_te, y_te = x[:cut], y[:cut], x[cut:], y[cut:]

# =====================================================================
# 第 2 节  网络定义: MLP(5 -> H -> 1)
#   隐藏层 H 个神经元 = H 维"自动学出的特征向量"(非人工设计)
#   ReLU   引入非线性(没有它多层退化为线性)
#   Sigmoid 输出 [0,1] 概率, 与二元交叉熵成对出现
# =====================================================================
D_H = 16                                        # 隐藏层宽度(实验可改)
W1 = np.random.randn(N_FEATURES, D_H) * 0.1     # 隐藏层权重
b1 = np.zeros(D_H)                              # 隐藏层偏置
W2 = np.random.randn(D_H, 1) * 0.1              # 输出层权重
b2 = np.zeros(1)                                # 输出层偏置

relu    = lambda v: np.maximum(v, 0)
sigmoid = lambda v: 1 / (1 + np.exp(-v))
# 二元交叉熵(分类任务标准 Loss; 加 1e-9 防止 log(0))
bce = lambda p, t: -(t * np.log(p + 1e-9) + (1 - t) * np.log(1 - p + 1e-9))

# =====================================================================
# 第 3 节  训练循环: mini-batch SGD
#   每个 batch 走一遍完整闭环: 
#     前向传播 -> 算 Loss -> 反向传播(链式法则求梯度) -> 参数更新
#   数学要点: Sigmoid + BCE 组合求导后, 输出层梯度恰好 = (p - y)
# =====================================================================
LR, BATCH, EPOCHS = 0.05, 64, 60               # 学习率/批大小/轮数(均超参数)

print(f"\n[训练] MLP({N_FEATURES}->{D_H}->1)  lr={LR}  batch={BATCH}  epochs={EPOCHS}")
print(f"{'epoch':>6} {'测试Loss':>10} {'测试准确率':>10}")

for epoch in range(1, EPOCHS + 1):
    for s in np.random.permutation(cut)[::BATCH]:   # 每轮打乱后按批取
        xb, yb = x_tr[s:s + BATCH], y_tr[s:s + BATCH]

        # ---------- (1) 前向传播 ----------
        z1 = xb @ W1 + b1                # 线性组合
        h  = relu(z1)                    # 隐藏层特征 (batch * D_H)
        p  = sigmoid(h @ W2 + b2)        # 预测流失概率

        # ---------- (2) 反向传播(链式法则, 逐层相乘往回推)----------
        gz2 = p - yb                     # dL/dz2: Sigmoid+BCE 的优雅结果
        gW2 = h.T @ gz2 / len(xb)        # dL/dW2
        gb2 = gz2.mean(axis=0)           # dL/db2
        gh  = gz2 @ W2.T                 # 误差传回隐藏层
        gz1 = gh * (z1 > 0)              # 过 ReLU: 导数 0 或 1
        gW1 = xb.T @ gz1 / len(xb)       # dL/dW1
        gb1 = gz1.mean(axis=0)           # dL/db1

        # ---------- (3) 参数更新: 参数 <- 参数 - 学习率 * 梯度 ----------
        W1 -= LR * gW1;  b1 -= LR * gb1
        W2 -= LR * gW2;  b2 -= LR * gb2

    if epoch == 1 or epoch % 10 == 0:    # 定期在测试集上评估
        p_te = sigmoid(relu(x_te @ W1 + b1) @ W2 + b2)
        print(f"{epoch:>6} {bce(p_te, y_te).mean():>10.4f} {((p_te > .5) == y_te).mean():>10.2%}")

# =====================================================================
# 第 4 节  推理(在线服务化场景: 参数冻结, 仅一次前向传播)
# =====================================================================
def predict(user) -> float:
    u = (np.array(user, dtype=float) - MU) / SIGMA     # 与训练同款标准化
    return float(sigmoid(relu(u @ W1 + b1) @ W2 + b2)[0])

CASES = [
    ("新用户, 投诉2次, 无合约",   [3,  18, 2, 20,  0]),
    ("老用户, 无投诉, 长约在身", [65, 12, 0, 30, 20]),
    ("老用户, 投诉3次, 临期",   [50, 25, 3, 10,  1]),
]
print("\n[预测]")
for name, feats in CASES:
    print(f"  {name:<18} -> 流失概率 {predict(feats):.1%}")

# =====================================================================
# 第 5 节  实验区(亲手改代码观察行为, 每个都是一次原理体验)
#   - LR=2       -> Loss 震荡/发散: 学习率过大的直观体验
#   - LR=0.0001  -> 60 轮几乎没学动: 学习率过小
#   - D_H=2      -> 容量不足, 准确率上不去
#   - BATCH=4000 -> 变批量梯度下降: 每轮慢但步子稳
#   - make_data 的 risk 里加交叉项(如 0.02*x[:,2]*x[:,4])-> 看模型能否学出
# =====================================================================
print("\n[OK] 完成. 改第 3 节的 LR / 第 2 节的 D_H / 第 1 节的 risk 规律做实验. ")
