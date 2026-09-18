# Pompa ciepła — sterownik Quotek i narzędzie `kotek_rpi`

| | |
|---|---|
| Sterownik | Quotek (`plytka typ="quotek1.0"`), `192.168.1.31:33311`, osiągalny przez `eth1` Pi (192.168.1.30) |
| Narzędzie | `/home/pi/dzarwisV2/kotek_rpi` — „Narzędzie konfiguracyjne sterownika Pompy Ciepła 3.62”, plik wykonywalny ARM 32-bit (2018), zewnętrzny, bez źródeł |
| Programy (pliki) | [`pompa/`](../pompa/README.md) w repozytorium: kopia z 2026-09-18, wgrane programy, stare pliki |
| Stan od 2026-09-18 | aktywny program 3 „bez grzania”, program S pusty — szczegóły w [`pompa/README.md`](../pompa/README.md) |

Wywołanie: `kotek_rpi [opcje] polecenie [parametry]`. Czas odpowiedzi ~0,03 s.

## Opcje

| Opcja | Znaczenie |
|---|---|
| `--adres <IP>` | adres sterownika (domyślnie zmienna `KOT_IP_ADRES`) — **zawsze `--adres 192.168.1.31`** |
| `--port <port>` | port (domyślnie `KOT_IP_PORT`; sterownik słucha na 33311) |
| `-x <plik>` / `--xml` | wynik jako XML do pliku (dla poleceń odczytu), `-x 0` — XML na ekran |
| `-b` / `--bezkomentarzy` | XML bez długiego komentarza-instrukcji na początku |
| `-v` | więcej komunikatów |
| `-h <polecenie>` | pomoc dla polecenia |

## Polecenia

Legenda ryzyka: **R** — tylko odczyt; **S** — zmienia pracę pompy (odwracalne); **Z** — zapisuje konfigurację/programy; **!** — niebezpieczne / nieodwracalne.

### Odczyt (R)

| Polecenie | Co zwraca | XML |
|---|---|---|
| `ping` | czy sterownik odpowiada („JEST!”) | – |
| `status` | stan (praca/awaria/…), opis awarii, grzanie (czas, start/stop, temperatury), program, pompy, czujniki PWR/HP/LP, wejścia/wyjścia, taryfa, liczniki energii, moc, grzanie CO/CWU wł./wył. | tak |
| `statuskrotki` | skrócony status (stan, awaria, czasy, CO wej., temp. zewn.) | tak |
| `odczytczujnikow` | wszystkie termometry: bieżąca, min/max/średnia 24 h, funkcja (pomoc błędnie podaje składnię `temperatury`) | tak |
| `temperatury <grupa>` | temperatury logiczne z grupy (`term`, `t24min`, `t24max`, `t24sr`, … — lista w `definicje`) | tak |
| `definicje` | identyfikatory temperatur logicznych do użycia w programach (`term1`…, `t24min1`…) | – |
| `czytaj` | pełna konfiguracja sterownika (IP, termometry, czasy, progi, wyjścia, termostaty, programator) | tak |
| `czytajprogram <n>` | program 1–5, `S` (stały) lub `0` (aktywny) | tak |
| `aktprogram` | numer i opis aktywnego programu | – |
| `listaprogramow` | lista programów: numer, opis, poprawność, aktywny | – |
| `wykonaneakcje` | ostatnio wykonane akcje programów (data, czas, program, akcja) | – |
| `energia` | liczniki energii w **impulsach** (taryfa niska / wysoka / obie) | tak |
| `statystyka` | statystyka dobowa: czas grzania, temperatury zewn./wewn., energia | tak |
| `zuzycie` (bez parametru) | licznik godzin pracy sprężarki (2026-09-18: 8730:39) | tak |
| `regulacja` (bez parametru) | korekta czasu grzania [%] i regulacje temperaturowe | – |
| `tempzew` | krzywa temperatury zewnętrznej (u nas brak czujnika — „Nie aktywna”) | – |
| `logi <n>` | ostatnie n wpisów logu (0 = wszystkie, 32 768 — długo!) | tak |
| `wykresy <dni> <katalog>` / `wykresy <od> <do> <katalog>` | z logów tworzy pliki danych do wykresów amCharts (`wyk_startstop.js`, `wyk_stat24.js`) — zapis na Pi, nie w sterowniku | – |
| `czytajkrzywe` | krzywe grzania (pomoc błędnie podaje nazwę `zapiszkrzywe`) | tak |
| `przebiegkrzywej <nr> <T od> <T do>` | punkty krzywej do wykresu | – |
| `pwmstatus <nr>` | stan wyjścia PWM | – |
| `flagidefinicje`, `flagistan` | definicje i stan flag (`USR1..16`, `SPRSTART`, `TARYFAN`, `GRZANIECO`, …) | – |

