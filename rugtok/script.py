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
    if n >= 100000:
        return n // 10000 * 10000
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


def MIN(n, punct: str = "", dat: bool = False) -> list:
    """'3 Minuten' / '1 Minute' / 'in einer Minute' with correct German grammar."""
    n = int(round(n))
    if n == 1:
        return [Word("1", "einer" if dat else "eine"), Word("Minute" + punct, "Minute" + punct)]
    return [N(n), Word("Minuten" + punct, "Minuten" + punct)]


def flag_specs(d: dict) -> list:
    """Red flags from data: each -> dict(marker, sentence, big, small).
    Only kinds the data pipeline can actually prove are supported."""
    out = []
    for i, f in enumerate(d.get("flags", [])[:3]):
        mk, k = f"f{i + 1}", f["kind"]
        if k == "creator_hold":
            p = f["pct"]
            sen = S(M(mk), "Die Ersteller-Wallet hielt", N(p, "%"), "aller Coins.")
            big, small = f"{fmt_int(p)} % in Ersteller-Wallet", "Anteil am Gesamt-Supply beim Start"
        elif k == "bundle":
            w, sec = f["wallets"], f.get("window_s", 5)
            sen = S(M(mk), N(w), X("Wallets", "Wollets"), "kauften gebündelt in den ersten",
                    N(sec), "Sekunden.")
            big = f"{fmt_int(w)} Wallets in {sec} Sekunden"
            small = "gebündelte Käufe direkt nach dem Start"
        elif k == "prior":
            bad, tot, thr = f["bad"], f["total"], f.get("threshold_pct", 90)
            if bad == tot:
                sen = S(M(mk), "Und", N(bad), "frühere Coins dieser Wallet:", "alle über",
                        N(thr, "%"), "gefallen.")
                big = f"{fmt_int(bad)} frühere Coins abgestürzt"
            else:
                sen = S(M(mk), "Und", N(bad), "von", N(tot), "früheren Coins dieser Wallet:",
                        "über", N(thr, "%"), "gefallen.")
                big = f"{fmt_int(bad)} von {fmt_int(tot)} früheren Coins"
            small = f"jeweils über −{thr} % vom Hoch"
        else:
            raise ValueError(f"unknown flag kind: {k}")
        out.append({"marker": mk, "sentence": sen, "big": big, "small": small})
    return out


def rug_des_tages(d: dict) -> list:
    """Script for the 'Rug-Check' format.

    Language rule (legal): only observable on-chain facts. No claims about people,
    intent or fraud. The wallet that created the token is 'Ersteller-Wallet'.
    Every sentence that depends on a fact only appears if the data proves it.
    """
    tok = d["token"]
    ticker = X(f"${tok['symbol']}.", f"{tok['say']}.")
    hh, mm = (int(x) for x in d["launch_time"].split(":"))
    launch = X(f"{d['launch_time']}.", f"{num_de(hh)} Uhr {num_de(mm) if mm else ''}".strip() + ".")
    cta = d.get("cta", {})
    crash = d.get("crash", {})

    end = [S(M("cta"), "Folg mir für den nächsten Fall.")]
    if cta.get("telegram"):
        end = [S(M("cta"), "Den täglichen Report gibt's auf Telegram.", "Link in Bio.")]

    if crash.get("by_creator") and crash.get("sold_all"):
        dump = [S("Dann verkaufte die Ersteller-Wallet", M("dump"), "alles.")]
        if crash.get("single_tx"):
            dump.append(S("In einer Transaktion."))
    else:
        dump = [S("Dann", M("dump"), "fiel der Kurs um", N(int(d["drawdown_pct"]), "%"),
                  "in", *MIN(d["minutes_peak_to_dead"], ".", dat=True))]

    flags = flag_specs(d)
    scenes = [
        SceneScript("hook", [
            S(M("num"), "Erst", *A(d["peak_gain_pct"], "%"), "Plus."),
            S(*MIN(d["minutes_peak_to_dead"]), "später:", M("crash"), "tot."),
        ], hold=0.6),
        SceneScript("card", [
            S(M("name"), "Der Coin:", ticker),
            S(M("launch"), "Gestartet", d.get("launch_day", "gestern"), "um", launch),
            S(M("liq"), "Höchster Marktwert:", *A(d["peak_market_cap_usd"], "$", ".")),
        ]),
        SceneScript("chart", [
            S(M("rise"), "In", *MIN(d["minutes_to_peak"], dat=True), "kauften",
              *(["mehr als", N(approx(d["buyers"]))] if d.get("buyers_is_lower_bound")
                else A(d["buyers"])),
              X("Wallets.", "Wollets.")),
            *dump,
        ], hold=0.3),
    ]
    if flags:
        scenes.append(SceneScript("flags", [S("Diese Signale waren vorher sichtbar.")]
                                  + [f["sentence"] for f in flags], hold=0.3))
    loss_words = ["Verlust der Käufer:", "mindestens" if d.get("loss_is_lower_bound") else "rund"]
    scenes.append(SceneScript("loss", [
        S(M("loss"), *loss_words, N(d["buyer_loss_usd"], "$", ".")),
        *end,
    ]))
    return scenes
