---
name: obsidian-cli-qa
description: Use the official Obsidian CLI to retrieve raw vault notes and answer questions from evidence, without maintaining any parallel QA index.
---

# Obsidian CLI QA

## Overview

Use this skill when the user wants to ask questions about content already ingested into an Obsidian vault.
This skill is model-agnostic. It is designed for Codex, Claude, or any other agent that can follow instructions and call local commands.

The required retrieval backend is the official Obsidian desktop CLI.
Do not replace it with repo file scanning, ad hoc grep over the vault, or any deprecated `oki` QA command.

## Requirements

- The official Obsidian CLI must be enabled in Obsidian Settings > General > Command line interface.
- The target vault must already contain notes under `Sources/**`.
- The agent must have shell access to run `obsidian search` and `obsidian read`.

## Hard Rules

- Use only the official `obsidian` CLI for retrieval.
- Search raw notes under the vault. Do not rely on derived maps, prebuilt corpora, or legacy `Derived/Scopes/**` files.
- Do not claim evidence from a note unless you actually opened it with `obsidian read`.
- Prefer multiple short, retrieval-friendly searches over one long natural-language search.
- Cite the note paths you opened when you answer.

## Default Workflow

1. Restate the user question as retrieval intent.
2. Produce 4-8 short query candidates.
3. Run several `obsidian search` calls with those short queries.
4. Collect a small set of promising note paths.
5. Open the highest-value notes with `obsidian read`.
6. Synthesize the answer from the opened raw notes only.
7. Include note-path citations in the final answer.

## Search Guidance

- Start with exact nouns, names, themes, and distinctive phrases.
- Split broad questions into sharper terms such as topic, motive, evaluation criterion, and counterpoint.
- If the user asks in Chinese, prefer Chinese search terms first.
- If the first round is sparse, broaden with synonyms instead of repeating the same query.
- Stop once the opened notes are clearly sufficient. Do not exhaustively read the whole vault.

## Command Patterns

Search:

```bash
obsidian search query="成长 自律"
obsidian search query="AI Agent"
```

Read a note:

```bash
obsidian read path="Sources/Zhihu/example-author/answers/example-note.md"
```

When the vault path must be explicit:

```bash
obsidian vault="/absolute/path/to/vault" search query="职业 路径"
obsidian vault="/absolute/path/to/vault" read path="Sources/WeChat/example/example.md"
```

## Output Expectations

- Keep the answer grounded in the opened notes.
- Distinguish evidence from inference.
- Include a short citations section or inline note-path references.
- If evidence is weak or conflicting, say so plainly.

## Non-Goals

- Do not generate or maintain session files.
- Do not build a derived scope package.
- Do not use deprecated `oki ask`, `oki qa-search`, `oki qa-open-derived`, or similar commands.
- Do not treat this skill as a crawler. It is retrieval-only.
