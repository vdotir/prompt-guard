# Runbook

How to set up, test, and work on prompt-guard. This file is updated with every step.

## Requirements

- Python 3.11 or newer, with the venv module (on Debian/Ubuntu: the `python3.X-venv` package that matches your Python version)
- git
- GitHub CLI (`gh`), only for creating the repository

## Development setup

If `python3 -m venv` says ensurepip is not available, install the venv package first (replace 3.14 with your Python version):

```bash
sudo apt install python3.14-venv
```

```bash
cd ~/prompt-guard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Install for daily use

The same venv works for development and daily use. `pip install -e .` creates two commands in the venv: `prompt-guard` and its short name `pgd`.

To use `pgd` without activating the venv, link it into `~/.local/bin` (on Ubuntu this folder is already on PATH after you log in again):

```bash
mkdir -p ~/.local/bin && ln -sf ~/prompt-guard/.venv/bin/pgd ~/.local/bin/pgd && ln -sf ~/prompt-guard/.venv/bin/prompt-guard ~/.local/bin/prompt-guard
```

### Clipboard tools

prompt-guard uses the system's clipboard tools. Install the one for your desktop:

Ubuntu with Wayland (default on recent Ubuntu):

```bash
sudo apt install wl-clipboard
```

Ubuntu with X11:

```bash
sudo apt install xclip
```

WSL uses `powershell.exe` from Windows; nothing to install. macOS has `pbcopy` and `pbpaste` built in.

Check which clipboard backend is picked:

```bash
python -m prompt_guard.clipboard
```

To force one, set `backend` under `[clipboard]` in the config (`wayland`, `x11`, `wsl`, `macos`).

Ubuntu in a VMware VM: copy and paste between the VM and the host needs open-vm-tools-desktop in the VM. prompt-guard only works on the VM's own clipboard; VMware tools carry it to the host.

```bash
sudo apt install open-vm-tools-desktop
```

## Checks before every commit

```bash
ruff check .
ruff format --check .
pytest
```

## Repository rules

- All code, comments, file names, and docs are in English.
- Every code file starts with a header comment: purpose, path in repo, relations, how to run.
- Every part has pytest tests and passes ruff.
- The repo is public: no real names, IPs, hostnames, or keys. Test fixtures use obviously fake secrets.
- Local config (`config.toml`) and vault files are in `.gitignore` and are never committed.

## Configuration

Create the config from the example and edit it:

```bash
mkdir -p ~/.config/prompt-guard && cp config.example.toml ~/.config/prompt-guard/config.toml
```

Use another file for one run:

```bash
PROMPT_GUARD_CONFIG=/path/to/config.toml python -c "from prompt_guard.config import load_config; print(load_config())"
```

A typo in a key name, a wrong type, or an invalid regex stops the program with a clear error. This is on purpose: a silently ignored rule would mean a silent leak.

## Layer 1: rules

Built-in kinds: PRIVATE_KEY, AWS_KEY, GITHUB_TOKEN, SLACK_TOKEN, API_KEY, GOOGLE_API_KEY, JWT, PASSWORD (in URLs), BEARER_TOKEN, SECRET (key = value assignments and high-entropy strings), EMAIL, IP (v4 and v6), PHONE, plus CUSTOM (your words) and your own pattern names.

Try layer 1 on any text:

```bash
echo "mail ops@example.org, DB=postgres://u:pa55word@db:5432/x" | python -m prompt_guard.rules
```

Tuning:

- Too many harmless strings flagged as SECRET: raise `entropy_threshold` (for example 4.3) or `entropy_min_length`.
- A value that must stay visible: add it to `allowlist`.
- A secret format that is not caught: add a `[[rules.patterns]]` entry.

## Layer 2: NER (names, addresses, organizations)

Layer 2 uses a GLiNER model to find personal data without a fixed shape. It needs torch and gliner, which are large, so they are an optional extra. Layer 1 works without them.

### Install

Inside the project venv, install the CPU build of torch first. It is much smaller than the default CUDA build, and an Ubuntu VM usually has no GPU anyway:

```bash
source ~/prompt-guard/.venv/bin/activate
```

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Then install the extra:

```bash
pip install -e ".[ner]"
```

If pip finds no torch build for your Python version, use a Python version that PyTorch supports for the venv. A CUDA build only helps when Linux runs directly on the hardware with an NVIDIA GPU; then set `device = "cuda"` under `[ner]`.

### First run

The first run downloads the model from Hugging Face into `~/.cache/huggingface`. After that, with `offline_after_download = true` (default), the model is loaded from the cache and no network request is made. Your text is never sent anywhere.

Download the model and check that it finds a name:

```bash
echo "Please send the invoice to Margaret Thompson at 12 Example Road." | python -m prompt_guard.ner
```

Run the optional real-model test:

```bash
PROMPT_GUARD_NER_TEST=1 pytest tests/test_ner.py
```

### Use

Turn it on for one run:

```bash
pgd redact --ner --show
```

Turn it on by default in `~/.config/prompt-guard/config.toml`:

```toml
[layers]
ner = true
```

Turn it off for one run when it is on by default:

```bash
pgd redact --no-ner
```

If layer 2 is turned on but cannot run (extra not installed, model missing), redact stops with an error and writes nothing. It never skips the layer silently.

Each run loads the model again, so redact with layer 2 takes a few seconds longer than layer 1 alone. Two known, harmless warnings from torch and huggingface_hub during loading are hidden; all other warnings are still shown.

### Tuning

- Names or addresses are missed: lower `threshold` (for example 0.2) or add labels.
- Normal words are hidden: raise `threshold` (for example 0.5), or add the word to `[rules] allowlist`.
- Labels are free text (the model is zero-shot). Each label becomes a placeholder kind: `name` gives `[[PERSON_1]]`, `location address` and `location street` give `[[ADDRESS_1]]`, `organization` gives `[[ORG_1]]`, `username` gives `[[USERNAME_1]]`. Other labels are converted, for example `vehicle id` gives `[[VEHICLE_ID_1]]`.
- Another model: set `model`, for example `knowledgator/gliner-pii-edge-v1.0` (faster) or `nvidia/gliner-PII` (larger). Check the model's license on its Hugging Face page.

## Layer 3: LLM review (local LLM)

A local model reads the text after layers 1 and 2 have hidden what they found, and lists sensitive values that are still visible (internal hostnames, project names, unusual IDs). It only lists values; the code replaces exact matches, so the model cannot change your text. It needs no extra Python package.

Layer 3 is off by default. It is slower than the other layers and needs the LLM server running.

### LM Studio on the same machine

1. In LM Studio, download and load a model. Qwen3-8B Q4_K_M fits an 8 GB GPU.
2. Start the server (Developer tab, "Start Server"). The default address is `http://localhost:1234/v1`.
3. Check the connection and see the exact model id:

