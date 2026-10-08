"""German number formatting (for screen) and number-to-words (for the voice)."""
import re

_UNITS = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
          "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
          "achtzehn", "neunzehn"]
_TENS = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig", 6: "sechzig", 7: "siebzig",
         8: "achtzig", 9: "neunzig"}


def _below100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    t, u = divmod(n, 10)
    if u == 0:
        return _TENS[t]
    return ("ein" if u == 1 else _UNITS[u]) + "und" + _TENS[t]


def _below1000(n: int) -> str:
    h, r = divmod(n, 100)
    out = ""
    if h:
        out = ("" if h == 1 else _UNITS[h]) + "hundert"
    if r:
        out += _below100(r)
    return out


def _lead(n: int) -> str:
    """Number used as a multiplier in front of 'tausend'/'hundert': 1 -> 'ein'."""
    s = _below1000(n)
    return "" if s == "eins" else s


def num_de(n) -> str:
    """Integer or float -> spoken German. 4218 -> 'viertausendzweihundertachtzehn'."""
    if isinstance(n, float) and not n.is_integer():
        whole, frac = f"{n:.10g}".split(".")
        return num_de(int(whole)) + " Komma " + " ".join(_UNITS[int(c)] for c in frac)
    n = int(n)
    if n < 0:
        return "minus " + num_de(-n)
    if n == 0:
        return "null"
    parts = []
    mil, rest = divmod(n, 1_000_000)
    if mil:
        parts.append("eine Million" if mil == 1 else f"{_below1000(mil)} Millionen")
    th, rest = divmod(rest, 1000)
    word = ""
    if th:
        word += _lead(th) + "tausend"
    if rest:
        word += _below1000(rest)
    if word:
        parts.append(word)
    return " ".join(parts)


def fmt_int(n) -> str:
    """4218 -> '4.218' (German thousands separator)."""
    return f"{int(round(n)):,}".replace(",", ".")


def fmt_dec(x: float, digits: int = 1) -> str:
    """99.7 -> '99,7'."""
    return f"{x:.{digits}f}".replace(".", ",")


def fmt_usd(n) -> str:
    return f"{fmt_int(n)} $"


_VOWELS = re.compile(r"[aeiouyäöü]+", re.IGNORECASE)


def syllables(text: str) -> int:
    """Rough German syllable count (vowel groups). Good enough for timing weights."""
    return max(1, len(_VOWELS.findall(text)))
