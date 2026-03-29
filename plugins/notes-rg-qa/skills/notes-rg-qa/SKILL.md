---
name: notes-rg-qa
description: Use rg and direct note reads to answer questions from a local Markdown notes library, without any parallel retrieval index.
---

# Notes RG QA

## Overview

Use this skill when the user wants to ask questions about content already ingested into the local notes library.
This skill is model-agnostic. It is designed for Codex, Claude, or any other agent that can follow instructions and call local commands.

The retrieval backend is plain filesystem search.
Prefer `rg`, `rg --files`, and direct file reads. Do not invent a dedicated Q&A CLI layer.

## Requirements

- The notes library must already contain Markdown notes under `Sources/**`.
- The agent must have shell access to run `rg`.
- The agent must be able to open note files directly after search.

## Hard Rules

- Use `rg` for discovery before opening files.
- Search raw notes under the library. Do not rely on derived maps, prebuilt indices, or hidden state.
- Do not claim evidence from a note unless you actually opened the file.
- Prefer multiple short, retrieval-friendly searches over one long natural-language search.
- Cite the file paths you opened when you answer.

## Default Workflow

1. Restate the user question as retrieval intent.
2. Produce 4-8 short query candidates.
3. Run several `rg` searches with those short queries.
4. Collect a small set of promising note paths.
5. Open the highest-value notes directly.
6. Synthesize the answer from the opened raw notes only.
7. Include note-path citations in the final answer.

## Search Guidance

- Start with exact nouns, names, themes, and distinctive phrases.
- Split broad questions into sharper terms such as topic, motive, evaluation criterion, and counterpoint.
- If the user asks in Chinese, prefer Chinese search terms first.
- If the first round is sparse, broaden with synonyms instead of repeating the same query.
- Stop once the opened notes are clearly sufficient. Do not read the whole library.

## Command Patterns

Find candidate files:

```bash
rg -n "成长|自律|职业路径" Sources
rg -n "AI Agent|工作|自由" Sources
```

List note files when you need to browse a subtree:

```bash
rg --files Sources/Zhihu
rg --files Sources/WeChat
```

Read a note after search:

```bash
sed -n '1,220p' Sources/Zhihu/example-author/answers/example-note.md
```

## Output Expectations

- Keep the answer grounded in opened notes.
- Distinguish evidence from inference.
- Include a short citations section or inline file-path references.
- If evidence is weak or conflicting, say so plainly.

## Non-Goals

- Do not generate or maintain session files.
- Do not build derived context packages.
- Do not treat this skill as a crawler. It is retrieval-only.
