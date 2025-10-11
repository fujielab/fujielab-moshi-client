# fujielab-moshi-client

Fujie lab. version of Moshi client library for Python programs.

## Overview
A Moshi client library for voice assistants and chatbots. Enables sending and receiving audio and text data via WebSocket.

## Installation
```bash
pip install fujielab-moshi-client
```

Or clone the repository and install dependencies with requirements.txt:
```bash
pip install -r requirements.txt
```

## Usage
### MoshiClient Class Example
```python
from fujielab.moshi.moshi_client_lib import MoshiClient
import numpy as np

# Initialize MoshiClient
client = MoshiClient()

# Connect to server (blocking)
client.connect("ws://localhost:8998/api/chat")

# Send audio data (PCM float32, 1D np.array)
audio_data = np.array([...], dtype=np.float32)
client.add_audio_input(audio_data)

# Get audio data from server
received_audio = client.get_audio_output()

# Get text response from server
text_response = client.get_text_output()

# Disconnect
client.disconnect()
```

## MoshiClient Parameters
- text_temperature: Temperature parameter for text generation (default: 0.7)
- text_topk: Top-K sampling for text generation (default: 25)
- audio_temperature: Temperature parameter for audio generation (default: 0.8)
- audio_topk: Top-K sampling for audio generation (default: 250)
- pad_mult: Audio padding multiplier (default: 0.0)
- repetition_penalty: Repetition penalty (default: 1.0)
- repetition_penalty_context: Context length for repetition penalty (default: 64)
- output_buffer_size: Size of audio output buffer (default: 1920 samples)

### About Audio Frame Size

**Audio Input (add_audio_input)**:
- You can send audio data of any size
- Internally buffered automatically to the appropriate size (1920 samples) and sent to the Moshi server
- Example: 160 samples, 480 samples, 2000 samples, etc. - any size is supported

**Audio Output (get_audio_output)**:
- The size of output audio data must be specified in the `MoshiClient` constructor
- Specified with the `output_buffer_size` parameter (default: 1920 samples)
- Example:
```python
# To get 480 samples (20ms @ 24kHz) at a time
client = MoshiClient(output_buffer_size=480)

# To get 960 samples (40ms @ 24kHz) at a time
client = MoshiClient(output_buffer_size=960)
```

**Important Notes**:
The Moshi server generates audio in 80ms (1920 samples) units.
Therefore, please note the following points in operation:
- When providing data less than 1920 samples with `add_audio_input`, it will not be sent to the Moshi server immediately.
  Data accumulates in the internal buffer and is sent together when it reaches 1920 samples.
- If you call `get_audio_output` before data is sent to the Moshi server, no audio data will be returned.

### Running Simple Client
```bash
python -m fujielab.moshi.simple_moshi_client
```

## Dependencies
- websockets
- sounddevice
- numpy
- opuslib

## License
Apache License 2.0
See [LICENSE](LICENSE) for details.
