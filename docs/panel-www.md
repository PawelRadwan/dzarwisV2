# Panel WWW

Strona do włączania i wyłączania świateł z telefonu.

**Adres:** http://192.168.8.18/ — w sieci domowej, spoza domu przez VPN. Bez logowania.

## Obsługa

- Zakładki u góry: **Oświetlenie**, **PV**, **Ogrzewanie** (dwie ostatnie jeszcze puste — „Wkrótce”).
- Każdy kafelek to jeden obwód: nazwa i stan. Żółty = **Świeci**, szary = **Zgaszone**. Dotknięcie przełącza światło.
- Stan odświeża się sam co 2 s — widać też zmiany z przycisków ściennych.
- **Wyłącz wszystko** (na dole) gasi wszystkie światła, po potwierdzeniu. Bojlera nie rusza.
- Czerwony pasek **„Brak połączenia ze sterownikiem”** — panel nie może się połączyć z WAGO albo z Pi. Kafelki są wtedy wyszarzone; strona sama wróci do działania, gdy połączenie wróci.

### Ikona na ekranie telefonu

- **Android (Chrome):** menu ⋮ → *Dodaj do ekranu głównego* / *Zainstaluj aplikację*.
- **iPhone (Safari):** przycisk *Udostępnij* → *Do ekranu początkowego*.

Strona otwiera się wtedy jak aplikacja, na pełnym ekranie, jako „Dżarwis”.

## Zakładka PV

- **Kafelki:** produkcja teraz, sieć („Oddawanie ↑” / „Pobór ↓”), zużycie domu (= produkcja + sieć), produkcja dziś.
- **Moc na fazach** (L1–L3): zużycie domu i pobór/oddawanie z sieci na każdej fazie, napięcie i prąd. Falownik jest jednofazowy, na **L1** (`INVERTER_PHASE` w `energia.py`) — tam dom = sieć + produkcja, na L2/L3 dom = sieć.
- **Wykres dnia** (00:00–24:00): produkcja — pomarańczowe pole, zużycie domu — niebieska linia. Dotknięcie / najechanie pokazuje godzinę i obie wartości. Przerwa w linii = brak danych (np. restart Pi).
- **Bilans dnia:** produkcja / pobrano / oddano / zużycie domu [kWh], autokonsumpcja (jaka część produkcji została w domu). Wszystkie wartości za ten sam okres — od pierwszego odczytu po północy; jeśli dane zaczęły się później (np. po restarcie Pi bez wcześniejszych danych), obok tytułu jest „od HH:MM”, a produkcja w bilansie może być mniejsza niż w kafelku „Produkcja dziś” (ten jest zawsze od północy, z falownika).
- **Łącznie od …** i **Miesiące** (od najnowszego): pobrano / oddano (zbilansowane), produkcja (moc falownika × czas, tak jak pobór i oddanie), zużycie domu (= produkcja + pobrano − oddano), autokonsumpcja. Dane od 2026-09-18; pierwszy miesiąc oznaczony „od DD.MM”.
- **Pobór i oddanie są zbilansowane po fazach** — jak licznik zakładu energetycznego (w Polsce zwykle sumuje fazy): co 5 s moc łączna z licznika × czas od poprzedniego odczytu, dodatnia → pobór, ujemna → oddanie (przerwy > 30 s pomijane). Licznik SDM630 liczy każdą fazę osobno — przy falowniku na L1 zawyża pobór i oddanie; jego stany są w karcie Falownik z dopiskiem „po fazach”. Dotyczy też bilansu dnia.
- **Stringi PV** i **Falownik** (status, temperatura, częstotliwość, kody błędów, liczniki łączne).
- Żółty pasek „Falownik nie odpowiada — w nocy to normalne”: falownik jest zasilany z paneli i w nocy się wyłącza. Produkcja = 0, reszta działa.
- Czerwony pasek „Brak połączenia z licznikiem energii”: bramka 192.168.8.40 lub licznik nie odpowiada.

Dane odświeżają się co 5 s (wykres co minutę), tylko gdy zakładka PV jest otwarta. Szczegóły odczytu rejestrów i obliczeń: [superpowers/specs/2026-09-18-panel-pv-design.md](superpowers/specs/2026-09-18-panel-pv-design.md).

### Zbieranie danych

