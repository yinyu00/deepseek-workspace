"""素材加载器：assets/*.png 缩放缓存；缺图回退 None（调用方画占位图形）"""
import os
import pygame

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_cache = {}


def get(key, size):
    """按 key 取缩放后的 Surface（带缓存）；无文件返回 None"""
    ck = (key, size)
    if ck in _cache:
        return _cache[ck]
    path = os.path.join(_DIR, key + ".png")
    if not os.path.exists(path):
        _cache[ck] = None
        return None
    try:
        img = pygame.image.load(path)
        try:
            img = img.convert_alpha()
        except pygame.error:
            pass  # display 未初始化时保持原样
        old = img.get_size()
        m = max(old[0], old[1])
        if m != size:
            img = pygame.transform.scale(img, (size, size))  # 邻近缩放保持像素风
        _cache[ck] = img
        return img
    except pygame.error:
        _cache[ck] = None
        return None


def available():
    return [f[:-4] for f in os.listdir(_DIR) if f.endswith(".png")]
