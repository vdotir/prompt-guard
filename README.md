# prompt-guard

A fully local CLI that removes secrets and personal data from text before you paste it into an online AI chat, then puts the original values back into the AI's reply.

Nothing leaves your machine, except calls to a local LLM server that you configure yourself (optional).

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
| 1. Rules | API keys, tokens, passwords, private keys (PEM), JWTs, URL credentials, emails, IPs, phone numbers, your own patterns | Pure Python (regex + entropy) |
| 2. NER | Names, addresses, organizations, usernames | GLiNER-PII (Python) |
| 3. LLM review (optional) | Anything the first two layers missed | Any OpenAI-compatible local server (LM Studio, Ollama) |

The LLM only lists values. It never rewrites your text. The code replaces exact matches only, so the LLM cannot add or change content.

The same value always gets the same placeholder within a session, for example `[[API_KEY_1]]` or `[[EMAIL_2]]`. Double square brackets survive Markdown chat interfaces, which often strip `<...>` as HTML.

## Supported setups

- LM Studio or Ollama on the same machine.
- LM Studio on another host, for example an Ubuntu VM with a bridged network and LM Studio on the Windows host.
- No GPU: rules + NER only.
- Clipboard: X11 (`xclip`), Wayland (`wl-clipboard`), WSL (PowerShell / `clip.exe`), or stdin/stdout.

## Status

| Part | Status |
|---|---|
| Repository setup (README, license, tooling) | Done |
| Config file and example template | Done |
| Layer 1: rules (regex + entropy) | Done |
| Session vault and restore | Done |
| CLI: `redact`, `restore`, `clear`, `sessions` | Done |
| Clipboard backends (X11, Wayland, WSL, macOS) | Done |
| Layer 2: NER (GLiNER-PII) | Planned |
| Layer 3: LLM review (OpenAI-compatible) | Planned |
| Install and usage guide in `docs/runbook.md` | Done for layer 1 |

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

See [docs/runbook.md](docs/runbook.md) for clipboard tools, sessions and troubleshooting.

## Configuration

Copy [config.example.toml](config.example.toml) to `~/.config/prompt-guard/config.toml` and edit it. Every key is optional. Add your own project names, internal hosts and token formats under `[rules]`: these custom rules catch the leaks that generic detection misses.

## Development

See [docs/runbook.md](docs/runbook.md).

## Limits

No detection is perfect. Always look at the redacted text before you paste it. The vault file holds all your real values: keep it private and clear it when the chat is over. For very sensitive data, the safest option is not to send it to an online service at all.

## License

MIT. See [LICENSE](LICENSE).

## Credits

This project was built with the help of [Claude](https://claude.ai), an AI assistant by Anthropic.