Wątek w `web_panel.py` (`scripts/energia.py`) co 5 s czyta falownik Growatt (unit 2) i licznik SDM630 (unit 3) przez bramkę `192.168.8.40`, niezależnie od tego, czy ktoś ogląda stronę. Co minutę zapisuje średnie do SQLite: `/home/pi/dzarwisV2/data/energia.db` (poza gitem, ok. 1440 wierszy na dobę). Podgląd bazy:

```bash
sqlite3 ~/dzarwisV2/data/energia.db "SELECT datetime(ts,'unixepoch','localtime'), pv_w, grid_w, home_w FROM samples ORDER BY ts DESC LIMIT 5"
```

Bramka odrzuca odczyt dużych bloków rejestrów (licznik: >54, Growatt: >64), dlatego zapytania są małe.

## Zakładka Ogrzewanie

Pompa ciepła (sterownik Quotek `192.168.1.31`) — wyłącznie przez narzędzie `kotek_rpi` ([pompa-ciepla.md](pompa-ciepla.md)).

- **Paski:** czerwony — awaria sterownika (np. „Awaria: Presostaty lub PWR”) albo brak łączności; żółty — zegar sterownika różni się od czasu Pi o > 5 min (harmonogramy działają wg zegara sterownika).
- **Kafelki:** stan, pobór mocy całej pompy [W], aktywny program.
- **Ręczne grzanie** (domyślnie 1 h, 0,5–8 h): panel wgrywa program S z jednorazową akcją grzania (z datą) na najbliższą minutę **zegara sterownika**; temperatura z ustawień sterownika (powrót CO 35 °C). Licznik pokazuje „Start o … — za …”, potem „Grzeje — do końca …” (czas ze sterownika). Nie ma przycisku stop — `kotek` nie ma polecenia przerywającego grzanie.
- **Same pompy obiegowe** (domyślnie 15 min, 1–120): Pompa CO / Pompa kolektora / Obie (`samepompy`), licznik odliczający, „Zatrzymaj pompy” (`samepompy 0 0`).
- **Program:** wybór 1–4 (`wlaczprogram`, zmiana potwierdzana — sterownik przełącza z opóźnieniem kilku sekund).
- **Harmonogram aktywnego programu** z linią „Teraz: …” (awaria / grzanie / pracujące pompy / spoczynek) i stanem każdego zadania na dziś: „✓ wykonano GG:MM” (z dziennika sterownika), „trwa”, „następne — za …”, „nie wykonano”; godziny wg zegara sterownika, przy przesunięciu z dopiskiem „u nas ok. GG:MM”. Opis zadań czytelny: „codziennie 03:30–06:00 grzanie…”.
- Temperatury czujników (bieżąca, min–max 24 h), pompy i wejścia (PWR, HP/LP), grzanie CO/CWU wł./wył., ostatnie akcje (powtórzenia zwinięte, np. „×124”), energia pompy ciepła łącznie [kWh] (1000 impulsów = 1 kWh), zegar sterownika.
- **Pompa CWU** — podłączona do przekaźnika sprężarki, bez osobnego sterowania (do zmiany).

Każda akcja wymaga potwierdzenia i trafia do dziennika (`journalctl -u web.service`). Stan „do kiedy” pomp i ręcznego grzania: `data/pompa-stan.json` (wspólny dla telefonów, przetrwa restart). Odczyt co 5 s tylko przy otwartej zakładce (w tle panel czyta sterownik co 5 s zawsze).

## Budowa

```
telefon ──HTTP :80──► web_panel.py (web.service) ──Modbus TCP──► WAGO 192.168.8.5
                           └─ energia.py (wątek) ──Modbus TCP──► bramka 192.168.8.40 (Growatt, SDM630)
                                   └─► data/energia.db (SQLite)
przyciski ścienne ──► WAGO ◄──Modbus TCP── lights_v2_.py (lights.service)
```

| Plik | Rola |
|---|---|
| `scripts/web_panel.py` | serwer HTTP (`http.server` z biblioteki standardowej) + obsługa Modbus |
| `scripts/energia.py` | odczyt falownika i licznika, minutowa historia w SQLite, bilans dnia |
| `scripts/pompa.py` | pompa ciepła przez `kotek_rpi`: odczyt, program, pompy, ręczne grzanie; tylko dozwolone polecenia |
| `scripts/web/index.html` | cała strona: HTML, CSS i JS w jednym pliku, bez bibliotek z internetu |
| `scripts/web/manifest.json`, `icon-192.png`, `icon-512.png` | ikona i nazwa na ekranie głównym telefonu |
| `deploy/systemd/web.service` | usługa systemd |
| `tests/test_web_panel.py`, `tests/test_energia.py` | testy na symulowanych urządzeniach (rejestry odczytane z prawdziwych) |

