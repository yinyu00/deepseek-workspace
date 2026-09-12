"""程序合成音效（无需外部素材，pygame.sndarray + numpy）"""
import pygame
import numpy as np

SR = 22050  # 采样率
_sounds = {}
enabled = True
_ready = False


def _tone(freqs, dur, vol=0.3, wave="sine", decay=6.0):
    """freqs: 单频率或 (起频,止频) 扫频。返回 float ndarray"""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    if isinstance(freqs, tuple):
        f = np.linspace(freqs[0], freqs[1], n)
    else:
        f = np.full(n, float(freqs))
    phase = 2 * np.pi * np.cumsum(f) / SR
    if wave == "square":
        sig = np.sign(np.sin(phase))
    elif wave == "saw":
        sig = 2 * ((phase / (2 * np.pi)) % 1) - 1
    else:
        sig = np.sin(phase)
    env = np.exp(-decay * t)
    return sig * env * vol


def _noise(dur, vol=0.3, decay=10.0):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    rng = np.random.default_rng(7)
    return rng.uniform(-1, 1, n) * np.exp(-decay * t) * vol


def _concat(*segs):
    return np.concatenate(segs)


def _to_sound(arr):
    arr = np.clip(arr, -1, 1)
    data = (arr * 32767).astype(np.int16)
    init = pygame.mixer.get_init()
    if init and init[2] == 2:  # 立体声 mixer 需要二维数组
        data = np.column_stack([data, data])
    return pygame.sndarray.make_sound(data)


def init():
    """初始化合成音效（mixer 未就绪则静默禁用）"""
    global _ready
    if _ready:
        return True
    try:
        pygame.mixer.quit()  # 重置为合成采样率（避免变调）
        pygame.mixer.init(frequency=SR, size=-16, channels=1)
        pygame.mixer.set_num_channels(12)
    except pygame.error:
        return False
    _ready = True
    _sounds["step"] = _to_sound(_tone(180, 0.06, 0.12, "square", 20))
    _sounds["pickup"] = _to_sound(_concat(_tone(660, 0.07, 0.22), _tone(880, 0.10, 0.22)))
    _sounds["battle"] = _to_sound(_concat(_tone((160, 90), 0.25, 0.3, "saw", 4), _noise(0.15, 0.25, 8)))
    _sounds["hit"] = _to_sound(_concat(_noise(0.07, 0.35, 18), _tone(120, 0.08, 0.25, "square", 18)))
    _sounds["arrow"] = _to_sound(_tone((1400, 400), 0.12, 0.2, "sine", 6))
    _sounds["spell"] = _to_sound(_tone((400, 1700), 0.2, 0.22, "sine", 3))
    _sounds["heal"] = _to_sound(_concat(_tone(520, 0.1, 0.2), _tone(780, 0.14, 0.2)))
    _sounds["build"] = _to_sound(_tone(140, 0.15, 0.3, "square", 10))
    _sounds["coin"] = _to_sound(_concat(_tone(990, 0.05, 0.18), _tone(1320, 0.08, 0.18)))
    _sounds["win"] = _to_sound(_concat(*[_tone(f, 0.16, 0.25) for f in (523, 659, 784, 1047)]))
    _sounds["lose"] = _to_sound(_tone((400, 130), 0.7, 0.3, "saw", 2))
    return True


def play(name):
    if not enabled or not _ready:
        return
    s = _sounds.get(name)
    if s:
        s.play()


def toggle():
    global enabled
    enabled = not enabled
    return enabled
