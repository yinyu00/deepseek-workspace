# -*- coding: utf-8 -*-
"""
SVM 最小可视化示例：三种核函数对比
生成「月亮形」两组数据 → 分别用 线性核 / RBF核 / 多项式核 分类
→ 画出决策边界和支持向量，直观看到「最宽隔离带」
运行：python3 svm_demo.py  （生成 svm_demo.png）
"""
import numpy as np
import matplotlib.pyplot as plt
from sklearn.svm import SVC
from sklearn.datasets import make_moons
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# ---------- 1. 造数据：两弯「月亮」，线性不可分 ----------
X, y = make_moons(n_samples=200, noise=0.15, random_state=42)

# 特征工程第一步：标准化（SVM 对尺度敏感，必做！）
X = StandardScaler().fit_transform(X)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42
)

# ---------- 2. 训练三个 SVM：不同核函数 ----------
kernels = {
    "linear": SVC(kernel="linear", C=1.0),        # 线性核：找直线分开
    "rbf":    SVC(kernel="rbf", C=1.0, gamma="scale"),  # 高斯核：弯着分（默认首选）
    "poly":   SVC(kernel="poly", degree=3, C=1.0), # 多项式核：三次曲线
}

# ---------- 3. 可视化：决策边界 + 支持向量 ----------
fig, axes = plt.subplots(1, 3, figsize=(16, 5))

for ax, (name, model) in zip(axes, kernels.items()):
    model.fit(X_train, y_train)
    acc = accuracy_score(y_test, model.predict(X_test))

    # 生成网格，对每个点预测类别 → 涂色形成边界区域
    xx, yy = np.meshgrid(np.linspace(-3, 3, 300), np.linspace(-3, 3, 300))
    Z = model.predict(np.c_[xx.ravel(), yy.ravel()]).reshape(xx.shape)
    ax.contourf(xx, yy, Z, alpha=0.15, cmap="coolwarm")

    # 训练点：两类不同颜色
    ax.scatter(X_train[:, 0], X_train[:, 1], c=y_train,
               cmap="coolwarm", s=25, edgecolors="k", linewidths=0.4)

    # ⭐ 支持向量：圈出来（决定边界位置的关键点）
    ax.scatter(model.support_vectors_[:, 0], model.support_vectors_[:, 1],
               s=160, facecolors="none", edgecolors="lime", linewidths=1.8,
               label=f"支持向量 ×{len(model.support_vectors_)}")

    ax.set_title(f"kernel = {name}  |  测试准确率 {acc:.1%}", fontsize=12)
    ax.legend(loc="upper right", fontsize=9)

plt.suptitle("SVM 三种核函数对比：背景色=决策区域，绿圈=支持向量", fontsize=13)
plt.tight_layout()
plt.savefig("svm_demo.png", dpi=130, bbox_inches="tight")
print("已保存 svm_demo.png")

# ---------- 4. 打印对比结论 ----------
for name, m in kernels.items():
    print(f"{name:7s} 核 | 支持向量 {len(m.support_vectors_):3d} 个 | "
          f"测试准确率 {accuracy_score(y_test, m.predict(X_test)):.1%}")