Panel to osobny proces — jego awaria nie wpływa na przyciski ścienne. Korzysta z `read_registers` i `ModbusError` z `lights_v2_.py`. Ma jedno połączenie Modbus, współdzielone przez wątki pod blokadą; po błędzie zamyka je i otwiera przy następnym żądaniu.

Serwer wydaje tylko pliki z listy `STATIC` w `web_panel.py` — nic innego z dysku Pi nie jest dostępne.

## API

| Żądanie | Treść | Odpowiedź |
|---|---|---|
| `GET /api/lights` | — | `{"lights": [{"id": "swiatlo kuchnia", "label": "Kuchnia", "on": true}, …]}` |
| `POST /api/lights` | `{"id": "swiatlo kuchnia", "on": false}` | lista jak wyżej, już po zmianie |
| `POST /api/lights/all-off` | — | lista jak wyżej |
| `GET /api/pv` | — | stan na żywo: `now`, `today`, `phases`, `strings`, `inverter`, `totals`, `meter_ok`, `inverter_ok`; `503` do pierwszego odczytu |
| `GET /api/heat` | — | stan pompy: `state`, `fault`, `power_w`, `temps`, `program`, `programs`, `actions`, `energy_kwh`, `clock_diff_min`, `manual` (liczniki) |
| `POST /api/heat/program` | `{"program": 1..4}` | stan pompy |
| `POST /api/heat/pumps` | `{"co_min": 0..120, "kol_min": 0..120}` | stan pompy |
| `POST /api/heat/pumps/stop` | — | stan pompy |
| `POST /api/heat/manual` | `{"hours": 0.5..8}` | stan pompy |
| `GET /api/pv/months` | — | `{"since": ts, "totals": {...}, "months": [{"month": "2026-09", "from_day": 18, "import_kwh", "export_kwh", "pv_kwh", "home_kwh", "self_use_pct"}, …]}` |
| `GET /api/pv/day` | — | `{"date": "2026-09-18", "points": [[ts, pv_w, home_w], …]}` — dzisiejsze minuty |

`on` to **docelowy stan**, nie „przełącz” — powtórzone żądanie niczego nie psuje, a zapis do WAGO jest wykonywany tylko wtedy, gdy stan się zmienia.

Błędy: `400` — nieznany obwód lub zły JSON; `503` — brak łączności z WAGO; `404` — nieznana ścieżka. Treść: `{"error": "…"}`.

Przykład z konsoli:

```bash
curl http://192.168.8.18/api/lights
curl -X POST http://192.168.8.18/api/lights -d '{"id": "swiatlo hol", "on": true}'
```

## Zmiana nazw i kolejności

Lista `SWIATLA` na początku `scripts/web_panel.py`: para *(nazwa wyjścia z `dzarwis_global_vars.PLC.Douts`, nazwa na stronie)*, w kolejności wyświetlania. Po zmianie:

```bash
sudo systemctl restart web.service
```

Obwód, którego nie ma na liście, nie pojawia się na stronie (tak jest z wyjściami bojlera).

## Usługa

```bash
systemctl status web.service
sudo systemctl restart web.service
journalctl -u web.service -f
```

W dzienniku są: start, każda zmiana z panelu (adres IP telefonu, obwód, włącz/wyłącz), błędy WAGO. Samo odświeżanie strony nie jest logowane.

Instalacja na nowym Pi:

```bash
sudo cp deploy/systemd/web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now web.service
```

Port można zmienić zmienną środowiskową `DZARWIS_WEB_PORT` (domyślnie 80).

## Testy

```bash
python3 -m unittest discover -s tests
```

Testy podmieniają `pyModbusTCP` na symulowany sterownik, więc nie wymagają WAGO ani biblioteki.

## Ograniczenia

- **Równoczesny zapis.** Panel i `lights_v2_.py` zapisują te same rejestry wyjść (odczyt → zmiana bitu → zapis). Jeśli w tej samej chwili (okno kilku ms) ktoś dotknie kafelka i naciśnie przycisk ścienny, jedna ze zmian może się cofnąć — wystarczy powtórzyć.
- **Bez logowania.** Każdy w sieci domowej (i w VPN) może sterować światłami. Nie wystawiać portu 80 do internetu.
