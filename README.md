# rug-tok – „Rug-Check“ TikTok-Generator

Erzeugt aus einer JSON-Datei mit Token-Daten ein fertiges TikTok-Video (1080×1920, 30 fps, ~30–35 s):
Hook mit Kurs-Counter → Token-Karte → Live-Chart mit Dev-Dump → Warnsignale → Verlust + Follow-CTA.
Deutsche KI-Stimme, Wort-für-Wort-Untertitel, Sounddesign, Lautheit auf −14 LUFS normalisiert.
Kein LLM pro Video nötig, also null Claude/ChatGPT-Kontingent im Betrieb.

## Start

```bash
pip install -r requirements.txt          # Python 3.10+, dazu ffmpeg im PATH
bash scripts/setup_piper.sh              # nur nötig, wenn edge-tts nicht geht (Offline-Stimme)
python3 build.py content/demo_rug.json   # -> out/demo_rug.mp4
```

Nützlich:
- `--stills 1,5.2,16` → nur Standbilder (PNG), zum schnellen Prüfen in Sekunden
- `--tts edge|piper|auto` → Stimme wählen (auto = edge, sonst piper)
- `--no-music` → ohne Hintergrund-Beat (wenn du in der TikTok-App einen Trend-Sound drunterlegst)
- Stimme ändern: `RUGTOK_EDGE_VOICE=de-DE-KatjaNeural`, Tempo: `RUGTOK_EDGE_RATE=+12%`

## Daten (`content/*.json`)

| Feld | Bedeutung |
|---|---|
| `token.symbol` / `token.say` | Ticker auf dem Bildschirm / so wird er ausgesprochen |
| `launch_time`, `launch_day` | Start, z. B. `"14:02"`, `"gestern"` |
| `initial_liquidity_usd` | Liquidität beim Start |
| `minutes_to_peak`, `peak_gain_pct` | Zeit bis Hoch, Anstieg in % |
| `minutes_peak_to_dead`, `drawdown_pct` | Zeit vom Hoch bis „tot“, Absturz in % |
| `buyers`, `dev_supply_pct`, `bundle_wallets`, `deployer_prior_rugs` | Käufer, Dev-Anteil, gebündelte Wallets, frühere Rugs des Deployers |
| `buyer_loss_usd` | Verlust der Käufer |
| `demo` | `true` blendet „DEMO-DATEN“ ein. **Nur echte, geprüfte Daten mit `false` posten.** |
| `contract_address`, `price_series`, `sources`, `loss_method` | **Pflicht bei `demo: false`.** `price_series` = `[[minute, preis], …]` (≥ 20 Punkte). Die Kennzahlen werden gegen die Preisreihe geprüft; passt etwas nicht, bricht der Build ab. |
| `series`, `cta.telegram` | Serienname (Standard `RUG-CHECK`), Telegram-CTA statt „Folgen“ |

Zu jedem Video entsteht `out/<name>_beschreibung.txt` mit voller Contract-Adresse, Quellen, Berechnungsmethode, Disclaimer und Hashtags – als Post-Text.

## Sprachregel (rechtlich)

Das Template sagt nur **beobachtbare On-Chain-Fakten**: „Die Ersteller-Wallet verkaufte alles“, nicht „Betrüger“ oder „Scam“. Keine Personennamen, keine Absicht unterstellen, Verlust als „geschätzt“ mit Methode. Das senkt das Risiko, ersetzt aber **keine Prüfung durch einen Anwalt** vor dem echten Betrieb.

## Tests

`python3 tests/test_data.py` – prüft, dass echte Videos ohne Contract-Adresse, Quellen, echte Preisreihe oder mit unstimmigen Zahlen **nicht** gebaut werden.

## Aufbau

```
build.py            CLI: Daten → Skript → Stimme → Bild → Ton → MP4
rugtok/script.py    Text-Template (Anzeige vs. Aussprache, Marker für Effekte)
rugtok/tts.py       edge-tts / Piper, Wort-Timings, Timeline
rugtok/scenes.py    die 5 Szenen + Chart
rugtok/captions.py  Untertitel
rugtok/audio.py     synthetische SFX (lizenzfrei), Beat, Ducking, Voice-Chain
rugtok/render.py    Frame-Loop, Shake/Flash/Glitch, ffmpeg
```

## Stand / bekannte Grenzen

- Getestet mit Piper (Offline-Stimme, 16 kHz – hörbar „billiger“). Der edge-tts-Pfad ist geschrieben, aber **noch nicht getestet** (hier kein Zugang zu Microsofts Server).
- Wort-Timings sind geschätzt (Silben + echte Pausen), nicht forced-aligned. Bei Versatz `GAP_*`/Piper-Tempo in `config.py`/`tts.py` anpassen.
- Ohne `price_series` (nur im Demo-Modus erlaubt) wird der Chart aus den Kennzahlen synthetisiert.
- Noch keine Datenanbindung und kein automatisches Posten – kommt in Schritt 3/4.

Lizenzen: Inter (OFL-1.1, `assets/fonts/LICENSE-Inter.txt`), Piper (MIT), Stimme „thorsten“ (siehe Model Card).
