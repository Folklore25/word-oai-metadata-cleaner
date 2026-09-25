---
name: word-oai-metadata-cleaner
description: Inspect and sanitize DOCX files for ChatGPT, OpenAI, AI-generated URLs, author identities, and personal Word metadata while preserving visible document content by default. Use when a user wants to audit or clean Word metadata, remove ChatGPT traces, anonymize document properties, or verify a sanitized DOCX. Do not use for legacy .doc files without first converting them to .docx.
---

# Word OAI Metadata Cleaner

Clean Word metadata conservatively and produce a verified copy. Never imply that metadata removal proves who authored a document or guarantees anonymity outside the inspected file.

## Safety boundary

- Preserve the source file. Write a sibling copy such as `name-sanitized.docx`; do not overwrite the original.
- Scan before cleaning and classify every match as package metadata, comment/revision identity, external hyperlink, visible document content, or custom XML.
- By default, clean only document properties and matching author/identity attributes. Do not silently delete visible text, comments, revisions, citations, headers, footers, or custom XML.
- A URL displayed in the document and a URL stored only as a hyperlink target are different. Remove hyperlink targets only when the user explicitly asks; preserve the displayed text.
- Treat `customXml/` matches as potentially data-bound. Report them for review instead of modifying them automatically.
- Do not upload confidential documents to online metadata-cleaning services.

## Workflow

1. Confirm the input is a valid `.docx` ZIP package. For `.doc`, require conversion to `.docx` first.
2. Run the bundled scanner:

   ```bash
   python scripts/sanitize_docx_metadata.py input.docx --scan
   ```

3. Explain any content-bearing matches before changing them. A normal targeted cleanup is:

   ```bash
   python scripts/sanitize_docx_metadata.py input.docx --output input-sanitized.docx
   ```

4. If the user also wants ChatGPT/OpenAI hyperlink destinations removed while keeping the displayed text:

   ```bash
   python scripts/sanitize_docx_metadata.py input.docx \
     --output input-sanitized.docx \
     --remove-ai-hyperlinks
   ```

5. If the user explicitly requests removal of all ordinary author/company metadata, add `--clear-all-personal`. This clears standard creator, last-saved-by, company, manager, and custom-property fields, not visible document content.
6. Scan the output again. Report unresolved matches in visible content or `customXml/`; do not call the file clean if relevant matches remain unexplained.
7. Validate the output ZIP and parse its XML. When delivering an edited DOCX, follow the document workflow's render-and-inspect requirement to confirm that layout and visible content remain intact.

## What the script changes

The default targeted mode:

- clears matching values in `docProps/core.xml` and `docProps/app.xml`;
- removes matching properties from `docProps/custom.xml`;
- anonymizes matching author, initials, user, and provider attributes used by comments or revisions;
- removes ZIP-level comments;
- leaves visible text, ordinary hyperlinks, and custom XML unchanged and reports remaining matches.

`--remove-ai-hyperlinks` removes matching external hyperlink relationships and detaches their relationship references without deleting displayed text. It does not erase a URL typed as visible text.

## Verification standard

- Confirm the output opens as a ZIP and every XML part parses.
- Compare pre-clean and post-clean findings.
- Confirm there are no broken relationship references introduced by hyperlink removal.
- Render and visually inspect every page after modification.
- State precisely what was removed and what remains. Avoid broad claims such as “all AI traces are gone” unless every package part was inspected and all remaining matches were resolved.