```bash
pgd llm-check
```

4. If the configured model is not in the list, set `model` under `[llm]` in `~/.config/prompt-guard/config.toml` to one of the listed ids.

### LM Studio on another machine (for example an Ubuntu VM and LM Studio on the Windows host)

1. In LM Studio on Windows, open the server settings and turn on "Serve on Local Network".
2. Find the Windows IP address in the same network as the VM. In PowerShell on Windows:

```powershell
ipconfig
```

3. Allow port 1234 through the Windows firewall, only from the VM. Run PowerShell as administrator on Windows, and replace `<vm-ip>` with the VM's IP address (`hostname -I` in the VM shows it):

```powershell
New-NetFirewallRule -DisplayName "LM Studio from VM" -Direction Inbound -Protocol TCP -LocalPort 1234 -RemoteAddress <vm-ip> -Action Allow -Profile Private
```

4. In the VM, set the server address in `~/.config/prompt-guard/config.toml`, with `<host-ip>` from step 2:

```toml
[llm]
base_url = "http://<host-ip>:1234/v1"
```

5. Check the connection from the VM:

```bash
pgd llm-check
```

"Serve on Local Network" lets other devices in the network use LM Studio. The firewall rule above limits that to the VM. The text you redact goes over the local network to the host, never to the internet.

### Use

Turn it on for one run, together with layer 2:

```bash
pgd redact --ner --llm --show
```

Turn it on by default in the config:

```toml
[layers]
llm = true
```

Turn it off for one run when it is on by default:

```bash
pgd redact --no-llm
```

If the server cannot be reached, or the model answers with something that is not the expected JSON, redact stops with an error and writes nothing.

Try layer 3 alone on some text:

```bash
echo "Deploy failed on build-07.corp-internal.lan, ask Margaret." | python -m prompt_guard.llm
```

Run the optional test against your real server:

```bash
PROMPT_GUARD_LLM_TEST=1 pytest tests/test_llm.py
```

### Tuning

