# prompt-guard

A fully local CLI that removes secrets and personal data from text before you paste it into an online AI chat, then puts the original values back into the AI's reply.

Nothing leaves your machine, except calls to a local LLM server that you configure yourself (optional).

```
before:           db = postgres://app:S3cretPw@build-07.corp.lan/main   # ask Margaret Thompson
after (--ner):    db = postgres://app:[[PASSWORD_1]]@[[HOSTNAME_1]]/main   # ask [[PERSON_1]]
```

## How it works

```
your text ──► redact ──► text with placeholders ──► online AI chat
                │                                        │
            session vault                                │
            (local, 0600)                                ▼
                │                                    AI reply
                └──────────► restore ◄───────────────────┘
                                │
                                ▼
                    reply with your real values
```

Detection runs in three layers. Each layer can be turned off.

| Layer | What it finds | Runs on |
|---|---|---|
| 1. Rules | API keys, tokens, passwords, private keys (PEM), JWTs, URL credentials, emails, IPs, phone numbers, internal hostnames, your own domains, user and host names in shell prompts, sudo and ssh lines, your own words and patterns | Pure Python (regex + entropy) |
| 2. NER (optional) | Names, addresses, organizations, usernames | A GLiNER PII model with torch, on CPU by default |
| 3. LLM review (optional) | Anything the first two layers missed | Any OpenAI-compatible local server (LM Studio, Ollama), standard library only |

The LLM only lists values. It never rewrites your text. The code replaces exact matches only, so the LLM cannot add or change content.

The same value always gets the same placeholder within a session, for example `[[API_KEY_1]]` or `[[EMAIL_2]]`. Double square brackets survive Markdown chat interfaces, which often strip `<...>` as HTML.

## Quick start

```bash
git clone https://github.com/vdotir/prompt-guard ~/prompt-guard
cd ~/prompt-guard
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy the text you want to send to the AI, then redact the clipboard:

```bash
pgd redact --show
```

Paste the redacted text into the chat. Copy the AI's reply, then restore your real values into the clipboard:

```bash
pgd restore
```

When the chat is over, delete its session:

```bash
pgd clear
```

`pgd` is the short name of `prompt-guard`. Use `-s <name>` to keep one session per chat. Pipes work too:

```bash
cat app.log | pgd redact > safe.log
```

### Without a terminal (GNOME)

Add two keyboard shortcuts: Ctrl+Alt+R redacts the clipboard, Ctrl+Alt+U restores it. A desktop notification tells you what happened.

```bash
pgd shortcuts install
```

### More layers

- Names and addresses: install the optional NER extra and use `--ner`.
- A local LLM as a final check: start LM Studio or Ollama and use `--llm`.

[docs/runbook.md](docs/runbook.md) has the full setup, a worked example from start to finish, and troubleshooting.

## Supported setups

- Linux with Wayland or X11, WSL, and macOS clipboards, or stdin/stdout anywhere.
- LM Studio or Ollama on the same machine, or on another host in the LAN (for example an Ubuntu VM with LM Studio on the Windows host).
- No GPU: layers 1 and 2 run on CPU; layer 3 is optional.

## Configuration

Copy [config.example.toml](config.example.toml) to `~/.config/prompt-guard/config.toml` and edit it. Every key is optional. Add your own project names, internal domains and token formats under `[rules]`: these custom rules catch the leaks that generic detection misses.

## Status

Version 1.1.1. See [CHANGELOG.md](CHANGELOG.md).

| Part | Status |
|---|---|
| Layer 1: rules (regex, entropy, internal hostnames, private domains, shell prompts) | Done |
| Layer 2: NER (GLiNER PII model, optional extra) | Done |
| Layer 3: LLM review (OpenAI-compatible, optional) | Done |
| Session vault with expiry, and restore | Done |
| CLI: `redact`, `restore`, `clear`, `sessions`, `llm-check`, `shortcuts` | Done |
| Clipboard backends (Wayland, X11, WSL, macOS) | Done |
| Keyboard shortcuts and desktop notifications (GNOME) | Done |
| Config file with validation and example template | Done |
| Install, usage and troubleshooting guide (`docs/runbook.md`) | Done |

## Development

See [docs/runbook.md](docs/runbook.md).

## Limits

No detection is perfect. Always look at the redacted text before you paste it. The vault file holds all your real values: keep it private and clear it when the chat is over. For very sensitive data, the safest option is not to send it to an online service at all.

## License

MIT. See [LICENSE](LICENSE).

## Credits

This project was built with the help of [Claude](https://claude.ai), an AI assistant by Anthropic.
