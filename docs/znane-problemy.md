# Znane problemy

Stan na 2026-09-18: analiza kodu z repozytorium (commit `31c5284`) oraz przegląd produkcyjnego Raspberry Pi (logi `lights.service`). Pi uruchamia ten sam kod, różnice to tylko kosmetyka — patrz [uruchomienie.md](uruchomienie.md#różnice-między-pi-a-repozytorium).

## Wysoki priorytet

### 1. `lights_v2_.py` kończy działanie przy błędzie komunikacji — **potwierdzone na produkcji**

`pyModbusTCP` przy błędzie **zwraca `None`** zamiast rzucać wyjątek. `try/except` wokół odczytu wejść (`lights_v2_.py:73`) więc go nie łapie, a program pada chwilę później na `len(None)`. Tak samo w `wago_read_outputs` (`extend(None)`) i przy starcie (`old_inputs = None`).

Awarie z dziennika Pi (od rozruchu 2026-08-17):

| Kiedy | Błąd | Skutek |
|---|---|---|
| 2026-08-17, tuż po rozruchu Pi | `object of type 'NoneType' has no len()` ×5 w 3 s | systemd przerwał restarty („Start request repeated too quickly”). **Przyciski nie działały do 20:36** — ok. 3 h 40 min (16:55–20:36), do ręcznego `systemctl start` |
| 2026-09-02 23:56 | `'NoneType' object is not iterable` w `wago_read_outputs` | restart po 100 ms |
| 2026-09-10 13:16 | to samo, w trakcie przełączania „swiatlo lazienka” | restart po 100 ms; naciśnięcie zgubione |

Test restartu Pi (2026-09-18) pokazał, że **skrypt pada przy każdym rozruchu**: startuje, zanim `eth0` ma adres IP. Awaria z 17.08 to ten sam przypadek: Pi nie ma zegara sprzętowego, więc wpisy dziennika sprzed synchronizacji NTP mają przesunięte godziny (dziennik: awaria 16:49, rzeczywisty start systemu wg `uptime`: 16:55). Awaria nastąpiła więc tuż po rozruchu — najpewniej po zaniku prądu — i oświetlenie nie wstało samo aż do ręcznego startu o 20:36. `lights.service` ma `Restart=always`, ale domyślne `RestartSec=100ms` i limit 5 startów w 10 s powodują, że przy dłuższym braku łączności usługa poddaje się na stałe.

**Naprawa:**

- ✅ **w usłudze — zrobione 2026-09-18.** Dodany drop-in `lights.service.d/restart.conf` (`RestartSec=5`, `StartLimitIntervalSec=0`), więc usługa nie poddaje się już przy dłuższym braku WAGO. Szczegóły: [uruchomienie.md](uruchomienie.md#etcsystemdsystemlightsservicedrestartconf-dodany-2026-09-18). To ogranicza skutki, ale nie usuwa przyczyny: skrypt nadal pada przy każdym błędzie odczytu, a naciśnięcie przycisku w tym momencie przepada.
- ✅ **w kodzie — poprawione 2026-09-18** (wymaga wdrożenia na Pi). `lights_v2_.py` sprawdza wynik na `None`, łapie wyjątki w całej pętli, a przy błędzie loguje go, odczekuje 1 s i próbuje dalej zamiast kończyć proces. Timeout zapytania skrócony z 30 s do 2 s.

### 2. Drugi przycisk „nad schodami” nie działa w v2

W v1 (`lihgts.py:143`) światło nad schodami reagowało na bit 6 **i bit 15** rejestru 0. W `lights_v2_.py` bit 15 nie jest obsługiwany. Jeśli przycisk jest podłączony, wystarczy dopisać `(0, 15): 'swiatlo nad schodami'` do słownika `PRZYCISKI`.

### 3. Wyścig zapisu między procesami

Przełączenie lampy to: odczyt → zmiana bitu → zapis całego 16-bitowego rejestru. Jeśli `lights_v2_.py` i `wago_750_comunication.py` (albo dwa przyciski w jednym obiegu) zapiszą ten sam rejestr jednocześnie, zmiana jednego procesu może cofnąć zmianę drugiego.

**Naprawa:** jeden proces jako jedyny właściciel zapisów (np. przyciski też przez kolejkę) albo przełączanie pojedynczych cewek (`write_single_coil`), jeśli WAGO je udostępnia.

## Średni priorytet

### 4. Wolna reakcja na przycisk — ✅ poprawione w `lights_v2_.py` 2026-09-18

Było: jedno przełączenie to 3 × odczyt 255 rejestrów (po 3 zapytania) + zapis, a przy `auto_close=True` każde zapytanie to nowe połączenie TCP. Teraz: jedno stałe połączenie, przełączenie = odczyt 1 rejestru + zapis. W `wago_750_comunication.py` stara metoda została.

### 5. `read_power.py` bez przerwy po błędzie

`sleep` jest tylko na ścieżce sukcesu (`read_power.py:110`). Po błędzie pętla od razu odpytuje bramkę ponownie.

### 6. Moc Growatta czytana z połowy rejestru

Pac1 to wartość 32-bitowa (3028 = słowo starsze, 3029 = młodsze). Kod zapisuje tylko młodsze słowo, więc moc powyżej 6553,5 W będzie błędna.

### 7. Konsument kolejki pada na złej wiadomości

Wyjątek w `callback` (zły JSON, brak `command`, błąd Modbusa) kończy `wago_750_comunication.py`.

### 8. `wago_750_comunication.py` nie działa na Pythonie 3.7

Adnotacja `list[dict[...]]` w `wago_set_outputs` wymaga Pythona ≥ 3.9. Produkcyjne Pi ma 3.7.3, więc import zakończy się `TypeError: 'type' object is not subscriptable`. Obecnie skrypt i tak nie jest tam uruchomiony.

## Niski priorytet

- `bojler_ster.py`: dzielenie przez zero, gdy w ostatnich 5 minutach nie ma pomiarów; analizuje tylko fazę `P1`, a nie sumę faz.
- `read_power.py`: prądy I1–I3 są dekodowane, ale nie zapisywane; dane InfluxDB zduplikowane zamiast brane z `dzarwis_global_vars`.
- Kopie funkcji obsługi WAGO w `wago_750_comunication.py`, `lihgts.py`, `brudnopis.py` — do wydzielenia do wspólnego modułu.
- `queue_tester.py` importuje `tkinter` bez potrzeby.
- Hasło `pi`/`pi` do InfluxDB w repozytorium.
