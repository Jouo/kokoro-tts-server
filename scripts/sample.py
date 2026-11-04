import json
from urllib.request import Request, urlopen


data = json.dumps({"text": "This is a sample audio file from Kokoro", "output_file": "sample.wav"}).encode("utf-8")
request = Request(
    "http://127.0.0.1:47864/speech",
    data=data,
    headers={"Content-Type": "application/json"},
)

with urlopen(request) as response:
    print(json.load(response)["output_file"])

