# Pompa ciepła — `kotek_rpi`

Poza repozytorium, w katalogu `/home/pi/dzarwisV2` na Pi, leży narzędzie do sterownika pompy ciepła. Nie jest częścią kodu Pythona i nie działa automatycznie — używane jest ręcznie z konsoli.

| | |
|---|---|
| Program | `kotek_rpi` — plik wykonywalny ARM (32-bit), z 2018 r., zewnętrzny (brak źródeł w repo) |
| Sterownik pompy | `192.168.1.31`, osiągalny przez `eth1` Pi (192.168.1.30) |
| Pliki programów | `*.xml` w katalogu projektu, nieśledzone przez git |

## Polecenia (z historii powłoki)

```bash
./kotek_rpi --adres 192.168.1.31 status
./kotek_rpi --adres 192.168.1.31 odczytczujnikow
./kotek_rpi --adres 192.168.1.31 listaprogramow
./kotek_rpi --adres 192.168.1.31 czytajprogram 1        # 1–4 lub S
./kotek_rpi --adres 192.168.1.31 program prog2026.xml   # wgranie programu
./kotek_rpi --adres 192.168.1.31 ustrtc 2026/01/06-08:18:00-WT   # ustawienie zegara
```

## Format plików XML

Opis jest w komentarzu na początku `pompa.xml`. W skrócie:

```xml
<pompa CfgVer="1.0">
  <program numer="1" opis="do 20 znakow">   <!-- numer: 1–4 lub S (stały, zawsze aktywny) -->
    <akcja czas="GG:MM">                      <!-- albo dni="PN WT ..." albo data="YYYY/MM/DD" -->
      <grzanie pco="24.0" czas="180"/>        <!-- grzanie CO do 24 °C przez 180 min -->
      <pompy czas_kol="5" czas_co="5"/>       <!-- przepompowanie obiegów -->
    </akcja>
  </program>
</pompa>
```

Opcjonalny atrybut akcji `wyjscia="001100XX00110001"` (16 znaków: `0` wyłącz, `1` włącz, `X` bez zmian) ustawia wyjścia triakowe (1–8) i MOS (9–16).

## Pliki na Pi

| Plik | Zawartość |
|---|---|
| `pompa.xml`, `prog.xml` | identyczne (styczeń 2024), pełny opis formatu |
| `progrma.xml`, `programspec.xml` | identyczne (2023/2024) |
| `progspec.xml` | wersja z 2026-01 |
| `prog2026.xml` | aktualny program na 2026: harmonogram grzania CO do 24 °C (m.in. 10:00, 22:00) i przepompowań obiegów |
| `pompaspecjal.xml` | program specjalny S: grzanie do 24 °C o 8:21 |

Pliki programów warto dodać do repozytorium (np. katalog `pompa/`), żeby mieć ich historię.
