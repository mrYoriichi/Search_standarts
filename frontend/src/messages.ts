// UI string dictionaries: Czech (reference), English, German.
// Keys are semantic, grouped by page prefix.
// {name} placeholders are filled by t() from i18n.tsx.

export type Lang = 'cs' | 'en' | 'de'

const cs = {
  // Common
  'common.networkError': 'Chyba sítě',
  'common.errorStatus': 'Chyba {status}',
  'common.serverReturned': 'Server vrátil {status}',
  'common.unknownError': 'Neznámá chyba',
  'common.loading': 'Načítání…',
  'common.cancel': 'Zrušit',
  'common.saveTitle': 'Uložit',
  'common.logout': 'Odhlásit se',

  // Header and tabs
  'nav.search': 'Vyhledávání',
  'nav.library': 'Knihovna',
  'nav.archive': 'Archiv projektů',
  'header.settingsTitle': 'Nastavení',
  'theme.toLight': 'Světlý režim',
  'theme.toDark': 'Tmavý režim',

  // Blocked overlay
  'blocked.title': 'Přístup zablokován',
  'blocked.revoked': 'Přístup byl odebrán administrátorem.',
  'blocked.updateRequired':
    'Je dostupná nová verze aplikace. Nainstalujte ji, abyste mohli pokračovat.',
  'blocked.offline':
    'Spojení s licenčním serverem chybí déle než 1 den. Připojte se k internetu.',
  'blocked.user': 'Uživatel:',
  'blocked.download': 'Stáhnout aktualizaci →',

  // Search
  'search.where': 'Kde hledat',
  'search.noDocs':
    'Žádné indexované dokumenty. Přejděte do „Knihovny“ a klikněte na „Skenovat“.',
  'search.wholeDb': 'Celá databáze',
  'search.ownLibrary': 'Vlastní knihovna',
  'search.mode': 'Režim hledání',
  'search.modeHybrid': 'Hybridní',
  'search.modeVector': 'Podle významu',
  'search.modeKeyword': 'Podle slov',
  'search.answerModel': 'Model odpovědi',
  'lang.cs': 'Čeština',
  'lang.en': 'English',
  'lang.de': 'Deutsch',
  'search.expand': 'Rozšířit dotaz (diakritika, synonyma) před hledáním',
  'search.strong':
    'Silné hledání — přiložit snímky stránek zdrojů (pomalejší, dražší)',
  'search.placeholder': 'Zadejte dotaz ke stavebním normám...',
  'search.asking': 'Hledám...',
  'search.ask': 'Zeptat se',
  'search.selectWhere':
    'Vyberte, kde hledat — zaškrtněte „Celá databáze“ nebo vyberte dokumenty.',
  'search.searchedAs': 'Hledáno jako:',
  'search.modelLine': 'Model: {model} · {seconds} s',
  'search.answer': 'Odpověď',
  'search.sources': 'Zdroje',
  'search.noAnswer': 'Model nenašel odpověď v nalezených úryvcích.',
  'search.related': 'Související',

  // Source links
  'source.openPdf': 'Otevřít PDF',
  'source.openPdfPage': 'Otevřít PDF na straně {page}',
  'source.pagesPrefix': ' / s. ',

  // "Nahlásit" under the answer
  'report.link': 'Odpověď nepomohla / nenašlo se to — nahlásit',
  'report.prompt': 'Co bylo špatně? (nepovinné — např. „mělo by být v MVL649, odd. 4“)',
  'report.sending': 'Odesílám…',
  'report.send': 'Odeslat hlášení',
  'report.thanks': 'Děkujeme, hlášení bylo odesláno.',
  'report.failed': 'Nepodařilo se odeslat hlášení.',

  // Login / registration
  'login.title': 'Přihlášení do aplikace',
  'login.registerTitle': 'Registrace nového účtu',
  'login.fullName': 'Jméno a příjmení',
  'login.email': 'E-mail',
  'login.username': 'Přihlašovací jméno',
  'login.password': 'Heslo',
  'login.passwordHint': 'Alespoň 8 znaků.',
  'login.company': 'Společnost',
  'login.position': 'Pozice',
  'login.linkedin': 'LinkedIn',
  'login.optionalSuffix': ' (nepovinné)',
  'login.submitting': 'Přihlašuji...',
  'login.registering': 'Registruji...',
  'login.submit': 'Přihlásit se',
  'login.register': 'Zaregistrovat se',
  'login.haveAccount': 'Máte účet? Přihlaste se',
  'login.noAccount': 'Nemáte účet? Zaregistrujte se',
  'login.badCredentials': 'Nesprávné přihlašovací jméno nebo heslo',
  'login.revoked': 'Přístup byl odebrán. Obraťte se na administrátora.',
  'login.emailTaken': 'Tento e-mail je již zaregistrovaný.',
  'login.badData':
    'Zkontrolujte údaje: platný e-mail, heslo alespoň 8 znaků, vyplněné jméno, firma a pozice.',
  'login.serverDown': 'Licenční server není dostupný. Zkuste to později.',
  'login.errorStatus': 'Chyba: {status}',
  'login.appUnreachable': 'Nepodařilo se spojit s aplikací.',
  'login.updateTitle': 'Nainstalujte novou verzi',
  'login.updateText':
    'Je dostupná povinná verze aplikace. Přihlásit se lze až po aktualizaci.',
  'login.updateNoLink': 'Odkaz zatím není dostupný. Obraťte se na administrátora.',

  // Settings — profile
  'settings.profile': 'Profil',
  'settings.name': 'Jméno',
  'settings.linkedinOptional': 'LinkedIn (nepovinné)',
  'settings.saving': 'Ukládání...',
  'settings.saveProfile': 'Uložit profil',
  'settings.profileSaved': 'Profil byl uložen.',
  'settings.profileLoadFailed': 'Profil se nepodařilo načíst.',
  'settings.profileSaveFailed': 'Uložení profilu selhalo.',
  'settings.appUnavailable': 'Aplikace není dostupná. Zkuste to později.',

  // Settings — password
  'settings.changePassword': 'Změna hesla',
  'settings.currentPassword': 'Současné heslo',
  'settings.newPassword': 'Nové heslo (min. 8 znaků)',
  'settings.changePasswordBtn': 'Změnit heslo',
  'settings.passwordChanged': 'Heslo bylo změněno.',
  'settings.passwordChangeFailed': 'Změna hesla selhala.',

  // Settings — OpenAI key
  'settings.answerLang': 'Jazyk odpovědi',
  'settings.answerLangText':
    'V tomto jazyce bude asistent odpovídat na dotazy.',
  'settings.openaiKey': 'Klíč OpenAI',
  'settings.openaiKeyText':
    'Klíč se ukládá pouze na vašem počítači. Náklady na dotazy se účtují na tento klíč.',
  'settings.currentKey': 'Aktuální klíč: {masked}',
  'settings.keyNotSet': 'Klíč zatím není nastaven.',
  'settings.saveKey': 'Uložit klíč',
  'settings.keySaved': 'Klíč byl uložen.',
  'settings.keySaveFailed': 'Uložení klíče selhalo.',

  // Library
  'lib.openFailed': 'Nepodařilo se otevřít soubor',
  'lib.pinFailed': 'Nepodařilo se přepnout připnutí: {status}',
  'lib.reindexConfirm':
    'Přeindexovat „{title}“?\n\nStaré úryvky a embeddingy budou smazány a dokument se zpracuje znovu. Trvá to 5–10 minut a stojí přibližně $0.50–$1.50.',
  'lib.retryConfirm':
    'Pokračovat v indexaci „{title}“?\n\nHotové stránky jsou uložené — zaplatí se jen ty nezpracované.',
  'lib.deleteConfirm':
    'Odebrat „{title}“ z indexu?\n\nSamotné PDF ve složce knihovny zůstane. Úryvky a embeddingy budou smazány.',
  'lib.orphanGone': 'soubor odstraněn ze složky',
  'lib.removeFromIndex': 'Odebrat z indexu',
  'lib.orphanHint': 'Pro přejmenování vložte nový soubor do složky knihovny.',
  'lib.isRename': 'Je to přejmenování?',
  'lib.chooseNewName': '— vyberte nový název —',
  'lib.relink': 'Propojit',
  'lib.unpin': 'Odepnout',
  'lib.pin': 'Připnout',
  'lib.openInViewer': 'Otevřít v systémovém prohlížeči',
  'lib.reindexTitle': 'Přeindexovat',
  'status.notIndexed': 'neindexováno',
  'status.pending': 'čeká na indexaci',
  'status.processing': 'zpracovává se…',
  'status.failed': 'chyba',
  'status.ready': 'hotovo',
  'lib.empty': 'prázdné',
  'lib.scanNoNew': 'Žádné nové PDF nenalezeny (již v indexu: {n}).',
  'lib.scanFound':
    'Nalezeno {n} nových PDF — zkontrolujte seznam a spusťte tlačítkem „Indexovat“.',
  'lib.scanAdopted': 'Převzato {n} hotových indexů ze složky (bez indexace, zdarma).',
  'lib.scanLimit':
    '⚠️ {n} dokumentů se nevešlo do limitu veřejné verze (3000 stran) — nebyly převzaty.',
  'lib.scanDuplicates':
    '⚠️ Přeskočeny soubory se stejnými názvy — přejmenujte je, aby je bylo možné rozlišit:',
  'lib.lockedMsg':
    'Indexaci právě provádí jiný počítač — tyto složky se přeskočily:\n\n{list}\n\nZkuste to znovu později.',
  'lib.overLimitMsg':
    '{n} dokumentů se nevešlo do limitu veřejné verze (3000 stran) — nebyly indexovány. Uvolněte místo smazáním nepotřebných dokumentů.',
  'lib.removePathConfirm':
    'Odpojit složku od knihovny?\n{path}\n\nIndexy na disku zůstanou.',
  'lib.folders': 'Složky knihovny',
  'lib.foldersText':
    'Všechna PDF z těchto složek (a podsložek) se objeví v knihovně. Můžete připojit více složek (např. vlastní normy + složku firmy).',
  'lib.editPath': 'Upravit cestu',
  'lib.detachFolder': 'Odpojit složku',
  'lib.adding': 'Přidávám…',
  'lib.addFolder': 'Přidat složku',
  'lib.orphans': 'Osiřelé dokumenty',
  'lib.orphansText':
    'Tyto dokumenty jsou v indexu, ale soubory ve složce nebyly nalezeny. Možná jste je přejmenovali nebo smazali.',
  'lib.pinned': 'Připnuté',
  'lib.contents': 'Obsah',
  'lib.starting': 'Spouštím…',
  'lib.indexN': 'Indexovat ({n})',
  'lib.scanning': 'Skenuji…',
  'lib.scan': 'Skenovat',
  'lib.loadFailed': 'Nepodařilo se načíst knihovnu',

  // Project archive
  'arch.reindexConfirm':
    'Přeindexovat „{title}“?\n\nStaré úryvky a embeddingy budou smazány a dokument se zpracuje znovu. Popisy stránek (vision) se platí znovu.',
  'arch.openPdf': 'Otevřít PDF v prohlížeči',
  'arch.pages': '{n} s.',
  'arch.folders': 'Složky projektů',
  'arch.foldersText':
    'Každá připojená složka = jeden projekt: indexují se všechny PDF uvnitř včetně podsložek (TZ, statické výpočty, výkresy). Můžete připojit více projektů. Soubory se pouze čtou. Zpracování výkresů využívá vision model (viz „Knihovna“).',
  'arch.removePathConfirm': 'Odpojit složku archivu?\n{path}\n\nIndexy zůstanou.',
  'arch.summary': 'Nalezeno {found}, nových {fresh}',
  'arch.summaryChanged': ', nahrazeno {n} (vráceno k indexaci)',
  'arch.summaryMissing': ', odstraněno {n}',
  'arch.summaryDuplicates': ', duplicit {n}',
  'arch.summaryErrors': ', chyb {n}',
  'arch.unavailable': 'Nedostupné složky (úklid přeskočen): {list}',
  'arch.myProjects': 'Moje projekty',
  'arch.noDocs': 'Zatím žádné dokumenty — klikněte na „Skenovat“.',
  'arch.docCount': '{n} dokumentů',
  'arch.processingCount': ' · zpracovává se {n}',
  'arch.errorCount': ' · chyb {n}',
  'arch.loadFailed': 'Nepodařilo se načíst archiv',

  // Indexing settings (modal)
  'idx.button': 'Nastavení indexace',
  'idx.close': 'Zavřít',
  'idx.scope': 'Platí pro knihovnu i archiv projektů.',
  'idx.visionModel': 'Model pro zpracování (vision)',
  'idx.visionModelText':
    'Použije se při skenování dokumentů. Vision tvoří ~99 % ceny dokumentu — „gpt-5.4-mini“ je výrazně levnější, „gpt-5.5“ kvalitnější.',
  'idx.describeImages': 'Popis obrázků a výkresů (vision)',
  'idx.describeImagesText':
    '„Standardní“ nechá vision popsat schémata a výkresy (lepší vyhledávání, vision tvoří ~99 % ceny). „Bez LLM“ použije jen OCR a text — zdarma.',
  'idx.standard': 'Standardní (s popisem)',
  'idx.noLlm': 'Bez LLM (jen OCR)',
}

