# MoshiClient Enhanced Audio Buffering

## Overview

The MoshiClient has been enhanced to support arbitrary-length audio input and configurable output buffering, making it much more flexible for real-world applications.

## Key Improvements

### 1. Arbitrary-Length Audio Input
- **Before**: Required exactly 1920 samples (80ms @ 24kHz) for each `add_audio_input()` call
- **After**: Can accept any length audio data, automatically buffers and sends in 1920-sample chunks

### 2. Configurable Output Buffer Size
- **Before**: Fixed output chunks from server
- **After**: Configurable output chunk size with timeout support

### 3. Enhanced Threading Safety
- All operations are thread-safe with proper locking
- Non-blocking and timeout modes available

## API Changes

### Constructor
```python
client = MoshiClient(
    # ... existing parameters ...
    output_buffer_size=1920  # NEW: Configure output chunk size (default: 1920)
)
```

### Input Method (Enhanced)
```python
# Can now accept any length audio
client.add_audio_input(audio_data)  # audio_data can be any length

# Examples:
client.add_audio_input(np.random.randn(500).astype(np.float32))   # 500 samples
client.add_audio_input(np.random.randn(3000).astype(np.float32))  # 3000 samples
client.add_audio_input(np.random.randn(100).astype(np.float32))   # 100 samples
```

### Output Method (Enhanced)
```python
# New timeout parameter
audio = client.get_audio_output(timeout=None)  # Block until data available
audio = client.get_audio_output(timeout=0)     # Non-blocking, return immediately  
audio = client.get_audio_output(timeout=1.0)   # Wait up to 1 second

# Returns exactly 'output_buffer_size' samples or None on timeout
```

## Usage Examples

### Basic Usage
```python
# Create client with 40ms output chunks (960 samples @ 24kHz)
client = MoshiClient(output_buffer_size=960)
client.connect("ws://localhost:8998/api/chat")

# Send audio of any length
microphone_chunk = record_audio()  # Any length
client.add_audio_input(microphone_chunk)

# Get response with timeout
response = client.get_audio_output(timeout=0.5)
if response is not None:
    play_audio(response)  # Always 960 samples
```

### Real-time Streaming
```python
client = MoshiClient(output_buffer_size=480)  # 20ms chunks for low latency

while streaming:
    # Variable-length input (e.g., from microphone callback)
    mic_data = get_microphone_data()  # Could be 256, 512, 1024 samples etc.
    client.add_audio_input(mic_data)
    
    # Non-blocking output check
    response = client.get_audio_output(timeout=0)
    if response is not None:
        play_audio(response)  # Always 480 samples
```

### Batch Processing
```python
client = MoshiClient(output_buffer_size=4800)  # 200ms chunks for efficiency

# Process large audio file in arbitrary chunks
audio_file = load_audio_file()  # Large file
chunk_size = 1000  # Process in 1000-sample chunks

for i in range(0, len(audio_file), chunk_size):
    chunk = audio_file[i:i+chunk_size]
    client.add_audio_input(chunk)
    
    # Collect responses
    while True:
        response = client.get_audio_output(timeout=0.1)
        if response is None:
            break
        process_response(response)  # Always 4800 samples
```

## Internal Behavior

### Input Buffering
1. Audio data is accumulated in an internal buffer (`_input_audio_buffer`)
2. When buffer reaches 1920 samples, a complete chunk is sent to the server
3. Remaining samples stay in buffer for next call
4. Thread-safe with proper locking

### Output Buffering  
1. Decoded audio from server is accumulated in an internal buffer (`_output_audio_buffer`)
2. `get_audio_output()` waits until requested amount is available
3. Returns exactly `output_buffer_size` samples or None on timeout
4. Thread-safe queue management

## Compatibility

- **Backward Compatible**: Existing code continues to work unchanged
- **Server Protocol**: Still sends 1920-sample chunks to server as required
- **Audio Format**: Still uses 24kHz, mono, float32 PCM

## Performance Benefits

1. **Reduced Overhead**: No need to manually chunk audio data
2. **Better Real-time Performance**: Configurable output sizes for different latency requirements
3. **Memory Efficient**: Proper buffering prevents memory buildup
4. **Thread Safety**: Safe for multi-threaded applications

## Testing

Run the included tests to verify functionality:

```bash
# Basic functionality test
python test_buffering.py

# Detailed functionality test  
python test_buffering_detailed.py

# Usage examples
python example_enhanced_usage.py
```

## Migration Guide

### From Old API
```python
# OLD: Had to chunk to exactly 1920 samples
chunk_size = 1920
for i in range(0, len(audio), chunk_size):
    chunk = audio[i:i+chunk_size]
    if len(chunk) == chunk_size:  # Skip incomplete chunks
        client.add_audio_input(chunk)

response = client.get_audio_output()  # Blocking, no timeout
```

### To New API
```python
# NEW: Send any length audio
client.add_audio_input(audio)  # Any length, automatically handled

# NEW: Configurable timeout
response = client.get_audio_output(timeout=1.0)  # 1 second timeout
```

## Configuration Recommendations

| Use Case                 | `output_buffer_size` | Reasoning             |
| ------------------------ | -------------------- | --------------------- |
| Real-time conversation   | 480 (20ms)           | Low latency           |
| Interactive applications | 960 (40ms)           | Good balance          |
| Default/general use      | 1920 (80ms)          | Matches server chunks |
| Batch processing         | 4800 (200ms)         | High efficiency       |

The enhanced MoshiClient provides much better flexibility and performance for real-world audio applications while maintaining full backward compatibility.