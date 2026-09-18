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

## Budowa

```
telefon ──HTTP :80──► web_panel.py (web.service) ──Modbus TCP──► WAGO 192.168.8.5
przyciski ścienne ──► WAGO ◄──Modbus TCP── lights_v2_.py (lights.service)
```

| Plik | Rola |
|---|---|
| `scripts/web_panel.py` | serwer HTTP (`http.server` z biblioteki standardowej) + obsługa Modbus |
| `scripts/web/index.html` | cała strona: HTML, CSS i JS w jednym pliku, bez bibliotek z internetu |
| `scripts/web/manifest.json`, `icon-192.png`, `icon-512.png` | ikona i nazwa na ekranie głównym telefonu |
| `deploy/systemd/web.service` | usługa systemd |
| `tests/test_web_panel.py` | testy na symulowanym WAGO |

Panel to osobny proces — jego awaria nie wpływa na przyciski ścienne. Korzysta z `read_registers` i `ModbusError` z `lights_v2_.py`. Ma jedno połączenie Modbus, współdzielone przez wątki pod blokadą; po błędzie zamyka je i otwiera przy następnym żądaniu.

Serwer wydaje tylko pliki z listy `STATIC` w `web_panel.py` — nic innego z dysku Pi nie jest dostępne.

## API

| Żądanie | Treść | Odpowiedź |
|---|---|---|
| `GET /api/lights` | — | `{"lights": [{"id": "swiatlo kuchnia", "label": "Kuchnia", "on": true}, …]}` |
| `POST /api/lights` | `{"id": "swiatlo kuchnia", "on": false}` | lista jak wyżej, już po zmianie |
| `POST /api/lights/all-off` | — | lista jak wyżej |

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