export type MsgKey = keyof typeof cs

const en: Record<MsgKey, string> = {
  'common.networkError': 'Network error',
  'common.errorStatus': 'Error {status}',
  'common.serverReturned': 'Server returned {status}',
  'common.unknownError': 'Unknown error',
  'common.loading': 'Loading…',
  'common.cancel': 'Cancel',
  'common.saveTitle': 'Save',
  'common.logout': 'Log out',

  'nav.search': 'Search',
  'nav.library': 'Library',
  'nav.archive': 'Project archive',
  'header.settingsTitle': 'Settings',
  'theme.toLight': 'Light mode',
  'theme.toDark': 'Dark mode',

  'blocked.title': 'Access blocked',
  'blocked.revoked': 'Access has been revoked by the administrator.',
  'blocked.updateRequired':
    'A new version of the app is available. Install it to continue.',
  'blocked.offline':
    'No connection to the license server for more than 1 day. Connect to the internet.',
  'blocked.user': 'User:',
  'blocked.download': 'Download update →',

  'search.where': 'Where to search',
  'search.noDocs':
    'No indexed documents. Go to “Library” and click “Scan”.',
  'search.wholeDb': 'Whole database',
  'search.ownLibrary': 'My library',
  'search.mode': 'Search mode',
  'search.modeHybrid': 'Hybrid',
  'search.modeVector': 'By meaning',
  'search.modeKeyword': 'By keywords',
  'search.answerModel': 'Answer model',
  'lang.cs': 'Čeština',
  'lang.en': 'English',
  'lang.de': 'Deutsch',
  'search.expand': 'Expand the query (diacritics, synonyms) before searching',
  'search.strong':
    'Strong search — attach page snapshots of the sources (slower, pricier)',
  'search.placeholder': 'Ask a question about construction standards...',
  'search.asking': 'Searching...',
  'search.ask': 'Ask',
  'search.selectWhere':
    'Choose where to search — tick “Whole database” or select documents.',
  'search.searchedAs': 'Searched as:',
  'search.modelLine': 'Model: {model} · {seconds} s',
  'search.answer': 'Answer',
  'search.sources': 'Sources',
  'search.noAnswer': 'The model found no answer in the retrieved excerpts.',
  'search.related': 'Related',

  'source.openPdf': 'Open PDF',
  'source.openPdfPage': 'Open PDF at page {page}',
  'source.pagesPrefix': ' / p. ',

  'report.link': 'The answer didn’t help / nothing found — report it',
  'report.prompt': 'What was wrong? (optional — e.g. “should be in MVL649, sec. 4”)',
  'report.sending': 'Sending…',
  'report.send': 'Send report',
  'report.thanks': 'Thank you, the report has been sent.',
  'report.failed': 'Failed to send the report.',

  'login.title': 'Sign in to the app',
  'login.registerTitle': 'Create a new account',
  'login.fullName': 'Full name',
  'login.email': 'E-mail',
  'login.username': 'Username',
  'login.password': 'Password',
  'login.passwordHint': 'At least 8 characters.',
  'login.company': 'Company',
  'login.position': 'Position',
  'login.linkedin': 'LinkedIn',
  'login.optionalSuffix': ' (optional)',
  'login.submitting': 'Signing in...',
  'login.registering': 'Registering...',
  'login.submit': 'Sign in',
  'login.register': 'Sign up',
  'login.haveAccount': 'Have an account? Sign in',
  'login.noAccount': 'No account? Sign up',
  'login.badCredentials': 'Incorrect username or password',
  'login.revoked': 'Access has been revoked. Contact the administrator.',
  'login.emailTaken': 'This e-mail is already registered.',
  'login.badData':
    'Check the details: a valid e-mail, password of at least 8 characters, and filled-in name, company and position.',
  'login.serverDown': 'The license server is unavailable. Try again later.',
  'login.errorStatus': 'Error: {status}',
  'login.appUnreachable': 'Could not reach the app.',
  'login.updateTitle': 'Install the new version',
  'login.updateText':
    'A mandatory app version is available. You can sign in only after updating.',
  'login.updateNoLink': 'The link is not available yet. Contact the administrator.',

  'settings.profile': 'Profile',
  'settings.name': 'Name',
  'settings.linkedinOptional': 'LinkedIn (optional)',
  'settings.saving': 'Saving...',
  'settings.saveProfile': 'Save profile',
  'settings.profileSaved': 'Profile saved.',
  'settings.profileLoadFailed': 'Failed to load the profile.',
  'settings.profileSaveFailed': 'Failed to save the profile.',
  'settings.appUnavailable': 'The app is unavailable. Try again later.',

  'settings.changePassword': 'Change password',
  'settings.currentPassword': 'Current password',
  'settings.newPassword': 'New password (min. 8 characters)',
  'settings.changePasswordBtn': 'Change password',
  'settings.passwordChanged': 'Password changed.',
  'settings.passwordChangeFailed': 'Password change failed.',

  'settings.answerLang': 'Answer language',
  'settings.answerLangText':
    'The assistant will answer questions in this language.',
  'settings.openaiKey': 'OpenAI key',
  'settings.openaiKeyText':
    'The key is stored only on your computer. Query costs are billed to this key.',
  'settings.currentKey': 'Current key: {masked}',
  'settings.keyNotSet': 'No key set yet.',
  'settings.saveKey': 'Save key',
  'settings.keySaved': 'Key saved.',
  'settings.keySaveFailed': 'Failed to save the key.',

  'lib.openFailed': 'Failed to open the file',
  'lib.pinFailed': 'Failed to toggle pin: {status}',
  'lib.reindexConfirm':
    'Re-index “{title}”?\n\nOld excerpts and embeddings will be deleted and the document will be processed again. It takes 5–10 minutes and costs roughly $0.50–$1.50.',
  'lib.retryConfirm':
    'Continue indexing “{title}”?\n\nFinished pages are saved — only the unprocessed ones are paid.',
  'lib.deleteConfirm':
    'Remove “{title}” from the index?\n\nThe PDF itself stays in the library folder. Excerpts and embeddings will be deleted.',
  'lib.orphanGone': 'file removed from the folder',
  'lib.removeFromIndex': 'Remove from index',
  'lib.orphanHint': 'To rename, put the new file into the library folder.',
  'lib.isRename': 'Is this a rename?',
  'lib.chooseNewName': '— choose the new name —',
  'lib.relink': 'Link',
  'lib.unpin': 'Unpin',
  'lib.pin': 'Pin',
  'lib.openInViewer': 'Open in the system viewer',
  'lib.reindexTitle': 'Re-index',
  'status.notIndexed': 'not indexed',
  'status.pending': 'waiting for indexing',
  'status.processing': 'processing…',
  'status.failed': 'error',
  'status.ready': 'done',
  'lib.empty': 'empty',
  'lib.scanNoNew': 'No new PDFs found (already indexed: {n}).',
  'lib.scanFound':
    'Found {n} new PDFs — review the list and start with the “Index” button.',
  'lib.scanAdopted': 'Adopted {n} ready-made indexes from the folder (no indexing, free).',
  'lib.scanLimit':
    '⚠️ {n} documents did not fit into the public version limit (3000 pages) — they were not adopted.',
  'lib.scanDuplicates':
    '⚠️ Files with identical names were skipped — rename them so they can be told apart:',
  'lib.lockedMsg':
    'Another computer is indexing right now — these folders were skipped:\n\n{list}\n\nTry again later.',
  'lib.overLimitMsg':
    '{n} documents did not fit into the public version limit (3000 pages) — they were not indexed. Free up space by deleting documents you don’t need.',
  'lib.removePathConfirm':
    'Detach the folder from the library?\n{path}\n\nIndexes stay on disk.',
  'lib.folders': 'Library folders',
  'lib.foldersText':
    'All PDFs from these folders (and subfolders) appear in the library. You can attach several folders (e.g. your own standards + a company folder).',
  'lib.editPath': 'Edit path',
  'lib.detachFolder': 'Detach folder',
  'lib.adding': 'Adding…',
  'lib.addFolder': 'Add folder',
  'lib.orphans': 'Orphaned documents',
  'lib.orphansText':
    'These documents are in the index, but their files were not found in the folder. You may have renamed or deleted them.',
  'lib.pinned': 'Pinned',
  'lib.contents': 'Contents',
  'lib.starting': 'Starting…',
  'lib.indexN': 'Index ({n})',
  'lib.scanning': 'Scanning…',
  'lib.scan': 'Scan',
  'lib.loadFailed': 'Failed to load the library',

  'arch.reindexConfirm':
    'Re-index “{title}”?\n\nOld excerpts and embeddings will be deleted and the document will be processed again. Page descriptions (vision) are paid again.',
  'arch.openPdf': 'Open the PDF in the browser',
  'arch.pages': '{n} p.',
  'arch.folders': 'Project folders',
  'arch.foldersText':
    'Each attached folder = one project: all PDFs inside are indexed, including subfolders (technical reports, structural calculations, drawings). You can attach several projects. Files are only read. Drawing processing uses the vision model (see “Library”).',
  'arch.removePathConfirm': 'Detach the archive folder?\n{path}\n\nIndexes stay.',
  'arch.summary': 'Found {found}, new {fresh}',
  'arch.summaryChanged': ', replaced {n} (returned to indexing)',
  'arch.summaryMissing': ', removed {n}',
  'arch.summaryDuplicates': ', duplicates {n}',
  'arch.summaryErrors': ', errors {n}',
  'arch.unavailable': 'Unavailable folders (cleanup skipped): {list}',
  'arch.myProjects': 'My projects',
  'arch.noDocs': 'No documents yet — click “Scan”.',
  'arch.docCount': '{n} documents',
  'arch.processingCount': ' · processing {n}',
  'arch.errorCount': ' · errors {n}',
  'arch.loadFailed': 'Failed to load the archive',

  'idx.button': 'Indexing settings',
  'idx.close': 'Close',
  'idx.scope': 'Applies to both the library and the project archive.',
  'idx.visionModel': 'Processing model (vision)',
  'idx.visionModelText':
    'Used when scanning documents. Vision makes up ~99% of a document’s cost — “gpt-5.4-mini” is much cheaper, “gpt-5.5” higher quality.',
  'idx.describeImages': 'Description of images and drawings (vision)',
  'idx.describeImagesText':
    '“Standard” lets vision describe schemes and drawings (better search, vision makes up ~99% of the cost). “No LLM” uses only OCR and text — free.',
  'idx.standard': 'Standard (with descriptions)',
  'idx.noLlm': 'No LLM (OCR only)',
}