- Long text is sent in pieces of `max_chunk_chars` characters. If the server reports that the context is too long, lower it, or raise the context length when you load the model in LM Studio.
- If the server rejects `response_format`, set `structured_output = "json_object"`, or `"none"` as a last resort.
- The model can still miss values or list harmless words. Harmless words can go into `[rules] allowlist`. Always look at the result before you paste it.
- Text that contains instructions aimed at the model ("ignore your rules") can make it list less. Layers 1 and 2 are not affected by this.

## Session vault

Each chat with an online AI should use its own session. Without a session name, the session `default` is used.

- Placeholders look like `[[EMAIL_1]]`. Within a session the same value always gets the same placeholder, also in later messages. A value already in the vault is hidden again even if no detector finds it the next time.
- Files: `~/.local/state/prompt-guard/<session>.json` (change with `[vault] dir`). The folder has mode 0700 and each file 0600. If the permissions get looser, they are tightened again on the next run.
- Expiry: a session not used for `ttl_hours` (default 24) is deleted the next time any session is opened. `ttl_hours = 0` keeps sessions until you clear them.
- The vault file holds every real value of the session. Do not copy it, back it up, or put it under git.

Check the vault folder and its permissions:

```bash
ls -la ~/.local/state/prompt-guard/
```

## Restore

Restore replaces placeholders in the AI's reply with the real values. It also accepts the forms chats often produce: `[[ X_1 ]]`, `\[\[X_1\]\]`, `[X_1]`, `<X_1>`, `&lt;X_1&gt;`. Single brackets and angle brackets are only replaced when the placeholder is in the vault, so normal text such as `[ITEM_1]` stays as it is.

A `[[X_N]]` placeholder that is not in the vault is left unchanged and reported as unknown. Usually the AI invented it; check that part of the reply by hand.

Tip: tell the online AI once at the start of the chat to keep `[[...]]` placeholders exactly as they are.

## Tests and fake secrets

The repo is public and GitHub push protection scans every push. Tests never contain token-shaped literals: `tests/fakes.py` builds obviously fake tokens from pieces at runtime. Follow the same rule for new tests.

## Usage

### Daily workflow

1. Copy the text for the AI (code, log, config, message).
2. Redact the clipboard and review what was hidden:

```bash
pgd redact --show
```

3. Paste into the online chat. Before sending, look at the text once more.
4. Copy the AI's reply, then restore your real values into the clipboard:

```bash
pgd restore
```

5. When the chat is over, delete its session:

```bash
pgd clear
```

### One session per chat

Placeholder numbers belong to a session. Use a name per chat so two chats do not mix:

```bash
pgd redact -s backup-script --show
```

```bash
pgd restore -s backup-script
```

List and delete sessions:

```bash
pgd sessions
```

```bash
pgd clear --all
```

### Pipes and files

If stdin is a pipe or a file, it is read instead of the clipboard. If stdout is a pipe or a file, the result goes there. `-i` and `-o` force stdin/stdout.

```bash
pgd redact < app.log > app.safe.log
```

```bash
journalctl -u myservice -n 200 | pgd redact -s logs | less
```

Messages and the `--show` list always go to stderr, so they never end up in the clipboard or the output file. `--show` masks values (for example `ops@…rg (15 chars)`), so real secrets do not stay in the terminal scrollback.

### Exit codes

- 0: done (also when nothing was found, or when restore warns about unknown placeholders)
- 1: error (bad config, empty input, empty or expired session, no clipboard tool); nothing is written
- 2: wrong command-line usage

### Troubleshooting

- `no desktop session found`: there is no DISPLAY, WAYLAND_DISPLAY or WSL, for example over SSH. Use pipes, or `-i` and `-o`.
- `no clipboard tool found`: install the tool named in the message (see "Clipboard tools").
- `session 'default' is empty or expired`: the session was cleared or not used for `ttl_hours`. Restore needs the same session that redacted the text.
- `layer 'ner' needs the optional extra`: install torch and the extra (see "Layer 2"), or run with `--no-ner`.
- `cannot load NER model`: the first download failed (no network) or the model name is wrong.
- `cannot reach http://...`: the LLM server is not running, "Serve on Local Network" is off, the firewall blocks port 1234, or `base_url` is wrong. Check with `pgd llm-check`.
- `server answered HTTP 400`: often the model id is wrong (check with `pgd llm-check`) or the server does not support `response_format` (see "Layer 3", "Tuning").
- `the model did not answer with JSON`: try `structured_output = "json_schema"`, or another model.
- `unknown placeholder(s)`: the AI wrote a placeholder that was never created. Check that part of the reply by hand.
