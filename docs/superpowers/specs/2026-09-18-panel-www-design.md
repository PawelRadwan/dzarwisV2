# Panel WWW do sterowania światłami — projekt

Data: 2026-09-18. Status: zaakceptowany.

## Cel

Strona do włączania i wyłączania świateł z telefonu. Zakładki: Oświetlenie (teraz), PV i Ogrzewanie (później — na razie „wkrótce”).

## Założenia

- Dostęp: sieć domowa, spoza domu przez VPN. Bez logowania. Adres `http://192.168.8.18/` (port 80).
- Raspberry Pi: Raspbian 10, Python 3.7, tylko `pyModbusTCP 0.2.0`. Bez nowych zależności.
- Nie zmieniamy `lights_v2_.py` — panel to osobna usługa; awaria panelu nie może wpłynąć na przyciski ścienne.

## Architektura

```
telefon ──HTTP──► web_panel.py (web.service, port 80) ──Modbus TCP──► WAGO 192.168.8.5
                                                         ▲
wall buttons ──► WAGO ◄──Modbus TCP── lights_v2_.py (lights.service)
```

- `scripts/web_panel.py` — serwer `http.server.ThreadingHTTPServer` (stdlib). Importuje `read_registers` i `ModbusError` z `lights_v2_` (import bezpieczny — `main()` pod `if __name__`).
- `scripts/web/index.html` — cała strona (HTML + CSS + JS w jednym pliku, bez zewnętrznych bibliotek).
- `scripts/web/manifest.json`, `scripts/web/icon-192.png`, `scripts/web/icon-512.png` — ikona na ekran główny (Android, iOS przez `apple-touch-icon`).
- `deploy/systemd/web.service` — usługa, `User=pi`, `AmbientCapabilities=CAP_NET_BIND_SERVICE` (port 80 bez roota), `Restart=always`, `RestartSec=5`, `StartLimitIntervalSec=0`.

Dostęp do Modbusa w panelu: jedno połączenie współdzielone przez wątki, chronione blokadą (`threading.Lock`), timeout 2 s. Po błędzie połączenie jest zamykane i otwierane przy następnym żądaniu.

## Obwody na stronie

Lista `SWIATLA` w `web_panel.py`: kolejność i nazwa wyświetlana → nazwa wyjścia w `dgv.PLC.Douts`:

Wiatrołap, Hol, Kuchnia, Jadalnia, Salon, Salon – kinkiety, Spiżarnia, Pralnia, Łazienka, Biuro, Nad schodami, Przejście, Łazienka góra, Sypialnia, Natka, Natka 2, Ola, Paweł.

Wyjścia bojlera nie są pokazywane (przyszła zakładka Ogrzewanie).

## API

| Metoda i ścieżka | Treść | Odpowiedź |
|---|---|---|
| `GET /` | — | `index.html` |
| `GET /manifest.json`, `/icon-*.png` | — | pliki statyczne (tylko z białej listy) |
| `GET /api/lights` | — | `200 {"lights": [{"id": "swiatlo kuchnia", "label": "Kuchnia", "on": true}, ...]}` |
| `POST /api/lights` | `{"id": "swiatlo kuchnia", "on": false}` | `200` + aktualna lista (jak GET) |
| `POST /api/lights/all-off` | — | `200` + aktualna lista |

Błędy: nieznany `id` / zły JSON → `400 {"error": "..."}`; brak łączności z WAGO → `503 {"error": "..."}`.

Ustawienie stanu (nie przełączenie): odczyt rejestru wyjść z bitem obwodu, ustawienie/wyzerowanie bitu, zapis — tylko jeśli wartość się zmienia. „Wyłącz wszystko” zeruje bity wszystkich świateł z listy, jeden zapis na rejestr.

## Strona

- Zakładki u góry: Oświetlenie / PV / Ogrzewanie; PV i Ogrzewanie z tekstem „Wkrótce”. Wybrana zakładka w `location.hash`.
- Oświetlenie: lista kafelków (jedna kolumna na telefonie, więcej na szerokim ekranie). Kafelek: nazwa + „Świeci” / „Zgaszone”; włączony — wyraźnie podświetlony. Dotknięcie wysyła przeciwny stan; w czasie żądania kafelek jest zablokowany.
- Na dole przycisk „Wyłącz wszystko” z `confirm()`.
- Odświeżanie `GET /api/lights` co 2 s (wstrzymane, gdy karta jest w tle — `visibilitychange`).
- Brak łączności (błąd sieci lub 503): czerwony pasek „Brak połączenia ze sterownikiem”, kafelki wyszarzone.
- Motyw jasny/ciemny wg ustawień telefonu. Bez zewnętrznych czcionek i skryptów.

## Ryzyko

Dwa procesy zapisują te same rejestry wyjść (odczyt → zmiana bitu → zapis). Równoczesne kliknięcie w panelu i naciśnięcie przycisku ściennego w oknie kilku ms może cofnąć jedną ze zmian. Akceptowalne; opisane w dokumentacji.

## Testy

- Automatyczne (`tests/test_web_panel.py`, `unittest`, podmieniony `ModbusClient`): lista świateł i stany, włączenie, wyłączenie, brak zapisu gdy stan się nie zmienia, wyłącz wszystko, nieznany id, zły JSON, brak łączności → 503, pliki statyczne i blokada ścieżek spoza białej listy.
- Na Pi: uruchomienie usługi, `GET /api/lights`, przełączenie jednego światła, podgląd strony.
