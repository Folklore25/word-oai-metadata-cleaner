# Word OAI Metadata Cleaner

A Codex skill and standalone Python utility for inspecting and conservatively cleaning Microsoft Word `.docx` metadata associated with ChatGPT, GPT, OpenAI, and related URLs.

## What it does

- Scans every DOCX package part for ChatGPT, GPT, OpenAI, and related domains.
- Classifies findings as document properties, identity metadata, relationships, visible content, or custom XML.
- Clears matching core, application, and custom document properties.
- Anonymizes matching comment and revision author attributes.
- Optionally removes matching external hyperlink destinations while preserving displayed text.
- Creates a new output file and never overwrites the source document.
- Reports visible-content and `customXml/` matches for manual review instead of silently deleting them.

The tool is intentionally conservative. Removing metadata does not prove authorship, remove copies stored elsewhere, or guarantee anonymity.

## Repository layout

```text
skills/
└── word-oai-metadata-cleaner/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    └── scripts/
        └── sanitize_docx_metadata.py
```

## Add to CC Switch

Add this repository as a custom skill repository using:

- Repository: `https://github.com/Folklore25/word-oai-metadata-cleaner.git`
- Branch: `main`
- Subdirectory: `skills`

CC Switch can then discover `word-oai-metadata-cleaner` beneath the configured subdirectory.

## Install manually as a Codex skill

```bash
git clone https://github.com/Folklore25/word-oai-metadata-cleaner.git
mkdir -p ~/.codex/skills
cp -R word-oai-metadata-cleaner/skills/word-oai-metadata-cleaner \
  ~/.codex/skills/
```

The skill entrypoint is [`skills/word-oai-metadata-cleaner/SKILL.md`](skills/word-oai-metadata-cleaner/SKILL.md). The utility uses only the Python standard library and requires Python 3.10 or newer.

## Scan a DOCX

```bash
python skills/word-oai-metadata-cleaner/scripts/sanitize_docx_metadata.py \
  document.docx --scan
```

Use `--json` when machine-readable findings are needed.

## Clean targeted OAI metadata

```bash
python skills/word-oai-metadata-cleaner/scripts/sanitize_docx_metadata.py \
  document.docx \
  --output document-sanitized.docx
```

This preserves visible text and ordinary hyperlinks.

## Remove OAI hyperlink destinations

```bash
python skills/word-oai-metadata-cleaner/scripts/sanitize_docx_metadata.py \
  document.docx \
  --output document-sanitized.docx \
  --remove-ai-hyperlinks
```

The displayed hyperlink text is retained. A URL typed as visible text is reported but not erased.

## Clear ordinary personal properties

Add `--clear-all-personal` only when the document's standard creator, last-saved-by, company, manager, and custom properties should also be cleared.

## Verification

After cleaning, scan the output again and review any remaining visible-content or `customXml/` findings. For document delivery, open or render the sanitized DOCX to confirm that its visible layout remains intact.
