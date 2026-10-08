"""Turns token data into a narration script (what is shown vs. what is spoken).

Every caption word has a `show` form (screen) and a `say` form (voice), e.g.
show "4.218 %"  /  say "viertausendzweihundertachtzehn Prozent".
Markers (M("crash")) pin visual events to the start of the following word.
"""
from dataclasses import dataclass, field

from .text_de import fmt_dec, fmt_int, num_de

_UNIT_SAY = {"%": "Prozent", "$": "Dollar", "": ""}


@dataclass
class Word:
    show: str
    say: str
    marker: str | None = None
    start: float = 0.0   # global seconds, filled by timeline
    end: float = 0.0


@dataclass
class Sentence:
    words: list
    start: float = 0.0
    dur: float = 0.0
    audio: object = None  # np.ndarray at SR, filled by TTS

    @property
    def say_text(self) -> str:
        return " ".join(w.say for w in self.words if w.say)


@dataclass
class SceneScript:
    kind: str
    sentences: list
    hold: float = 0.0    # extra beat after the last sentence (let the payoff land)
    start: float = 0.0
    end: float = 0.0
    markers: dict = field(default_factory=dict)  # name -> global time


class _Marker:
    def __init__(self, name):
        self.name = name


def M(name: str) -> _Marker:
    return _Marker(name)


def N(value, unit: str = "", punct: str = "", decimals: int | None = None, sign: str = "") -> Word:
    """A number word. N(4218, '%') -> show '4.218 %', say 'viertausend... Prozent'."""
    if decimals:
        shown = fmt_dec(value, decimals)
    else:
        shown = fmt_int(value)
    show = f"{sign}{shown}" + (f" {unit}" if unit else "") + punct
    say = num_de(value if decimals else int(round(value)))
    if _UNIT_SAY.get(unit, unit):
        say += " " + _UNIT_SAY.get(unit, unit)
    return Word(show, say + punct)


def X(show: str, say: str) -> Word:
    """Word whose pronunciation differs from its spelling."""
    return Word(show, say)


def S(*parts) -> Sentence:
    words, pending = [], None
    for p in parts:
        if isinstance(p, _Marker):
            pending = p.name
            continue
        new = [Word(t, t) for t in p.split()] if isinstance(p, str) else [p]
        for w in new:
            if pending:
                w.marker, pending = pending, None
            words.append(w)
    if pending:
        raise ValueError(f"Marker '{pending}' has no following word")
    return Sentence(words)


def approx(n) -> int:
    """Round down to a speakable number: 4218 -> 4000, 1240 -> 1200, 38 -> 38."""
    n = int(n)
    if n >= 10000:
        return n // 1000 * 1000
    if n >= 1000:
        return n // 100 * 100 if n % 1000 >= 100 and n < 2000 else n // 1000 * 1000
    if n >= 200:
        return n // 100 * 100
    return n


def A(value, unit="", punct="") -> list:
    """Approximate spoken number with 'über' (only if rounding changed the value)."""
    r = approx(value)
    w = N(r, unit, punct)
    return [Word("über", "über"), w] if r != int(value) else [w]


def rug_des_tages(d: dict) -> list:
    """Script for the 'Rug-Check' format.

    Language rule (legal): only observable on-chain facts. No claims about people,
    intent or fraud. The wallet that created the token is 'Ersteller-Wallet'.
    """
    tok = d["token"]
    ticker = X(f"${tok['symbol']}.", f"{tok['say']}.")
    hh, mm = (int(x) for x in d["launch_time"].split(":"))
    launch = X(d["launch_time"], f"{num_de(hh)} Uhr {num_de(mm) if mm else ''}".strip())
    thr = d.get("prior_drop_threshold_pct", 90)
    cta = d.get("cta", {})

    end = [S(M("cta"), "Folg mir für den nächsten Fall.")]
    if cta.get("telegram"):
        end = [S(M("cta"), "Den täglichen Report gibt's auf Telegram.", "Link in Bio.")]

    return [
        SceneScript("hook", [
            S(M("num"), "Erst", *A(d["peak_gain_pct"], "%"), "Plus."),
            S(N(d["minutes_peak_to_dead"]), "Minuten später:", M("crash"), "tot."),
        ], hold=0.6),
        SceneScript("card", [
            S(M("name"), "Der Coin:", ticker),
            S(M("launch"), "Gestartet", d.get("launch_day", "gestern"), "um", launch,
              M("liq"), "mit", N(d["initial_liquidity_usd"], "$"), "Liquidität."),
        ]),
        SceneScript("chart", [
            S(M("rise"), "In", N(d["minutes_to_peak"]), "Minuten kauften", *A(d["buyers"]),
              X("Wallets.", "Wollets.")),
            S("Dann verkaufte die Ersteller-Wallet", M("dump"), "alles.", "In einer Transaktion."),
        ], hold=0.3),
        SceneScript("flags", [
            S("Diese Signale waren vorher sichtbar."),
            S(M("f1"), "Die Ersteller-Wallet hielt", N(d["dev_supply_pct"], "%"), "aller Coins."),
            S(M("f2"), N(d["bundle_wallets"]), X("Wallets", "Wollets"), "kauften im selben Block."),
            S(M("f3"), "Und", N(d["deployer_prior_rugs"]), "frühere Coins dieser Wallet:",
              "alle über", N(thr, "%"), "gefallen."),
        ], hold=0.3),
        SceneScript("loss", [
            S(M("loss"), "Verlust der Käufer:", "rund", N(d["buyer_loss_usd"], "$", ".")),
            *end,
        ]),
    ]
