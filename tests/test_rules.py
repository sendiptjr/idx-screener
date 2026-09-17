import pytest

from idx_screener.rules import RuleError, compile_rule, compile_rules, unknown_fields

ROW = {
    "per": 8.0, "pbv": None, "close": 100.0, "sma200": 90.0,
    "sector": "Keuangan", "industry": "Banks - Regional", "rsi14": 55.0,
    "above_sma200": True, "avg_value_20": 5e9,
}


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("per < 10", True),
        ("per > 10", False),
        ("close > sma200", True),
        ("above_sma200", True),
        ("rsi14 between 40 and 60", True),
        ("rsi14 between 60 and 80", False),
        ('sector in ["Keuangan", "Energi"]', True),
        ('sector in ["Energi"]', False),
        ('"bank" in lower(industry)', True),
        ("not (per > 20)", True),
        ("avg_value_20 > 1e9 and per < 10", True),
        ("min(per, 5) == 5", True),
    ],
)
def test_ekspresi_dasar(expression, expected):
    assert compile_rule(expression).evaluate(ROW) is expected


def test_nilai_kosong_menghasilkan_none():
    assert compile_rule("pbv < 2").evaluate(ROW) is None


def test_and_tetap_false_walau_ada_nilai_kosong():
    # Satu syarat sudah pasti salah, jadi hasilnya tidak perlu menunggu pbv.
    assert compile_rule("per > 100 and pbv < 2").evaluate(ROW) is False


def test_or_tetap_true_walau_ada_nilai_kosong():
    assert compile_rule("per < 10 or pbv < 2").evaluate(ROW) is True


def test_pembagian_nol_tidak_melempar():
    assert compile_rule("per / 0 > 1").evaluate(ROW) is None


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('ls')", "open('/etc/passwd')", "per = 5",
     "[x for x in range(3)]", "lambda: 1", "per.__class__"],
)
def test_ekspresi_berbahaya_ditolak(expression):
    with pytest.raises(RuleError):
        compile_rule(expression)


def test_metrik_asing_terdeteksi():
    rules = compile_rules(["per < 10", "entah_apa > 1"])
    assert unknown_fields(rules, set(ROW)) == {"entah_apa"}


def test_metrik_asing_saat_evaluasi_melempar():
    with pytest.raises(RuleError):
        compile_rule("tidak_ada > 1").evaluate(ROW)


def test_nan_diperlakukan_sebagai_data_kosong():
    # pandas menyimpan None numerik sebagai NaN, bukan None.
    assert compile_rule("per > 0").evaluate({**ROW, "per": float("nan")}) is None
