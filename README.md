# MAI Assistant - search your construction database

[![CI](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml/badge.svg)](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml)

**English** | [Čeština](README.cs.md) | [Deutsch](README.de.md)

> 🔧 **Engineers & developers:** the technical description - stack, RAG
> pipeline, design decisions - is in [ARCHITECTURE.md](ARCHITECTURE.md).
> This page describes the product for its users.

Build a local database out of your own construction documents and search it
from one place. Documents, projects, drawings - scanned or not, it makes no
difference.

Ask a question in plain language and get a short answer with a link to the
exact page of the exact document. No more remembering which file it was in
and scrolling through hundreds of pages. The search works by keywords and by
meaning, so you can ask the way you would ask a colleague, without guessing
the wording used in the document.

![Search page](docs/screenshots/search.png)

## How this differs from plain ChatGPT

Upload 100 documents to ChatGPT and it has to read all of them again for
every question - slow and expensive, and a whole library of documents does
not fit there in the first place.

Here the search through your documents is done by code, and ChatGPT only
phrases the answer from the fragments that were found. That is what makes it
fast, cheap and precise about its source.

## Document formats

The current version works with PDF. Whatever is inside - text, scans,
schemes, tables, drawings, title blocks, handwritten notes - is read,
remembered by the assistant and used in the search. Scanned pages that
contain no actual text are recognised automatically. For drawings and schemes
the AI additionally writes a description - what is drawn, which object, which
design stage - and that description is what later helps to find the right
sheet. Handwriting is read as far as the AI can make it out.

## Privacy

The assistant is installed and runs locally on your computer, working with
the documents on your computer. The database and everything the assistant has
remembered from your documents stay with you; there is no cloud storage.

Answers are phrased by ChatGPT (the OpenAI API). Your documents are split
into small fragments, and only the few fragments relevant to your question are
sent - directly to OpenAI on your own key, with no server of the author's and
no third-party service in between.

Free registration is required, only so that the author can see that the app
is actually being used. The author sees none of your documents, questions or
file names: the app sends anonymous statistics - how often something was run,
how much time and money it took, which errors occurred.

Your OpenAI key is stored on your computer encrypted by Windows and tied to
your user account: the app's data file copied to another computer, or opened
under another account, does not give the key away. Programs running under
your own account can still use it - as with any saved password - so keep the
computer itself trustworthy. If the key ever leaks, delete it in your OpenAI
account and create a new one.

## Cost

The app itself is free and the author earns nothing from it. You pay OpenAI
only, and you pay them directly: once for processing your documents, then
cents for questions.

| Action | gpt-5.6-luna (default) | gpt-5.6-sol |
|---|---|---|
| Process a page with schemes or tables | ~$0.002 | ~$0.04 |
| Process a drawing sheet | ~$0.002 | ~$0.04 |
| One question | ~$0.002 | ~$0.03 |
| One strong-search question | ~$0.003 | ~$0.07 |

Plain text pages are almost free. A 300-page document is a one-off of tens of
cents on the default model (a few dollars with gpt-5.6-sol); a working day of
questions costs cents.

## How it works

**1. You point at a folder** - or several: your own documents, whole
projects, or a company network folder. The folder is processed and a copy the
assistant can understand is created next to it - that is what it searches.
Your files are only read: nothing is modified and nothing is copied away.

![Library page](docs/screenshots/library.png)

Finished projects live on their own tab: one attached folder = one project,
with its reports, calculations and drawing sets.

![Project archive](docs/screenshots/archive.png)

If the folder is a shared one, only the first person pays for the processing -
everyone else attaches the same folder and picks up the finished result for
free.

**2. You choose where to search** - the whole database or specific documents.
And how: by keywords, by meaning, or both. There is also strong search, where
the assistant looks at the pages themselves and can tell what is drawn on a
sheet or which dimension a table gives.

**3. You get a short answer** and a link to the source - straight to the page
the answer came from. Ask in any language; the answer language is chosen
separately from the interface language (English, Czech, German).

**How much fits.** The public version holds up to 5000 pages in total - your
library and your project archive together. Everything the assistant has
remembered is kept in memory so that the search stays instant, and that is
what sets the limit. Documents above it stay in the list, marked, and are
simply not searched.

## Getting started

1. **Download the installer** for Windows - it needs no administrator rights.
   *(The public build is in preparation and will appear on the
   [Releases](https://github.com/mrYoriichi/Search_standarts/releases) page.)*
2. **Register** on the first launch - email and password, free, no
   subscription.
3. **Get an OpenAI key:** create an account at
   [platform.openai.com](https://platform.openai.com) → **Billing → Add
   credits** ($5 goes a long way) → **API keys → Create new secret key** →
   paste the key into the app under **Settings**. It is stored only on your
   computer.
4. **Attach a folder** with your documents, press **Scan**, then **Index**.

**The app opens in a browser window - that is only its interface, not a
website.** The program is installed on your computer and runs there; the
browser is simply the window it uses.

## About the author

The app was built by a bridge engineer for design engineers, out of a daily
working need. The public Windows version is free.

## For developers

Architecture, engineering decisions, measured numbers and how to run it from
source: **[ARCHITECTURE.md](ARCHITECTURE.md)**. Windows build instructions:
[BUILD.md](BUILD.md).

## License

[PolyForm Internal Use 1.0.0](LICENSE.md) - free to use inside your
organization, commercial companies included; selling the software or offering
it to third parties as a product or service stays with the author.
