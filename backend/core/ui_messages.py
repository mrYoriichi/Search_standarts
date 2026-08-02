"""Backend texts for the UI in three languages (en — default and fallback).

The backend cannot know each HTTP request's language, so it is one
value: the frontend PUTs /api/settings/language on switch, the value
persists in settings (survives restarts) and lives in a module global
(read when a text is built). Errors already written to the DB
(Document.error_message of failed documents) keep the language of the
moment they happened — history is not rewritten.

Keys mirror frontend/src/messages.ts in spirit: short id → texts.
"""

LANGS = ("cs", "en", "de")

_current = "en"


def set_language(lang: str) -> None:
    """Set the current language; unknown codes are silently ignored
    (second guard behind the endpoint's Literal validation)."""
    global _current
    if lang in LANGS:
        _current = lang


def get_language() -> str:
    return _current


MESSAGES: dict[str, dict[str, str]] = {
    # --- pipeline error classifier (backend/core/errors.py) ---
    "err.bad_api_key": {
        "cs": "Neplatný OpenAI API klíč — zkontrolujte ho v Nastavení.",
        "en": "Invalid OpenAI API key — check it in Settings.",
        "de": "Ungültiger OpenAI-API-Schlüssel — prüfen Sie ihn in den Einstellungen.",
    },
    "err.no_credit": {
        "cs": "Na OpenAI klíči došel kredit — dobijte na platform.openai.com.",
        "en": "The OpenAI key has run out of credit — top up at platform.openai.com.",
        "de": "Das Guthaben des OpenAI-Schlüssels ist aufgebraucht — aufladen auf platform.openai.com.",
    },
    "err.rate_limit": {
        "cs": "Překročen limit požadavků OpenAI — zkuste to za chvíli znovu.",
        "en": "OpenAI request limit exceeded — try again in a moment.",
        "de": "OpenAI-Anfragelimit überschritten — versuchen Sie es gleich erneut.",
    },
    "err.no_connection": {
        "cs": "Nepodařilo se připojit k OpenAI — zkontrolujte internet.",
        "en": "Could not connect to OpenAI — check your internet connection.",
        "de": "Keine Verbindung zu OpenAI — prüfen Sie Ihre Internetverbindung.",
    },
    "err.missing_api_key": {
        "cs": "Chybí OpenAI API klíč — nastavte ho v Nastavení.",
        "en": "OpenAI API key is missing — set it in Settings.",
        "de": "OpenAI-API-Schlüssel fehlt — legen Sie ihn in den Einstellungen fest.",
    },
    "err.vision_empty": {
        "cs": "Vision nevrátil popis stránky — zkuste dokument indexovat znovu.",
        "en": "Vision returned no page description — try indexing the document again.",
        "de": "Vision lieferte keine Seitenbeschreibung — indexieren Sie das Dokument erneut.",
    },
    "err.pdf_password": {
        "cs": "PDF je chráněno heslem — odemkněte ho a naskenujte znovu.",
        "en": "The PDF is password-protected — unlock it and scan again.",
        "de": "Die PDF ist passwortgeschützt — entsperren Sie sie und scannen Sie erneut.",
    },
    "err.pdf_open": {
        "cs": "Soubor se nepodařilo otevřít jako PDF.",
        "en": "The file could not be opened as a PDF.",
        "de": "Die Datei konnte nicht als PDF geöffnet werden.",
    },
    "err.pdf_read": {
        "cs": "Soubor se nepodařilo přečíst jako PDF — je poškozený nebo to není PDF.",
        "en": "The file could not be read as a PDF — it is corrupted or not a PDF.",
        "de": "Die Datei konnte nicht als PDF gelesen werden — sie ist beschädigt oder keine PDF.",
    },
    "err.locked_or_no_write": {
        "cs": (
            "Soubor nebo složka je uzamčena, nebo chybí oprávnění k zápisu — "
            "zavřete soubor v jiném programu a zkuste to znovu. ({exc})"
        ),
        "en": (
            "The file or folder is locked, or write permission is missing — "
            "close the file in the other program and try again. ({exc})"
        ),
        "de": (
            "Die Datei oder der Ordner ist gesperrt, oder Schreibrechte fehlen — "
            "schließen Sie die Datei im anderen Programm und versuchen Sie es erneut. ({exc})"
        ),
    },
    "err.unexpected": {
        "cs": "Neočekávaná chyba ({name}): {exc}",
        "en": "Unexpected error ({name}): {exc}",
        "de": "Unerwarteter Fehler ({name}): {exc}",
    },
    # --- library and search ---
    "lib.empty_library": {
        "cs": (
            "V knihovně zatím není žádný hotový dokument — "
            "nejdřív složku naskenujte a naindexujte."
        ),
        "en": (
            "The library has no ready document yet — scan and index a folder first."
        ),
        "de": (
            "Die Bibliothek enthält noch kein fertiges Dokument — "
            "scannen und indexieren Sie zuerst einen Ordner."
        ),
    },
    "lib.mixed_models_doc": {
        "cs": (
            "Dokument {doc} je indexován jiným modelem embeddingů "
            "({model_a} ≠ {model_b}) — přeindexujte ho (🔄)."
        ),
        "en": (
            "Document {doc} is indexed with a different embedding model "
            "({model_a} ≠ {model_b}) — re-index it (🔄)."
        ),
        "de": (
            "Dokument {doc} ist mit einem anderen Embedding-Modell indexiert "
            "({model_a} ≠ {model_b}) — indexieren Sie es neu (🔄)."
        ),
    },
    "lib.mixed_models_pools": {
        "cs": (
            "Části knihovny jsou indexovány různými modely embeddingů "
            "({model_a} ≠ {model_b}) a nejsou kompatibilní — "
            "přeindexujte starší složku."
        ),
        "en": (
            "Parts of the library are indexed with different embedding models "
            "({model_a} ≠ {model_b}) and are incompatible — "
            "re-index the older folder."
        ),
        "de": (
            "Teile der Bibliothek sind mit unterschiedlichen Embedding-Modellen "
            "indexiert ({model_a} ≠ {model_b}) und nicht kompatibel — "
            "indexieren Sie den älteren Ordner neu."
        ),
    },
    "lib.stale_selection": {
        "cs": (
            "Vybrané dokumenty už v knihovně nejsou — "
            "obnovte výběr v poli „Kde hledat“."
        ),
        "en": (
            "The selected documents are no longer in the library — "
            "refresh the selection in “Where to search”."
        ),
        "de": (
            "Die ausgewählten Dokumente sind nicht mehr in der Bibliothek — "
            "aktualisieren Sie die Auswahl unter „Wo suchen“."
        ),
    },
    "lib.readonly_folder": {
        "cs": (
            "Do složky knihovny nelze zapisovat — index (.search_index) "
            "nelze uložit. Povolte zápis do složky."
        ),
        "en": (
            "The library folder is not writable — the index (.search_index) "
            "cannot be saved. Allow writing to the folder."
        ),
        "de": (
            "In den Bibliotheksordner kann nicht geschrieben werden — der Index "
            "(.search_index) lässt sich nicht speichern. Erlauben Sie das Schreiben."
        ),
    },
    "lib.tree_root": {
        "cs": "Knihovny",
        "en": "Libraries",
        "de": "Bibliotheken",
    },
    "lib.folder_unavailable": {
        "cs": "{name} (nedostupná)",
        "en": "{name} (unavailable)",
        "de": "{name} (nicht erreichbar)",
    },
    "lib.doc_busy": {
        "cs": "Dokument {slug} se právě indexuje — počkejte na dokončení.",
        "en": "Document {slug} is being indexed right now — wait for it to finish.",
        "de": "Dokument {slug} wird gerade indexiert — warten Sie, bis es fertig ist.",
    },
    "lib.folder_busy": {
        "cs": "Složku právě indexuje jiný počítač: {owner}",
        "en": "Another computer is indexing this folder right now: {owner}",
        "de": "Ein anderer Computer indexiert diesen Ordner gerade: {owner}",
    },
    "lib.no_library_path": {
        "cs": "Složka knihovny není nastavena.",
        "en": "The library folder is not set.",
        "de": "Der Bibliotheksordner ist nicht festgelegt.",
    },
    "lib.pdf_not_found": {
        "cs": "PDF pro dokument {slug} nebylo nalezeno.",
        "en": "PDF for document {slug} was not found.",
        "de": "PDF für Dokument {slug} wurde nicht gefunden.",
    },
    "lib.file_outside": {
        "cs": "Soubor je mimo složky knihovny.",
        "en": "The file is outside the library folders.",
        "de": "Die Datei liegt außerhalb der Bibliotheksordner.",
    },
    "lib.file_not_found": {
        "cs": "Soubor nenalezen: {path}",
        "en": "File not found: {path}",
        "de": "Datei nicht gefunden: {path}",
    },
    # --- indexing progress (pipeline stages) ---
    "progress.reading": {
        "cs": "čtení PDF…",
        "en": "reading PDF…",
        "de": "PDF wird gelesen…",
    },
    "progress.images": {
        "cs": "popis obrázků…",
        "en": "describing images…",
        "de": "Bilder werden beschrieben…",
    },
    "progress.images_page": {
        "cs": "popis obrázků: strana {done}/{total}",
        "en": "describing images: page {done}/{total}",
        "de": "Bildbeschreibung: Seite {done}/{total}",
    },
    "progress.drawings_page": {
        "cs": "popis výkresů: strana {done}/{total}",
        "en": "describing drawings: page {done}/{total}",
        "de": "Zeichnungsbeschreibung: Seite {done}/{total}",
    },
    "progress.chunking": {
        "cs": "řezání na části…",
        "en": "splitting into chunks…",
        "de": "Aufteilen in Abschnitte…",
    },
    "progress.embedding": {
        "cs": "indexace…",
        "en": "indexing…",
        "de": "Indexierung…",
    },
    # --- settings validation (folder paths, OpenAI key) ---
    "settings.path_not_found": {
        "cs": "Cesta neexistuje: {path}",
        "en": "Path does not exist: {path}",
        "de": "Pfad existiert nicht: {path}",
    },
    "settings.not_a_dir": {
        "cs": "Toto není složka: {path}",
        "en": "Not a folder: {path}",
        "de": "Kein Ordner: {path}",
    },
    "settings.bad_openai_key": {
        "cs": "Klíč OpenAI musí začínat na 'sk-'.",
        "en": "The OpenAI key must start with 'sk-'.",
        "de": "Der OpenAI-Schlüssel muss mit 'sk-' beginnen.",
    },
    # --- profile (auth) ---
    "auth.server_unavailable": {
        "cs": "Licenční server není dostupný. Zkuste to později.",
        "en": "The license server is unavailable. Try again later.",
        "de": "Der Lizenzserver ist nicht erreichbar. Versuchen Sie es später.",
    },
    "profile.load_failed": {
        "cs": "Nepodařilo se načíst profil.",
        "en": "Failed to load the profile.",
        "de": "Das Profil konnte nicht geladen werden.",
    },
    "profile.save_failed": {
        "cs": "Nepodařilo se uložit profil.",
        "en": "Failed to save the profile.",
        "de": "Das Profil konnte nicht gespeichert werden.",
    },
    "profile.password_change_failed": {
        "cs": "Změna hesla selhala.",
        "en": "Password change failed.",
        "de": "Die Passwortänderung ist fehlgeschlagen.",
    },
}


def msg(key: str, **params: object) -> str:
    """Message text in the current language; English is the fallback."""
    entry = MESSAGES[key]
    template = entry.get(_current) or entry["en"]
    return template.format(**params) if params else template
