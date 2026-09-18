# Konfiguracja i uruchomienie

## Serwer produkcyjny (stan z 2026-09-18)

| | |
|---|---|
| Host | Raspberry Pi `raspberrypi`, użytkownik `pi` |
| System | Raspbian 10 (buster), armv7l, jądro 5.10 |
| Python | **3.7.3** (systemowy `/usr/bin/python3`, bez venv) |
| Sieć | `eth0` 192.168.8.18/24 — sieć WAGO i bramki Modbus<br>`eth1` 192.168.1.30/24 — sieć sterownika pompy ciepła (192.168.1.31) |
| Katalog projektu | `/home/pi/dzarwisV2` (klon z GitHuba, gałąź `main`, commit `31c5284`) |
| Zainstalowane pakiety projektu | tylko `pyModbusTCP 0.2.0` |
| Inne usługi | `codesysedge` (CODESYS Edge Gateway) — niezwiązany z tym repo |

### Co faktycznie działa

Na Pi działa **wyłącznie** `lights_v2_.py` jako usługa systemd `lights.service`. Pozostałe skrypty (`read_power.py`, `wago_750_comunication.py`, `bojler_ster.py`) **nie są tu uruchomione** — nie ma też RabbitMQ, InfluxDB ani bibliotek `pika`, `influxdb`, `pymodbus`.

### `/etc/systemd/system/lights.service`

```ini
[Unit]
Description=Autostart Lights Script
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/dzarwisV2/scripts
ExecStart=/usr/bin/python3 /home/pi/dzarwisV2/scripts/lights_v2_.py
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/lights.service.d/restart.conf` (dodany 2026-09-18)

```ini
[Unit]
StartLimitIntervalSec=0

[Service]
RestartSec=5
```

Plik nadpisujący (drop-in) zmienia zachowanie po awarii skryptu:

| | Przed | Po |
|---|---|---|
| Przerwa przed ponownym startem | 100 ms | 5 s |
| Limit startów | 5 w ciągu 10 s, potem usługa zostaje wyłączona na stałe | brak — usługa podnosi się w nieskończoność |

