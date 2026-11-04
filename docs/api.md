# Endpoints

## `GET`

### `/health`

Returns `200 OK` when the server is running:

```json
{"status":"ok"}
```

## `POST`

If defaults are providen in `settings.ini`, then only `text` / `input_file` fields are required.

### `/speech`

Submit UTF-8 text directly as part of the request.

```sh
curl -X POST http://127.0.0.1:47864/speech \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from Kokoro.","output_file":"message.wav","language":"spanish","voice":"ef_dora","speed":0.75}'
```

### `/speech/file`

Upload a UTF-8 text file containing the text.

```sh
curl -X POST http://127.0.0.1:47864/speech/file \
  -F 'input_file=@message.txt;type=text/plain' \
  -F 'output_file=message.wav' \
  -F 'language=spanish' \
  -F 'voice=ef_dora' \
  -F 'speed=0.75'
```

# Fields

The fields marked as not required will take the values from `settings.ini`

| Name | Endpoint | Required | Description |
| --- | --- | --- | --- |
| `text` | JSON `/speech` | Yes | Nonempty UTF-8 text to synthesize. |
| `input_file` | Multipart `/speech/file` | Yes | File containing UTF-8 text. |
| `output_file` | Both | If no default | Destination file path, must end in `.wav` |
| `language` | Both | No | Accepted values: `american`, `british`, `japanese`, `mandarin`, `spanish`, `french`, `hindi`, `italian` |
| `voice` | Both | No | Accepted values can be found in [**Kokoro-82M**](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) |
| `speed` | Both | No | Accepts values from `0.1` to `2.0` |

# Responses

## Success

Both speech endpoints return `200 OK` after synthesis and writing the WAV:

```json
{
  "output_file": "/absolute/path/to/message.wav",
  "sample_rate": 24000,
  "duration_seconds": 2.5
}
```

1. `sample_rate` is in hertz.
2. `duration_seconds` is the generated audio duration.

## Errors

| Status | Meaning |
| --- | --- |
| `400 Bad Request` | Empty or invalid-UTF-8 upload, missing output parent directory, or output write failure. |
| `403 Forbidden` | Untrusted Host or browser Origin. |
| `413 Payload Too Large` | Text or total HTTP body exceeds its limit. |
| `422 Unprocessable Content` | Missing or invalid request fields (including an `output_file` that does not end in `.wav`), unsupported language, invalid speed, or missing upload part. |
| `500 Internal Server Error` | Speech synthesis failed; check the server log. |

1. Error responses use JSON, typically `{"detail":"..."}` for request/runtime errors.
2. Validation errors use `{"detail":[...]}`.

