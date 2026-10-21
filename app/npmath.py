"""NumPy mirrors of the Earth Engine maths in dataset.py (pixel profiles, calibration, tests)."""
import numpy as np


def rho(dn):
    return 0.02 + 0.48 * (np.asarray(dn, dtype=float) / 255.0) ** 1.7


def gli(r, g, b):
    R, G, B = rho(r), rho(g), rho(b)
    return (2 * G - R - B) / (2 * G + R + B)


def brightness(r, g, b):
    return (rho(r) + rho(g) + rho(b)) / 3


def lab(r, g, b):
    c = np.stack([np.asarray(v, dtype=float) / 255.0 for v in (r, g, b)])
    lin = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    R, G, B = lin
    X = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047
    Y = 0.2126729 * R + 0.7151522 * G + 0.0721750 * B
    Z = (0.0193339 * R + 0.1191920 * G + 0.9503041 * B) / 1.08883

    def f(t):
        return np.where(t <= 216 / 24389, (t * 24389 / 27 + 16) / 116, np.cbrt(t))

    fx, fy, fz = f(X), f(Y), f(Z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)])


def delta_e(rgb_a, rgb_b):
    return np.sqrt(((lab(*rgb_a) - lab(*rgb_b)) ** 2).sum(axis=0))


def collinear(prev, cur, nxt, tol=2):
    """True where (prev, cur, nxt) RGB triples lie on a line within tol DN in every band."""
    d2 = np.abs(np.asarray(nxt, dtype=int) - 2 * np.asarray(cur, dtype=int) + np.asarray(prev, dtype=int))
    return (d2 <= tol).all(axis=0)


def linear_segment_flags(series, tol=2):
    """series: (n_years, 3) DN array. Flags every year that belongs to a collinear triple."""
    s = np.asarray(series, dtype=int)
    n = len(s)
    centre = np.zeros(n, bool)
    for t in range(1, n - 1):
        centre[t] = collinear(s[t - 1], s[t], s[t + 1], tol)
    flags = centre.copy()
    flags[:-1] |= centre[1:]
    flags[1:] |= centre[:-1]
    return flags
