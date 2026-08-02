# MAI Assistant

[English](README.md) | **Čeština** | [Deutsch](README.de.md)

Zeptejte se na stavební normy běžným jazykem — dostanete stručnou odpověď
s odkazem na konkrétní dokument, kapitolu a stránku. Konec listování
třísetstránkovými PDF.

Aplikace pro stavební inženýry pracující s ČSN, Eurokódy a vlastními
archivy projektů. Autor je mostní inženýr; aplikaci denně používá
skutečná projekční kancelář.

**Vaše dokumenty nikdy neopouštějí váš počítač.** Index i databáze běží
lokálně; žádné cloudové úložiště neexistuje a nikdo — ani autor — vaše
soubory a dotazy nevidí. Jediný odchozí provoz jsou volání OpenAI API
s vaším vlastním klíčem.

![Vyhledávání](docs/screenshots/search.png)

## Co umí

- **Otázka v libovolném jazyce** — odpověď cituje zdroj a odkazuje přímo
  na stránku v původním PDF.
- **Hybridní vyhledávání** — přesné kódy („ČSN 73 6201“) i význam.
- **Rozumí výkresům** — OCR + vision model popíše každý list (co je
  nakresleno, stupeň, objekt).
- **Archiv projektů** — hledejte ve svých hotových projektech (TZ,
  statické výpočty, výkresy) společně s normami.
- **Sdílená firemní knihovna** — jeden kolega naindexuje síťovou složku,
  ostatní hotový index převezmou zdarma.
- **Silné hledání** — u těžkých dotazů na výkresy a tabulky dostane
  odpovídající model i snímky stránek.
- **3 jazyky rozhraní** (EN/CS/DE) + samostatný jazyk odpovědi.
- **Lokální provoz** — index, databáze i dokumenty zůstávají u vás.

![Knihovna](docs/screenshots/library.png)
![Archiv projektů](docs/screenshots/archive.png)

## Klíč OpenAI API

Aplikace běží na vašem vlastním klíči OpenAI — platíte přímo OpenAI,
aplikace si nic nepřidává.

1. Založte účet na [platform.openai.com](https://platform.openai.com).
2. **Billing → Add credits** — předplaťte malou částku (minimum $5 vydrží
   dlouho).
3. **API keys → Create new secret key** — zkopírujte klíč `sk-…`.
4. Vložte ho v aplikaci do **Nastavení → Klíč OpenAI**. Ukládá se pouze
   na vašem počítači.

Naměřené ceny s výchozím modelem:

| Akce | Cena |
|---|---|
| Indexace textové normy | ~$0.04 za stránku se schématy, prostý text méně |
| Indexace výkresu | < $0.01 za list |
| Jeden dotaz | < $0.01 |
| Dotaz se silným hledáním | ~$0.04 |

## Soukromí a telemetrie

- Dokumenty, index i databáze nikdy neopouštějí váš počítač. Úryvky
  textu a snímky stránek jdou pouze do **OpenAI API** na váš klíč.
- Je nutná bezplatná registrace; aplikace odesílá **anonymní telemetrii**
  (počty událostí, časy, ceny, typy chyb — nikdy texty dotazů ani názvy
  souborů).
- Nedostupný licenční server aplikaci nikdy nezablokuje.
- Veřejná verze indexuje až **3000 stran** (bezpečnostní limit paměti).

## Stav

Pilotní provoz v mostní projekční kanceláři (ČR) na skutečných normách
a projektech. Veřejná bezplatná verze pro Windows se připravuje.

Technické detaily (architektura, spuštění ze zdrojáků):
[anglické README](README.md).

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE.md) — pro nekomerční použití
zdarma; komerční práva zůstávají autorovi.