Powód: 2026-08-17 po rozruchu Pi sieć nie była jeszcze gotowa, skrypt padł 5 razy w 3 s, systemd przestał go uruchamiać i przyciski nie działały ok. 3 h 40 min ([znane-problemy.md](znane-problemy.md#1-lights_v2_py-kończy-działanie-przy-błędzie-komunikacji)). Teraz przy braku łączności skrypt próbuje co 5 s, aż WAGO wróci.

Zmiana została wprowadzona przez `systemctl daemon-reload` **bez restartu** działającego procesu. Kopie obu plików są w repo: [`deploy/systemd/`](../deploy/systemd/).

Odtworzenie na nowym Pi:

```bash
sudo cp deploy/systemd/lights.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/lights.service.d
sudo cp deploy/systemd/lights.service.d/restart.conf /etc/systemd/system/lights.service.d/
sudo systemctl daemon-reload
sudo systemctl enable --now lights.service
```

Sprawdzenie aktywnych ustawień:

```bash
systemctl show lights.service -p RestartUSec,StartLimitIntervalUSec,DropInPaths
# RestartUSec=5s, StartLimitIntervalUSec=0, DropInPaths=.../restart.conf
```

Cofnięcie: `sudo rm -r /etc/systemd/system/lights.service.d && sudo systemctl daemon-reload`.

### Testy po zmianie (2026-09-18)

| Test | Jak | Wynik |
|---|---|---|
| Awaria procesu | `systemctl kill -s KILL lights.service` | ✅ ponowny start po 5 s (12:14:56 → 12:15:01) |
| Brak WAGO przez 40 s | reguła `iptables -j REJECT` do 192.168.8.5 na Pi | ✅ 8 awarii co 5 s (stara konfiguracja poddałaby się po 5.), po odblokowaniu skrypt wstał sam w ~2 s |
| Zapis wyjść | przez Modbus: „swiatlo biuro” wyłączone i włączone z powrotem | ✅ zapis i odczyt zgodne |
| Restart Pi (jak po zaniku prądu) | `systemctl reboot` | ✅ patrz niżej |

Przebieg rozruchu Pi:

```
12:18:22  start systemu
12:18:37  lights.service uruchomiony
12:18:38  awaria: TypeError: object of type 'NoneType' has no len()   ← eth0 jeszcze bez adresu
12:18:43  ponowny start po 5 s — działa stabilnie
```

**Skrypt zawsze pada przy pierwszym starcie po rozruchu Pi**, bo `After=network.target` nie czeka, aż `eth0` dostanie adres, i pierwszy odczyt z WAGO się nie udaje. Przy starej konfiguracji (100 ms × 5 prób) usługa poddawała się, zanim sieć była gotowa, więc **po każdym zaniku prądu oświetlenie mogło nie wstać samo** — to wyjaśnia wcześniejsze problemy. Teraz pierwsza nieudana próba kosztuje 5 s, a oświetlenie działa ok. 20 s od startu systemu.

Test nie odwzorowuje w 100% zaniku prądu: przy prawdziwym zaniku restartuje się też WAGO i może wstać później niż Pi. Test z blokadą WAGO pokazał, że usługa czeka na nie dowolnie długo.

### Różnice między Pi a repozytorium

Stan przed wdrożeniem poprawionego `lights_v2_.py`: na Pi działa commit `31c5284` z niezacommitowanymi zmianami (shebang w `lights_v2_.py`, kosmetyka w `dzarwis_global_vars.py`). Obie zmiany zostały przeniesione do repozytorium, więc `git pull` na Pi przejdzie bez konfliktów — wystarczy przed nim `git checkout -- scripts/` (zmiany lokalne są już w repo).

Nieśledzone pliki w katalogu projektu (narzędzie do pompy ciepła, zob. [pompa-ciepla.md](pompa-ciepla.md)): `kotek_rpi`, `*.xml`.

### Obsługa usługi

```bash
systemctl status lights.service
sudo systemctl restart lights.service
journalctl -u lights.service -f          # podgląd na żywo
journalctl -u lights.service | grep -E "exited|Traceback"   # historia awarii
```

Dziennik systemd nie jest trwały — po restarcie Pi historia sprzed rozruchu znika.

### Wdrożenie zmian

Na Pi nie ma mechanizmu wdrożeń — kod aktualizuje się z GitHuba:

```bash
cd ~/dzarwisV2
git status                      # nie powinno być zmian w scripts/
git pull
sudo systemctl restart lights.service
journalctl -u lights.service -f # oczekiwane: "połączenie z WAGO OK"
```

Powrót do poprzedniej wersji: `git checkout <commit> -- scripts/lights_v2_.py && sudo systemctl restart lights.service`.

---

## Wymagania

- Python ≥ 3.7. Uwaga: `wago_750_comunication.py` używa adnotacji `list[dict[...]]`, która na Pythonie 3.7/3.8 powoduje błąd przy imporcie — na obecnym Pi ten skrypt **nie uruchomi się** bez poprawki.
- Dostęp sieciowy do `192.168.8.5` (WAGO) i `192.168.8.40` (bramka Modbus).
- RabbitMQ na localhost — tylko dla `wago_750_comunication.py` i `queue_tester.py`.
- InfluxDB 1.x na localhost z bazą `Energia` i użytkownikiem `pi` — tylko dla `read_power.py` i `bojler_ster.py`.

## Biblioteki

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

| Pakiet | Używany w | Uwagi |
|---|---|---|
| `pyModbusTCP` | wszystkie skrypty Modbus | na Pi: 0.2.0 |
| `pika` | kolejka | klient RabbitMQ |
| `influxdb` | `read_power.py`, `bojler_ster.py` | klient InfluxDB **1.x** (nie 2.x) |
| `pymodbus` | `read_power.py` | tylko `BinaryPayloadDecoder` i `Endian.Big`. Kod pisany pod pymodbus 2.x — w wersjach 3.x zmieniono nazwy (`Endian.BIG`), a dekoder został później usunięty. Stąd ograniczenie `<3`. |

## Uruchamianie ręczne

Z katalogu `scripts/`:

```bash
cd scripts
python3 lights_v2_.py              # obsługa przycisków
python3 wago_750_comunication.py   # konsument kolejki
python3 read_power.py              # rejestrator energii
python3 bojler_ster.py             # logika bojlera (tylko wypisuje)
```

Każdy skrypt działa w nieskończonej pętli i pisze diagnostykę na standardowe wyjście.

**Nie uruchamiaj ręcznie `lights_v2_.py` na Pi, gdy działa `lights.service`**, ani razem z `lihgts.py` / `brudnopis.py` — każda kopia przełączałaby lampy osobno, więc jedno naciśnięcie przełączyłoby lampę dwa razy.

## Zmiana konfiguracji

| Co zmieniasz | Gdzie |
|---|---|
| IP sterownika WAGO, lista wyjść | `scripts/dzarwis_global_vars.py` → `PLC` |
| Przypisanie przycisków do lamp | `scripts/lights_v2_.py` (słownik `PRZYCISKI`) |
| Godziny taryfy, mieszanie bojlera | `scripts/dzarwis_global_vars.py` |
| IP bramki, unit id Growatta/licznika, okres odczytu | `scripts/read_power.py` (stałe na górze pliku) |
| Dane InfluxDB | `dzarwis_global_vars.py` **oraz** `read_power.py` (wpisane osobno) |

Po zmianie trzeba zrestartować odpowiedni skrypt / usługę.
