# eBay Hub UK — Instrukcja obsługi

## Jak wejść do aplikacji

1. Otwórz przeglądarkę (Chrome, Safari, Firefox)
2. Wpisz adres który dostałeś (link ngrok)
3. Wpisz PIN i kliknij **Unlock**

## Dodawanie nowej palety (joblotu)

1. Kliknij **Pallets** w górnym menu
2. Kliknij **+ Add Pallet** (niebieski przycisk)
3. Wypełnij:
   - **Pallet Name** — nazwa palety, np. "Amazon Returns #5"
   - **Supplier** — dostawca, np. "Jobalots"
   - **Purchase Price** — cena zakupu w funtach (£)
   - **Purchase Date** — data zakupu
   - **Import Specification** — wybierz plik CSV lub XLSX od dostawcy
4. Kliknij **+ Add Pallet**
5. Poczekaj — aplikacja importuje produkty i ściąga zdjęcia z Amazon UK

## Ustawianie cen

1. Wejdź w paletę (kliknij na nią)
2. Sekcja **Set Prices** — lista produktów z polami ceny
3. Dwa sposoby:
   - **Ręcznie** — wpisz cenę przy każdym produkcie
   - **Mnożnik** — wpisz np. 2.5 w pole "Multiplier" → kliknij **Apply Multiplier** → aplikacja wyliczy cenę = koszt palety / ilość produktów × 2.5
4. Kliknij **Save All Prices**

## Wystawianie na eBay

**WAŻNE: Ustaw ceny PRZED wystawieniem! Na eBay nie ma szkiców — oferta od razu jest widoczna dla kupujących.**

### Cała paleta naraz:
1. Wejdź w paletę
2. Kliknij **List All on eBay** (zielony przycisk)
3. Poczekaj — aplikacja wystawia każdy produkt osobno
4. Zobaczysz komunikat ile wystawiono

### Pojedynczy produkt:
1. Kliknij w produkt
2. Ustaw tytuł, opis, cenę
3. Kliknij **List on eBay**

## Zamówienia

1. Kliknij **Orders** w górnym menu
2. Nowe zamówienia mają status **TO SHIP**
3. Spakuj paczkę, wyślij
4. Kliknij **Mark as Shipped** przy zamówieniu
5. Wpisz numer śledzenia przesyłki

## Dashboard

Strona główna pokazuje:
- Sprzedaż dziś / tydzień / miesiąc (w £)
- Aktywne oferty
- Zamówienia do wysłania
- Zamrożony kapitał
- Wykres przychodu

## Ustawienia

**Settings** → tutaj możesz:
- Zmienić PIN dostępu
- Zmienić domyślną wysyłkę (Royal Mail, Evri, DPD)
- Zmienić dni zwrotu (domyślnie 30)
- Zobaczyć backupy i przywrócić stary stan

## Backupy

- Aplikacja robi backup automatycznie co godzinę
- W **Settings** na dole widzisz listę backupów
- **Create Backup Now** — zrób backup ręcznie
- **Restore** — przywróć bazę z backupu
- **Download** — pobierz plik backupu na komputer

## Instalacja na telefonie (PWA)

1. Otwórz aplikację w przeglądarce na telefonie
2. **Android**: kliknij 3 kropki → "Add to Home Screen"
3. **iPhone**: kliknij ikona share → "Add to Home Screen"
4. Aplikacja będzie jak normalna apka na telefonie

## Rozwiązywanie problemów

**Nie mogę wejść na stronę:**
- Sprawdź czy masz internet
- Sprawdź czy link jest aktualny (ngrok zmienia URL po restarcie Pi)
- Skontaktuj się z Adrianem

**Zapomniałem PIN:**
- Skontaktuj się z Adrianem — zresetuje PIN

**Produkty nie mają zdjęć:**
- Wejdź w paletę → kliknij **Scrape Images**
- Poczekaj ~30 sekund na produkt

**Wystawianie nie działa:**
- Sprawdź czy klucze eBay API są w Settings
- Sprawdź czy produkt ma cenę > £0
- Sprawdź czy produkt ma tytuł
