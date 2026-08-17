# MAI Search - vyhledávání ve vaší stavební databázi

[![CI](https://github.com/mrYoriichi/mai-search/actions/workflows/ci.yml/badge.svg)](https://github.com/mrYoriichi/mai-search/actions/workflows/ci.yml)

[English](README.md) | **Čeština** | [Deutsch](README.de.md)

**⬇️ [Stáhnout pro Windows](https://github.com/mrYoriichi/mai-search/releases/latest)** - instalátor zdarma, bez předplatného.

> 🔧 **Pro inženýry a vývojáře:** technický popis - stack, RAG pipeline,
> architektonická rozhodnutí - je v [ARCHITECTURE.md](ARCHITECTURE.md)
> (anglicky). Tato stránka popisuje produkt pro jeho uživatele.

Vytvořte si z vlastní stavební dokumentace lokální databázi a hledejte v ní
z jednoho místa. Dokumenty, projekty, výkresy - nezáleží na tom, jestli jsou
naskenované, nebo ne.

Zeptáte se běžným jazykem a dostanete stručnou odpověď s odkazem na konkrétní
stránku konkrétního dokumentu. Už si nemusíte vzpomínat, ve kterém souboru to
bylo, ani listovat stovkami stran. Hledá se podle klíčových slov i podle
významu, takže se můžete ptát tak, jak byste se zeptali kolegy, aniž byste
hádali formulaci použitou v dokumentu.

![Vyhledávání](docs/screenshots/search.png)

## Čím se to liší od běžného ChatGPT

Když do ChatGPT nahrajete 100 dokumentů, musí je při každé otázce znovu celé
přečíst - je to pomalé a drahé a celá knihovna dokumentů se tam stejně
nevejde.

Tady vyhledávání v dokumentech dělá kód a ChatGPT jen formuluje odpověď
z nalezených úryvků. Proto je to rychlé, levné a přesné v odkazu na zdroj.

## Formáty dokumentů

Současná verze pracuje s PDF. Uvnitř může být cokoli - text, skeny, schémata,
tabulky, výkresy, rohová razítka, ručně psané poznámky - všechno se přečte,
asistent si to zapamatuje a použije to při hledání. Naskenované stránky, které
neobsahují skutečný text, se rozpoznají automaticky. U výkresů a schémat navíc
AI sepíše popis - co je nakresleno, jaký objekt, jaký stupeň - a právě tento
popis pak pomáhá najít ten správný list. Ruční písmo se přečte natolik,
nakolik ho AI rozluští.

## Soukromí

Asistent se instaluje a běží lokálně na vašem počítači a pracuje s dokumenty
na vašem počítači. Databáze i všechno, co si asistent z vašich dokumentů
zapamatoval, zůstává u vás; žádné cloudové úložiště neexistuje.

Odpovědi formuluje ChatGPT (OpenAI API). Vaše dokumenty jsou rozdělené na malé
úryvky a odesílá se jen těch několik úryvků, které se týkají vaší otázky -
přímo do OpenAI na váš vlastní klíč, bez jakéhokoli serveru autora a bez
služeb třetích stran mezi tím.

Je nutná bezplatná registrace, a to jen proto, aby autor viděl, že se aplikace
skutečně používá. Autor nevidí ani vaše dokumenty, ani otázky, ani názvy
souborů: aplikace odesílá anonymní statistiku - jak často se co spustilo,
kolik to zabralo času a peněz, jaké nastaly chyby.

Váš klíč OpenAI je ve vašem počítači uložený zašifrovaný Windows a svázaný
s vaším uživatelským účtem: datový soubor aplikace zkopírovaný na jiný
počítač nebo otevřený pod jiným účtem klíč neprozradí. Programy běžící pod
vaším vlastním účtem ho použít mohou - stejně jako u jakéhokoli uloženého
hesla - počítač samotný proto držte důvěryhodný. Pokud klíč přesto unikne,
zrušte ho ve svém účtu OpenAI a vytvořte nový.

## Cena

Samotná aplikace je zdarma a autor z ní nic nemá. Platíte pouze OpenAI, a to
přímo: jednou za zpracování dokumentů a potom centy za dotazy.

| Akce | gpt-5.6-luna (výchozí) | gpt-5.6-sol |
|---|---|---|
| Zpracování stránky se schématy a tabulkami | ~$0.002 | ~$0.04 |
| Zpracování výkresového listu | ~$0.002 | ~$0.04 |
| Jeden dotaz | ~$0.002 | ~$0.03 |
| Dotaz se silným hledáním | ~$0.003 | ~$0.07 |

Stránky s prostým textem jsou téměř zdarma. Dokument o 300 stranách vyjde s
výchozím modelem jednorázově na desítky centů (s gpt-5.6-sol na pár dolarů);
celý pracovní den dotazů stojí centy.

## Jak to funguje

**1. Ukážete na složku** - nebo na několik: vlastní dokumenty, celé projekty,
nebo firemní síťovou složku. Složka se zpracuje a vedle ní vznikne kopie,
které asistent rozumí - v té pak hledá. Vaše soubory se pouze čtou: nic se
nemění a nikam se nekopíruje.

![Knihovna](docs/screenshots/library.png)

Hotové projekty mají vlastní záložku: jedna připojená složka = jeden projekt
s jeho TZ, výpočty a výkresy.

![Archiv projektů](docs/screenshots/archive.png)

Pokud je složka sdílená, zaplatí zpracování jen ten první - ostatní připojí
tutéž složku a hotový výsledek převezmou zdarma.

**2. Vyberete, kde hledat** - v celé databázi, nebo jen v konkrétních
dokumentech. A jak: podle klíčových slov, podle významu, nebo obojím.
K dispozici je i silné hledání, kdy se asistent podívá i na samotné stránky
a dokáže říct, co je na listu nakresleno nebo jaký rozměr udává tabulka.

**3. Dostanete stručnou odpověď** a odkaz na zdroj - přímo na tu stránku, ze
které odpověď pochází. Ptát se můžete v libovolném jazyce; jazyk odpovědi se
volí nezávisle na jazyce rozhraní (angličtina, čeština, němčina).

**Kolik se toho vejde.** Veřejná verze pojme celkem 5000 stran - knihovna
a archiv projektů dohromady. Všechno, co si asistent zapamatoval, drží
v paměti, aby hledání bylo okamžité, a právě to určuje limit. Dokumenty nad
limit zůstanou v seznamu s označením a jen se v nich nehledá.

## Jak začít

1. **Stáhněte si instalátor** pro Windows - nepotřebuje práva správce.
   *(Veřejná verze se připravuje a objeví se na stránce
   [Releases](https://github.com/mrYoriichi/mai-search/releases).)*
2. **Zaregistrujte se** při prvním spuštění - e-mail a heslo, zdarma, bez
   předplatného.
3. **Získejte klíč OpenAI:** založte účet na
   [platform.openai.com](https://platform.openai.com) → **Billing → Add
   credits** ($5 vydrží dlouho) → **API keys → Create new secret key** → klíč
   vložte v aplikaci do **Nastavení**. Ukládá se pouze na vašem počítači.
4. **Připojte složku** s dokumenty, stiskněte **Skenovat** a potom
   **Indexovat**.

**Aplikace se otevírá v okně prohlížeče - to je jen její rozhraní, ne web.**
Program je nainstalovaný na vašem počítači a běží tam; prohlížeč slouží pouze
jako okno.

## O autorovi

Aplikaci vytvořil mostní inženýr pro projektanty, z vlastní každodenní
potřeby. Veřejná verze pro Windows je zdarma.

## Pro vývojáře

Architektura, inženýrská rozhodnutí, naměřená čísla a spuštění ze zdrojových
kódů: **[ARCHITECTURE.md](ARCHITECTURE.md)** (anglicky). Sestavení instalátoru
pro Windows: [BUILD.md](BUILD.md).

## Licence

[PolyForm Internal Use 1.0.0](LICENSE.md) - zdarma pro použití uvnitř vaší
organizace, včetně komerčních firem; prodej softwaru nebo jeho nabízení třetím
stranám jako produkt či službu zůstává autorovi.
