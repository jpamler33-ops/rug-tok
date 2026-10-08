# rug-tok – „Rug-Check“: tägliches TikTok-Video aus echten Solana-Daten

Jeden Morgen automatisch:

1. **Fall finden** (`fetch_case.py`): sucht unter den Solana-Tokens der letzten 36 h den auffälligsten Crash
   (mind. +300 % Anstieg, dann mind. −90 % innerhalb von 60 Minuten, ≥ 100 Käufer-Wallets).
2. **Video bauen** (`build.py`): 1080×1920, ~30–35 s, Stimme, Untertitel, Chart, Sounddesign.
3. **Aufs Handy schicken** (`deliver.py`): Video + fertiger Post-Text per Telegram-Bot.
   Du postest es auf TikTok mit ein paar Taps (siehe „Warum nicht automatisch auf TikTok?“).

Kein LLM im Betrieb → **null Claude/ChatGPT-Kontingent pro Video**.

## Einrichten (einmalig, ~20 Minuten)

1. **API-Key holen:** Account bei [Solana Tracker](https://www.solanatracker.io) → Data API Key.
   Free-Plan: 10.000 Requests/Monat, 3 Requests/s. Ein Lauf braucht ~20–40 Requests.
2. **Telegram-Bot:** In Telegram `@BotFather` → `/newbot` → Token kopieren.
   Dann dem Bot einmal „hi“ schreiben und deine Chat-ID über `@userinfobot` holen.
3. **GitHub:** Neues **privates** Repo anlegen, diesen Ordner hochladen.
   Unter *Settings → Secrets and variables → Actions* anlegen:
   - Secret `SOLANATRACKER_API_KEY`
   - Secret `TELEGRAM_BOT_TOKEN`, Secret `TELEGRAM_CHAT_ID`
   - optional Variable `RUGTOK_TELEGRAM_CTA` = `1` (Video endet mit „Telegram, Link in Bio“)
4. **Testlauf:** *Actions → Daily Rug-Check video → Run workflow*. Danach läuft es täglich um 07:47 (Sommerzeit).

**Niemals** Keys in den Chat, in Code oder in Dateien schreiben – nur als GitHub-Secret.

## Lokal ausführen

```bash
pip install -r requirements.txt      # Python 3.10+, ffmpeg im PATH
bash scripts/setup_piper.sh          # Offline-Ersatzstimme, falls edge-tts nicht geht
export SOLANATRACKER_API_KEY=...
python3 fetch_case.py                # -> content/<datum>_<SYMBOL>.json
python3 build.py content/<datei>.json   # -> out/<datei>.mp4 + _beschreibung.txt
python3 build.py content/demo_rug.json  # Demo ohne API (mit Wasserzeichen)
```

`build.py --stills 1,5.2,16` rendert nur Standbilder zum schnellen Prüfen, `--tts piper|edge`,
`--no-music` (wenn du in der App einen Trend-Sound drunterlegst).

## Was das Video sagt – und was nicht

Jede Aussage stammt aus der API und wird nur gesagt, wenn die Daten sie belegen:

| Aussage | Quelle | Wenn nicht belegt |
|---|---|---|
| +X % / −Y % / Minuten | 1-Minuten- bzw. Sekunden-Kerzen (`/chart`) | Fall wird verworfen |
| „Ersteller-Wallet verkaufte alles“ | PnL-API: Ersteller-Wallet hat Bestand 0, letzter Trade ±3 min um das Hoch | stattdessen „Kurs fiel um Y % in Z Minuten“ |
| „N Wallets gebündelt beim Start“ | `/tokens/{mint}/bundlers` (Erkennung von Solana Tracker) | Signal entfällt |
| „X von Y früheren Coins dieser Wallet über 90 % gefallen“ | `/deployer` + ATH je Token (max. 8 geprüft) | Signal entfällt |
| Verlust der Käufer | Summe negativer PnL aller Käufer-Wallets ohne Ersteller | „mindestens“, wenn nicht alle Wallets geladen wurden |

Sprachregel: nur beobachtbare On-Chain-Fakten, keine Personen, keine Absicht („Betrug“, „Scam“) unterstellen.
Das senkt das Risiko, **ersetzt aber keine Prüfung durch einen Anwalt** vor dem echten Betrieb.

Jede API-Antwort wird unter `data/raw/<lauf>/` archiviert (Beweissicherung), der Post-Text enthält
Contract-Adresse, Quellen-Links und die Berechnungsmethode.

## Warum nicht automatisch auf TikTok?

TikToks Content-Posting-API veröffentlicht für nicht geprüfte Apps nur **privat**. Öffentliches
Auto-Posten braucht entweder TikToks App-Audit oder einen kostenpflichtigen Dienst mit geprüfter App.
Erst lohnt es sich zu sehen, ob die Videos Views bringen – dann automatisieren.

## Tests

```bash
python3 tests/test_data.py    # echte Videos ohne Belege/mit unstimmigen Zahlen werden blockiert
python3 tests/test_fetch.py   # Fall-Auswahl, Verlust, Ersteller-Verkauf, Retry, Budget – offline mit Fixtures
```

## Stand / bekannte Grenzen

- **Gegen die echte API noch nicht gelaufen** (aus der Entwicklungsumgebung kein Zugriff). Die Feldnamen
  stammen aus der offiziellen Doku; die Tests nutzen nachgebaute Antworten. Erster echter Lauf: Ausgabe
  prüfen, bei Abweichungen liegen die Rohantworten in `data/raw/`.
- Pagination der PnL-Trader-Liste ist in der Doku nicht beschrieben → wenn nur eine Seite kommt,
  steht im Video „mindestens“.
- edge-tts (bessere Stimme) ist geschrieben, aber nicht getestet; Fallback ist die Offline-Stimme Piper.
- Wort-Timings der Untertitel sind geschätzt, nicht exakt ausgerichtet.

## Aufbau

```
fetch_case.py        Fall finden -> content/*.json (validiert)
build.py             Daten -> Skript -> Stimme -> Bild -> Ton -> MP4 + Post-Text
deliver.py           Video + Text an Telegram
rugtok/fetch.py      API-Client (Rate-Limit, Retries, Budget, Archiv) + Auswahl-Logik
rugtok/data.py       Schema + strenge Prüfung echter Daten
rugtok/script.py     Text-Template (Anzeige vs. Aussprache, nur belegte Sätze)
rugtok/scenes.py     5 Szenen + Chart     rugtok/render.py  Frames, Effekte, ffmpeg
rugtok/tts.py        Stimme + Timing      rugtok/audio.py   SFX, Beat, Mix
.github/workflows/daily.yml   täglicher Lauf
```

Lizenzen: Inter (OFL-1.1), Piper (MIT), Stimme „thorsten“ (CC0).
