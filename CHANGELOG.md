# Changelog

All notable changes to this project. Versions follow [Semantic Versioning](https://semver.org/).

## 1.1.0 (2026-10-16)

Found with real terminal output: secrets were hidden, but names that identify the person and server were not.

- Shell prompts (`user@host:~$`), `[sudo] password for user:` and `ssh`/`scp`/`sftp`/`rsync user@...` hide the user name as `[[USERNAME_N]]` and the prompt's host as `[[HOSTNAME_N]]`. Generic accounts (`root`, `git`, `admin`, `ubuntu`, ...) stay visible.
- New `[rules] private_domains`: your own public domains, hidden with every subdomain as `[[DOMAIN_N]]`.
- New `[rules] hide_private_ips` (default `true`): set `false` to keep private and local IPs visible, so the AI can see the network layout. Public IPs are always hidden.
- Values shorter than 4 characters are no longer searched again in later messages (a hidden user `ru` no longer hides `/srv` or other words); the rules still find them where their pattern matches.

## 1.0.1 (2026-10-16)

- Fix: writing the clipboard with wl-copy or xclip could hang until the timeout ("did not answer within 10s"). These tools leave a background process that kept the error pipe open. The error output now goes to a temporary file, so the write returns at once.

## 1.0.0 (2026-10-16)

First stable release.

- Layer 1 (rules): API keys and tokens (AWS, GitHub, Slack, OpenAI/Anthropic-style, Google), private keys (PEM), JWTs, bearer tokens, passwords in URLs and in `key = value` assignments, emails, IPv4/IPv6, phone numbers, high-entropy strings, internal hostnames (`.lan`, `.local`, `.internal`, `.corp`, ... plus your own domains), your own words and regex patterns, and an allowlist.
- Layer 2 (optional extra `ner`): GLiNER PII model for names, addresses, organizations and usernames; CPU by default; no network access after the first download.
- Layer 3 (optional): review by a local LLM through any OpenAI-compatible server (LM Studio, Ollama) with JSON-schema answers; the model only lists values, the code replaces exact matches.
- Session vault: the same value always gets the same `[[KIND_N]]` placeholder; files with mode 0600 in a 0700 folder; automatic expiry (`ttl_hours`).
- Restore: also accepts `[X_1]`, `<X_1>`, `&lt;X_1&gt;` and Markdown-escaped forms; reports placeholders the AI invented.
- CLI `prompt-guard` / `pgd`: `redact` (with `--show`, `--ner`, `--llm`), `restore`, `clear`, `sessions`, `llm-check`, `shortcuts`.
- Clipboard on Wayland, X11, WSL and macOS, or stdin/stdout.
- GNOME keyboard shortcuts (Ctrl+Alt+R / Ctrl+Alt+U) with desktop notifications that never show hidden values.
- An enabled layer that cannot run stops the run with an error; nothing is written and the clipboard is not changed.

## 0.3.0

- Layer 3: local LLM review; `pgd llm-check`.

## 0.2.0

- Layer 2: GLiNER NER (optional extra).

## 0.1.0

- First usable version: layer 1, session vault, restore, CLI and clipboard backends.
