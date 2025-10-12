#!/usr/bin/env python3
"""
Enhanced MoshiClient Usage Example
==================================

This example demonstrates how to use the enhanced MoshiClient with arbitrary-length
audio input/output functionality.

Key Features:
1. Input: Can accept any length audio, internally buffers to 1920-sample chunks
2. Output: Configurable chunk size with timeout support
3. Thread-safe operations
"""

import numpy as np
import time
import asyncio
from fujielab.moshi.moshi_client_lib import MoshiClient, MOSHI_SAMPLE_RATE


def generate_test_audio(duration_ms, frequency=440):
    """Generate test audio with specified duration in milliseconds"""
    samples = int(MOSHI_SAMPLE_RATE * duration_ms / 1000)
    t = np.arange(samples) / MOSHI_SAMPLE_RATE
    audio = np.sin(2 * np.pi * frequency * t).astype(np.float32) * 0.1
    return audio


async def enhanced_client_example():
    """Demonstrate enhanced MoshiClient functionality"""

    print("Enhanced MoshiClient Example")
    print("=" * 40)

    # 1. Create client with custom output buffer size
    # This will return 40ms chunks (960 samples @ 24kHz) instead of default 80ms
    client = MoshiClient(output_buffer_size=960)  # 40ms chunks

    print(f"Created client with {client.output_buffer_size} sample output buffer")
    print(
        f"This equals {client.output_buffer_size / MOSHI_SAMPLE_RATE * 1000:.1f}ms at {MOSHI_SAMPLE_RATE}Hz"
    )

    # 2. Connect to Moshi server (replace with actual server URL when available)
    server_url = "ws://localhost:8998/api/chat"
    print(f"\nConnecting to: {server_url}")

    try:
        client.connect(server_url)
        print("✅ Connected successfully!")

        # 3. Demonstrate arbitrary-length input
        print("\n=== Arbitrary-Length Input Demo ===")

        # Create audio chunks of various sizes
        audio_chunks = [
            ("Short burst", generate_test_audio(25)),  # 25ms -> 600 samples
            ("Medium chunk", generate_test_audio(65)),  # 65ms -> 1560 samples
            ("Long chunk", generate_test_audio(150)),  # 150ms -> 3600 samples
            ("Tiny fragment", generate_test_audio(5)),  # 5ms -> 120 samples
            ("Another medium", generate_test_audio(90)),  # 90ms -> 2160 samples
        ]

        print("Sending audio chunks of various sizes:")
        for name, audio in audio_chunks:
            client.add_audio_input(audio)
            print(
                f"  {name}: {len(audio)} samples ({len(audio)/MOSHI_SAMPLE_RATE*1000:.1f}ms)"
            )

        print(f"\nAll chunks buffered and sent as complete 1920-sample frames")

        # 4. Demonstrate configurable output with timeout
        print("\n=== Configurable Output Demo ===")

        print("Waiting for audio responses...")

        # Try different timeout scenarios
        scenarios = [
            ("Non-blocking check", 0),  # Return immediately
            ("Short timeout", 0.1),  # 100ms timeout
            ("Medium timeout", 0.5),  # 500ms timeout
            ("Long timeout", 2.0),  # 2 second timeout
        ]

        for name, timeout in scenarios:
            start_time = time.time()
            audio_output = client.get_audio_output(timeout=timeout)
            elapsed = time.time() - start_time

            if audio_output is not None:
                print(f"  {name}: ✅ Got {len(audio_output)} samples in {elapsed:.3f}s")

                # Analyze audio quality
                rms = np.sqrt(np.mean(audio_output**2))
                max_amp = np.max(np.abs(audio_output))
                print(f"    Audio stats: RMS={rms:.4f}, Max={max_amp:.4f}")
            else:
                print(f"  {name}: ⏰ Timeout after {elapsed:.3f}s")

        # 5. Real-time simulation
        print("\n=== Real-time Simulation ===")
        print("Simulating real-time audio streaming...")

        # Simulate microphone input with varying chunk sizes
        mic_chunk_sizes = [512, 256, 1024, 384, 768]  # Typical microphone buffer sizes

        for i, chunk_size in enumerate(mic_chunk_sizes):
            # Generate audio chunk (simulate microphone input)
            mic_audio = generate_test_audio(
                chunk_size / MOSHI_SAMPLE_RATE * 1000, 220 + i * 55
            )

            # Send to Moshi
            client.add_audio_input(mic_audio)
            print(f"  Mic chunk {i+1}: {chunk_size} samples -> buffered")

            # Try to get response (non-blocking)
            response = client.get_audio_output(timeout=0)
            if response is not None:
                print(f"    Got response: {len(response)} samples")

            # Simulate real-time delay
            await asyncio.sleep(0.02)  # 20ms delay

        # 6. Text responses
        print("\n=== Text Response Demo ===")
        text_responses = []
        for _ in range(5):  # Check for text responses
            text = client.get_text_output()
            if text:
                text_responses.append(text)

        if text_responses:
            print("Received text responses:")
            for i, text in enumerate(text_responses, 1):
                print(f"  {i}. {text}")
        else:
            print("No text responses received")

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("This is expected if no Moshi server is running")

        # Demonstrate offline functionality
        print("\n=== Offline Functionality Demo ===")
        demonstrate_offline_features(client)

    finally:
        # Cleanup
        if client.is_connected():
            client.disconnect()
            print("\n✅ Disconnected successfully")


def demonstrate_offline_features(client):
    """Demonstrate features that work without server connection"""
    print("Demonstrating buffering without server connection...")

    # Temporarily bypass connection check for demo
    client.is_connected = lambda: True

    # Show input buffering
    print("\n1. Input buffering:")
    sizes = [300, 800, 1200, 500, 2000]
    for size in sizes:
        audio = generate_test_audio(size / MOSHI_SAMPLE_RATE * 1000)
        client.add_audio_input(audio)
        queue_items = client.audio_input_queue.qsize()
        buffer_samples = len(client._input_audio_buffer)
        print(
            f"   Added {size} samples -> Queue: {queue_items} items, Buffer: {buffer_samples} samples"
        )

    # Show output buffering simulation
    print("\n2. Output buffering:")
    # Add some test audio to output queue
    for i in range(3):
        test_audio = generate_test_audio(20, 440 + i * 110)  # 20ms chunks
        client.audio_output_queue.put_nowait(test_audio)

    # Try to get configured output size
    result = client.get_audio_output(timeout=0.1)
    if result is not None:
        print(
            f"   Got output: {len(result)} samples (requested: {client.output_buffer_size})"
        )
    else:
        print("   No output available")


def main():
    """Main function"""
    print("Enhanced MoshiClient Demo")
    print("This demonstrates the new arbitrary-length audio features")
    print("\nKey improvements:")
    print("• Input: Accept any audio length, buffer internally to 1920-sample chunks")
    print("• Output: Configurable chunk size with timeout support")
    print("• Better real-time performance and flexibility")
    print("\n" + "=" * 60)

    # Run the async demo
    asyncio.run(enhanced_client_example())

    print("\n" + "=" * 60)
    print("Demo completed! Key takeaways:")
    print("✅ Can send audio of any length - no need to chunk to 1920 samples")
    print("✅ Can configure output chunk size based on your needs")
    print("✅ Timeout support prevents blocking when no audio available")
    print("✅ Thread-safe operations for real-time applications")


if __name__ == "__main__":
    main()
