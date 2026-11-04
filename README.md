![badge-python](https://img.shields.io/badge/python-blue) ![badge-kokoro](https://img.shields.io/badge/kokoro-orange) ![badge-server](https://img.shields.io/badge/tts_server-grey) ![badge-version](https://img.shields.io/badge/v0.1.0-green)

Multilingual text-to-speech server intended for clients running on the same machine. This is a trusted local API, not a public internet service, It has no authentication and requires no credentials. Accepts HTTP requests and writes generated WAV files to paths on the machine running the server.

This project uses [**hexgrad/kokoro**](https://github.com/hexgrad/kokoro) library.

## Requirements

- Python `3.10` - `3.12`
- Spanish, French, Hindi, and Italian text processing may require the `espeak-ng` package.

## Installation

**Linux/macOS:**

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

### NVIDIA Acceleration (Optional)

To install PyTorch, use the selector at <https://pytorch.org/get-started/locally/> , choose your preferences and copy the command displayed then run it, example: `python -m pip install torch torchvision`

After the PyTorch installation has been done, run the following check:

```sh
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA runtime:', torch.version.cuda); print('CUDA available:', torch.cuda.is_available())"
```

## Run Server

Simply run it via:

```sh
python -m kokoro_server
```

Or specify a configuration file:

```sh
python -m kokoro_server --config <file_path>
```

## Configuration

On first startup, `settings.ini` is created in the user configuration directory with the following defaults:

- Linux: `$XDG_CONFIG_HOME/kokoro-server/settings.ini` (normally `~/.config/kokoro-server/settings.ini`)
- macOS: `~/Library/Application Support/kokoro-server/settings.ini`
- Windows: `%LOCALAPPDATA%\kokoro-server\settings.ini`

```ini
[server]
port = 47864
additional_origins =
detailed_logs = false

[engine]
device = auto
max_input_kib = 1024
output_file =

[speech]
language = american
voice = af_kore,af_bella
speed = 0.80
```

### Settings

| Field | Description |
| --- | --- |
| `port` | HTTP listening port, from `1` to `65535`. |
| `additional_origins` | Optional comma-separated trusted browser origins, explicit HTTP(S) origins without paths or wildcards. |
| `detailed_logs` | `true` or `false`, Include query strings and request/response details in logs. |
| `device` | `auto`, `cpu`, or `cuda` (`auto` selects CUDA when available, otherwise CPU.) |
| `max_input_kib` | Maximum UTF-8 text size in KiB (`1024` KiB = `1` MiB). |
| `output_file` | Optional default WAV output path. If empty, requests must provide a path. |
| `language` | Default language used when a request omits it: `american`, `british`, `japanese`, `mandarin`, `spanish`, `french`, `hindi`, or `italian`. |
| `voice` | Default voice, accepted values can be found [**HERE**](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md). Requests can override it. |
| `speed` | Default speed from `0.1` to `2.0`. Requests can override it. |

1. To allow a separate trusted web app, set e.g. `additional_origins = http://localhost:3000, https://my-app.example`. Each allowed site can submit requests and overwrite WAV files accessible to the server user.

2. Logs contain the client, method, endpoint path, and status. Enabling `detailed_logs` will include the query strings, JSON text, and response bodies.

3. A larger `max_input_kib` limit can significantly increase synthesis time and memory, multiple concurrent requests can use multiples of this memory. These limits do not guarantee low model memory usage.

4. To select another settings file use the option `--config <path>`, example: `python -m kokoro_server --config other.ini`

## Generate speech

Refer to the [API documentation](docs/api.md) for endpoints, request formats, and client examples.

**Linux/macOS:**

```sh
curl -X POST http://127.0.0.1:47864/speech \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello! This model stays loaded between requests.","output_file":"sample.wav"}'

curl -X POST http://127.0.0.1:47864/speech/file \
  -F 'input_file=@message.txt;type=text/plain' \
  -F 'output_file=sample.wav' \
  -F 'language=spanish' \
  -F 'voice=ef_dora' \
  -F 'speed=0.75'
```

**Windows PowerShell**:

```powershell
curl.exe -X POST http://127.0.0.1:47864/speech `
  -H 'Content-Type: application/json' `
  -d '{"text":"Hello! This model stays loaded between requests.","output_file":"sample.wav"}'

curl.exe -X POST http://127.0.0.1:47864/speech/file `
  -F 'input_file=@message.txt;type=text/plain' `
  -F 'output_file=sample.wav' `
  -F 'language=spanish' `
  -F 'voice=ef_dora' `
  -F 'speed=0.75'
```

### Smoke test

With the server running, open a second terminal in the project folder and run:

```sh
python scripts/sample.py
```

The script sends a sample request to the default address and prints the output WAV path. It uses only Python's standard library and assumes the server is using port `47864`.

## Troubleshooting

- **Cannot connect:** wait for startup to finish, keep the terminal open, and check the configured port.
- **CUDA errors:** check PyTorch CUDA availability as described above and install a compatible build if needed. If GPU acceleration is not required, set `device = cpu` and restart. Automatic selection does not recover from every broken GPU installation.
- **Download failures:** check your internet connection and retry after fixing it.
- **HTTP 422:** check the request fields and speed/language values.
- **HTTP 400:** check the output path, parent directory, permissions, and UTF-8 file contents.
- **HTTP 403:** check the request Host and browser origin; configure trusted additional origins if needed.
- **HTTP 413:** text or the total request exceeds the configured size limit.
- **HTTP 500:** check the server console for synthesis/model/voice errors.
- **Configuration errors:** fix the INI file or remove it to regenerate defaults.