### Sterowanie pracą (S)

| Polecenie | Działanie |
|---|---|
| `wlaczprogram <n>` | ustawia aktywny program. Pomoc: 1–4, sterownik przyjął też 5. **Działa z opóźnieniem kilku sekund**; wypisuje numer liczony od zera (`programNr=2` = program 3) |
| `grzaniewlwyl co\|cwu 0\|1` | ręcznie włącza/wyłącza funkcję grzania CO lub CWU; normalnie ustawia to program |
| `samepompy <min kolektora> <min CO>` | uruchamia same pompy obiegowe (bez sprężarki) na podany czas; po zakończeniu aktualizuje temperatury w statusie |
| `termostat <1..2> 0\|1` | włącza/wyłącza termostat (skonfigurowany: #1 „bojler” 55 °C, histereza 0,5) |
| `flagiustaw <lista>` | ustawia do 4 flag użytkownika (`USR1,-USR2`, `~` negacja) — do warunków w programach |
| `regulacja czas <%>` | korekta czasu grzania ±50% |
| `regulacja <nr> <temp>` | wartość regulacji temperaturowej |
| `pwm <wyj> <czas> <okres> <impuls>`, `szybkipwm <%>` | wyjścia PWM |
| `port <1..16> 0\|1` | **!** bezpośrednio ustawia wyjście sterownika z pominięciem logiki — port 1 to sprężarka, 2 pompa CO, 3 pompa kolektora, 16 zapadka. Nie używać |

### Zapis programów i konfiguracji (Z)

| Polecenie | Działanie |
|---|---|
| `program <plik.xml>` | wgrywa programy zdefiniowane w pliku (numery z atrybutu `numer`) |
| `krzywe <plik.xml>` | wgrywa krzywe grzania (pomoc błędnie podaje nazwę `czytajkrzywe`) |
| `ustrtc <sekundy \| RRRR/MM/DD-GG:MM:SS-DT>` | ustawia zegar sterownika: przesunięcie w s albo czas bezwzględny, `DT` = `PN WT SR CZ PI SO ND` |
| `ustaw <plik.xml>` | **!** nadpisuje całą konfigurację sterownika (termometry, progi bezpieczeństwa, wyjścia). Tylko z kopią z `czytaj` |
| `zuzycie <min>` | **!** nadpisuje licznik pracy sprężarki |
| `usunprogramy` | **!** kasuje wszystkie programy łącznie z S (~20 s) |
| `reset` | **!** restart sterownika |

### Serwis i testy (!)

`symuon <p>` / `symuoff` (tryb symulacji), `symuterm <nr> <temp> <ok> <awaria>`, `symuwej <nr> <stan>` (symulowane termometry i wejścia) — podmieniają odczyty, na których sterownik podejmuje decyzje. Tylko przy wyłączonej pompie. `ds1820 1` — wykrywanie termometrów na porcie.

## Konfiguracja sterownika (odczyt 2026-09-18)

| Element | Wartość |
|---|---|
| Termometry DS1820 | #1 `zco` zasilanie CO, #2 `pko` powrót kolektora, #3 `par` parownik, #4 `zko` zasilanie kolektora, #5 `pco` powrót CO |
| Wyjścia | sprężarka port 1, pompa CO port 2, pompa kolektora port 3, zapadka port 16 |
| Progi | `pco` 35,0 °C (powrót CO — koniec grzania), `zko` −7,0 °C, `par` −8,1 °C (zabezpieczenia dolnego źródła), `rco` 0,4 |
| Czasy | przerwa między startami sprężarki 2 min; pompy CO/kolektora przed startem i po stopie 10 min |
| Presostaty | LP i HP włączone |
| Termostat | #1 „bojler” 55 °C, histereza 0,5, port 4 |
| Taryfa | wejście nr 5, po starcie „niska” |
| Programator | grzanie na starcie: CO tak, CWU nie |
| Czujnik zewnętrzny | brak (temperatura zewn. −99,9) |

## Format programów (XML)

Pełny opis jest w komentarzu na początku każdego pliku z `czytajprogram -x` (bez `-b`). Najważniejsze:

```xml
<pompa CfgVer="1.0">
  <program numer="1" opis="do 20 znakow">       <!-- 1–5 lub S (stały, zawsze działa niezależnie od aktywnego) -->
    <akcja czas="GG:MM">                          <!-- codziennie -->
    <akcja dni="PN WT SR" czas="GG:MM">           <!-- wybrane dni -->
    <akcja data="RRRR/MM/DD" czas="GG:MM">        <!-- JEDEN RAZ -->
      <grzanie pco="24.0" czas="180"/>            <!-- do temp. powrotu CO, maks. 180 min -->
      <grzanie pco="24.0" czas="-150"/>           <!-- czas ujemny: grzanie DO godziny akcji (akcja = stop) -->
      <grzanie pco="24.0"/>                       <!-- bez czasu: do temperatury -->
      <grzaniecwu .../>
      <pompy czas_kol="5" czas_co="5"/>           <!-- przepompowanie obiegów -->
    </akcja>
  </program>
</pompa>
```

- Akcja może mieć `wyjscia="001100XX00110001"` (16 znaków: 0/1/X) i `flagi="USR1,!USR3"` (warunek), `czas="1m"` / `"24h"` — akcje cykliczne.
- Grzanie może mieć `zew="-12"` i warunki `warunekstart` / `warunekstop` porównujące temperatury logiczne.
- Program pusty (bez akcji) — pompa nic nie robi z programu.

## Pułapki

- **Akcja bez `data` wykonuje się codziennie.** Ręczny start wgrany jako `<akcja czas="08:21">` w programie S grzał codziennie od stycznia do 2026-09-18.
- **Zegar sterownika** nie zmienia sam czasu letni/zimowy. 2026-09-18 spóźniał się 62 min — ustawiony na czas Pi (`ustrtc 2026/09/18-14:58:24-PI`). **Po zmianie czasu (ostatnia niedziela października i marca) trzeba go poprawić** — panel pokazuje żółte ostrzeżenie, gdy różnica przekracza 5 min. Polecenie na Pi:
  `~/dzarwisV2/kotek_rpi --adres 192.168.1.31 ustrtc "$(date +%Y/%m/%d-%H:%M:%S)-$(python3 -c 'import time;print(["PN","WT","SR","CZ","PI","SO","ND"][time.localtime().tm_wday])')"`
- W XML ze `status` numer aktywnego programu jest liczony od zera (`aktywnyProgram nr="3"` = program 4); w tekście (`aktprogram`) — od jedynki.
- `energia` podaje impulsy licznika; przelicznik na kWh zależy od stałej licznika (nieznana). Z logu: 2 h pracy sprężarki = 7563 impulsy.
- **Log sterownika nie zapisuje się od 2025-11-10 13:06** (sprawdzone 2026-09-18: 400 najnowszych wpisów obejmuje 2025-09-08…2025-11-10, bufor pełny — 32 768 pozycji). `wykonaneakcje` działa normalnie. Historii pracy pompy od listopada 2025 nie ma w sterowniku — panel musi zbierać własną. Kasowanie logu jest tylko przez tryb symulacji (`symuon 3`) — nie próbowane.