const de: Record<MsgKey, string> = {
  'common.networkError': 'Netzwerkfehler',
  'common.errorStatus': 'Fehler {status}',
  'common.serverReturned': 'Server antwortete mit {status}',
  'common.unknownError': 'Unbekannter Fehler',
  'common.loading': 'Wird geladen…',
  'common.cancel': 'Abbrechen',
  'common.saveTitle': 'Speichern',
  'common.logout': 'Abmelden',

  'nav.search': 'Suche',
  'nav.library': 'Bibliothek',
  'nav.archive': 'Projektarchiv',
  'header.settingsTitle': 'Einstellungen',
  'theme.toLight': 'Heller Modus',
  'theme.toDark': 'Dunkler Modus',

  'blocked.title': 'Zugang gesperrt',
  'blocked.revoked': 'Der Zugang wurde vom Administrator entzogen.',
  'blocked.updateRequired':
    'Eine neue Version der App ist verfügbar. Installieren Sie sie, um fortzufahren.',
  'blocked.offline':
    'Seit mehr als einem Tag keine Verbindung zum Lizenzserver. Stellen Sie eine Internetverbindung her.',
  'blocked.user': 'Benutzer:',
  'blocked.download': 'Update herunterladen →',

  'search.where': 'Wo suchen',
  'search.noDocs':
    'Keine indexierten Dokumente. Öffnen Sie die „Bibliothek“ und klicken Sie auf „Scannen“.',
  'search.wholeDb': 'Gesamte Datenbank',
  'search.ownLibrary': 'Eigene Bibliothek',
  'search.mode': 'Suchmodus',
  'search.modeHybrid': 'Hybrid',
  'search.modeVector': 'Nach Bedeutung',
  'search.modeKeyword': 'Nach Stichwörtern',
  'search.answerModel': 'Antwortmodell',
  'lang.cs': 'Čeština',
  'lang.en': 'English',
  'lang.de': 'Deutsch',
  'search.expand': 'Anfrage vor der Suche erweitern (Diakritika, Synonyme)',
  'search.strong':
    'Starke Suche — Seitenabbilder der Quellen anhängen (langsamer, teurer)',
  'search.placeholder': 'Stellen Sie eine Frage zu Baunormen...',
  'search.asking': 'Suche läuft...',
  'search.ask': 'Fragen',
  'search.selectWhere':
    'Wählen Sie, wo gesucht wird — „Gesamte Datenbank“ ankreuzen oder Dokumente auswählen.',
  'search.searchedAs': 'Gesucht als:',
  'search.modelLine': 'Modell: {model} · {seconds} s',
  'search.answer': 'Antwort',
  'search.sources': 'Quellen',
  'search.noAnswer': 'Das Modell fand in den gefundenen Auszügen keine Antwort.',
  'search.related': 'Verwandte Quellen',

  'source.openPdf': 'PDF öffnen',
  'source.openPdfPage': 'PDF auf Seite {page} öffnen',
  'source.pagesPrefix': ' / S. ',

  'report.link': 'Die Antwort hat nicht geholfen / nichts gefunden — melden',
  'report.prompt': 'Was war falsch? (optional — z. B. „sollte in MVL649, Abschn. 4 sein“)',
  'report.sending': 'Wird gesendet…',
  'report.send': 'Meldung senden',
  'report.thanks': 'Danke, die Meldung wurde gesendet.',
  'report.failed': 'Die Meldung konnte nicht gesendet werden.',

  'login.title': 'Anmeldung in der App',
  'login.registerTitle': 'Neues Konto erstellen',
  'login.fullName': 'Vor- und Nachname',
  'login.email': 'E-Mail',
  'login.username': 'Benutzername',
  'login.password': 'Passwort',
  'login.passwordHint': 'Mindestens 8 Zeichen.',
  'login.company': 'Firma',
  'login.position': 'Position',
  'login.linkedin': 'LinkedIn',
  'login.optionalSuffix': ' (optional)',
  'login.submitting': 'Anmeldung läuft...',
  'login.registering': 'Registrierung läuft...',
  'login.submit': 'Anmelden',
  'login.register': 'Registrieren',
  'login.haveAccount': 'Schon ein Konto? Anmelden',
  'login.noAccount': 'Kein Konto? Registrieren',
  'login.badCredentials': 'Falscher Benutzername oder falsches Passwort',
  'login.revoked': 'Der Zugang wurde entzogen. Wenden Sie sich an den Administrator.',
  'login.emailTaken': 'Diese E-Mail ist bereits registriert.',
  'login.badData':
    'Prüfen Sie die Angaben: gültige E-Mail, Passwort mit mindestens 8 Zeichen, ausgefüllter Name, Firma und Position.',
  'login.serverDown': 'Der Lizenzserver ist nicht erreichbar. Versuchen Sie es später.',
  'login.errorStatus': 'Fehler: {status}',
  'login.appUnreachable': 'Die App konnte nicht erreicht werden.',
  'login.updateTitle': 'Neue Version installieren',
  'login.updateText':
    'Eine verpflichtende App-Version ist verfügbar. Die Anmeldung ist erst nach dem Update möglich.',
  'login.updateNoLink': 'Der Link ist noch nicht verfügbar. Wenden Sie sich an den Administrator.',

  'settings.profile': 'Profil',
  'settings.name': 'Name',
  'settings.linkedinOptional': 'LinkedIn (optional)',
  'settings.saving': 'Wird gespeichert...',
  'settings.saveProfile': 'Profil speichern',
  'settings.profileSaved': 'Profil gespeichert.',
  'settings.profileLoadFailed': 'Das Profil konnte nicht geladen werden.',
  'settings.profileSaveFailed': 'Das Profil konnte nicht gespeichert werden.',
  'settings.appUnavailable': 'Die App ist nicht erreichbar. Versuchen Sie es später.',

  'settings.changePassword': 'Passwort ändern',
  'settings.currentPassword': 'Aktuelles Passwort',
  'settings.newPassword': 'Neues Passwort (mind. 8 Zeichen)',
  'settings.changePasswordBtn': 'Passwort ändern',
  'settings.passwordChanged': 'Passwort geändert.',
  'settings.passwordChangeFailed': 'Passwortänderung fehlgeschlagen.',

  'settings.answerLang': 'Antwortsprache',
  'settings.answerLangText':
    'Der Assistent beantwortet Fragen in dieser Sprache.',
  'settings.openaiKey': 'OpenAI-Schlüssel',
  'settings.openaiKeyText':
    'Der Schlüssel wird nur auf Ihrem Computer gespeichert. Abfragekosten werden über diesen Schlüssel abgerechnet.',
  'settings.currentKey': 'Aktueller Schlüssel: {masked}',
  'settings.keyNotSet': 'Noch kein Schlüssel gesetzt.',
  'settings.saveKey': 'Schlüssel speichern',
  'settings.keySaved': 'Schlüssel gespeichert.',
  'settings.keySaveFailed': 'Der Schlüssel konnte nicht gespeichert werden.',

  'lib.openFailed': 'Die Datei konnte nicht geöffnet werden',
  'lib.pinFailed': 'Anheften konnte nicht umgeschaltet werden: {status}',
  'lib.reindexConfirm':
    '„{title}“ neu indexieren?\n\nAlte Auszüge und Embeddings werden gelöscht und das Dokument wird neu verarbeitet. Dauert 5–10 Minuten und kostet etwa $0.50–$1.50.',
  'lib.retryConfirm':
    'Indexierung von „{title}“ fortsetzen?\n\nFertige Seiten sind gespeichert — bezahlt werden nur die unverarbeiteten.',
  'lib.deleteConfirm':
    '„{title}“ aus dem Index entfernen?\n\nDie PDF-Datei selbst bleibt im Bibliotheksordner. Auszüge und Embeddings werden gelöscht.',
  'lib.orphanGone': 'Datei aus dem Ordner entfernt',
  'lib.removeFromIndex': 'Aus dem Index entfernen',
  'lib.orphanHint': 'Zum Umbenennen legen Sie die neue Datei in den Bibliotheksordner.',
  'lib.isRename': 'Ist das eine Umbenennung?',
  'lib.chooseNewName': '— neuen Namen wählen —',
  'lib.relink': 'Verknüpfen',
  'lib.unpin': 'Lösen',
  'lib.pin': 'Anheften',
  'lib.openInViewer': 'Im System-Viewer öffnen',
  'lib.reindexTitle': 'Neu indexieren',
  'status.notIndexed': 'nicht indexiert',
  'status.pending': 'wartet auf Indexierung',
  'status.processing': 'wird verarbeitet…',
  'status.failed': 'Fehler',
  'status.ready': 'fertig',
  'lib.empty': 'leer',
  'lib.scanNoNew': 'Keine neuen PDFs gefunden (bereits im Index: {n}).',
  'lib.scanFound':
    '{n} neue PDFs gefunden — prüfen Sie die Liste und starten Sie mit „Indexieren“.',
  'lib.scanAdopted': '{n} fertige Indexe aus dem Ordner übernommen (ohne Indexierung, kostenlos).',
  'lib.scanLimit':
    '⚠️ {n} Dokumente passten nicht in das Limit der öffentlichen Version (3000 Seiten) — sie wurden nicht übernommen.',
  'lib.scanDuplicates':
    '⚠️ Dateien mit gleichen Namen wurden übersprungen — benennen Sie sie um, damit sie unterscheidbar sind:',
  'lib.lockedMsg':
    'Ein anderer Computer indexiert gerade — diese Ordner wurden übersprungen:\n\n{list}\n\nVersuchen Sie es später erneut.',
  'lib.overLimitMsg':
    '{n} Dokumente passten nicht in das Limit der öffentlichen Version (3000 Seiten) — sie wurden nicht indexiert. Schaffen Sie Platz, indem Sie nicht benötigte Dokumente löschen.',
  'lib.removePathConfirm':
    'Ordner von der Bibliothek trennen?\n{path}\n\nIndexe bleiben auf der Festplatte.',
  'lib.folders': 'Bibliotheksordner',
  'lib.foldersText':
    'Alle PDFs aus diesen Ordnern (und Unterordnern) erscheinen in der Bibliothek. Sie können mehrere Ordner anbinden (z. B. eigene Normen + einen Firmenordner).',
  'lib.editPath': 'Pfad bearbeiten',
  'lib.detachFolder': 'Ordner trennen',
  'lib.adding': 'Wird hinzugefügt…',
  'lib.addFolder': 'Ordner hinzufügen',
  'lib.orphans': 'Verwaiste Dokumente',
  'lib.orphansText':
    'Diese Dokumente sind im Index, aber ihre Dateien wurden im Ordner nicht gefunden. Vielleicht wurden sie umbenannt oder gelöscht.',
  'lib.pinned': 'Angeheftet',
  'lib.contents': 'Inhalt',
  'lib.starting': 'Wird gestartet…',
  'lib.indexN': 'Indexieren ({n})',
  'lib.scanning': 'Scannen läuft…',
  'lib.scan': 'Scannen',
  'lib.loadFailed': 'Die Bibliothek konnte nicht geladen werden',

  'arch.reindexConfirm':
    '„{title}“ neu indexieren?\n\nAlte Auszüge und Embeddings werden gelöscht und das Dokument wird neu verarbeitet. Seitenbeschreibungen (Vision) werden erneut bezahlt.',
  'arch.openPdf': 'PDF im Browser öffnen',
  'arch.pages': '{n} S.',
  'arch.folders': 'Projektordner',
  'arch.foldersText':
    'Jeder angebundene Ordner = ein Projekt: alle PDFs darin werden indexiert, einschließlich Unterordner (technische Berichte, statische Berechnungen, Zeichnungen). Sie können mehrere Projekte anbinden. Dateien werden nur gelesen. Die Zeichnungsverarbeitung nutzt das Vision-Modell (siehe „Bibliothek“).',
  'arch.removePathConfirm': 'Archivordner trennen?\n{path}\n\nIndexe bleiben erhalten.',
  'arch.summary': 'Gefunden {found}, neu {fresh}',
  'arch.summaryChanged': ', ersetzt {n} (zurück zur Indexierung)',
  'arch.summaryMissing': ', entfernt {n}',
  'arch.summaryDuplicates': ', Duplikate {n}',
  'arch.summaryErrors': ', Fehler {n}',
  'arch.unavailable': 'Nicht erreichbare Ordner (Aufräumen übersprungen): {list}',
  'arch.myProjects': 'Meine Projekte',
  'arch.noDocs': 'Noch keine Dokumente — klicken Sie auf „Scannen“.',
  'arch.docCount': '{n} Dokumente',
  'arch.processingCount': ' · in Verarbeitung {n}',
  'arch.errorCount': ' · Fehler {n}',
  'arch.loadFailed': 'Das Archiv konnte nicht geladen werden',

  'idx.button': 'Indexierungseinstellungen',
  'idx.close': 'Schließen',
  'idx.scope': 'Gilt für die Bibliothek und das Projektarchiv.',
  'idx.visionModel': 'Verarbeitungsmodell (Vision)',
  'idx.visionModelText':
    'Wird beim Scannen der Dokumente verwendet. Vision macht ~99 % der Dokumentkosten aus — „gpt-5.4-mini“ ist deutlich günstiger, „gpt-5.5“ hochwertiger.',
  'idx.describeImages': 'Beschreibung von Bildern und Zeichnungen (Vision)',
  'idx.describeImagesText':
    '„Standard“ lässt Vision Schemata und Zeichnungen beschreiben (bessere Suche, Vision macht ~99 % der Kosten aus). „Ohne LLM“ nutzt nur OCR und Text — kostenlos.',
  'idx.standard': 'Standard (mit Beschreibung)',
  'idx.noLlm': 'Ohne LLM (nur OCR)',
}

export const dictionaries: Record<Lang, Record<MsgKey, string>> = { cs, en, de }
