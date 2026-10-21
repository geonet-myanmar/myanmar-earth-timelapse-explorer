"""Index maths (NumPy mirrors of the Earth Engine expressions) and the gap-fill signature."""
import numpy as np
import pytest
from app import npmath as M


def test_pseudo_reflectance_inverts_the_documented_stretch():
    # visualize(min=0.02, max=0.50, gamma=1.7): DN = 255 * ((rho - 0.02) / 0.48) ** (1 / 1.7)
    for rho in (0.02, 0.1, 0.3, 0.5):
        dn = 255 * ((rho - 0.02) / 0.48) ** (1 / 1.7)
        assert M.rho(dn) == pytest.approx(rho, abs=1e-9)


def test_gli_signs():
    assert M.gli(40, 90, 40) > 0.15          # green vegetation
    assert abs(M.gli(120, 120, 120)) < 1e-12  # grey
    assert M.gli(150, 110, 90) < 0           # bare soil


def test_lab_anchors_and_delta_e():
    L, a, b = M.lab(255, 255, 255)
    assert L == pytest.approx(100, abs=0.01) and abs(a) < 0.01 and abs(b) < 0.01
    assert M.lab(0, 0, 0)[0] == pytest.approx(0, abs=1e-6)
    assert M.delta_e([10, 120, 30], [10, 120, 30]) == pytest.approx(0)
    assert M.delta_e([255, 0, 0], [0, 0, 255]) > 150   # red vs blue: about 176


def test_collinear_flags_interpolated_years_only():
    rng = np.random.default_rng(1)
    real = rng.integers(40, 90, size=(12, 3))
    # years 3..7 replaced by a straight line between year 2 and year 8, rounded like 8-bit output
    for t in range(3, 8):
        real[t] = np.round(real[2] + (real[8] - real[2]) * (t - 2) / 6)
    f = M.linear_segment_flags(real)
    assert f[2:9].all()                      # the segment and its two anchors
    assert not f[[0, 10, 11]].any()          # noisy real years
    flat = np.tile([60, 70, 55], (5, 1))     # 1984-86 in Hpakant: identical years
    assert M.linear_segment_flags(flat).all()
