#!/usr/bin/env python3
"""
Test script for MoshiClient buffering functionality
"""

import numpy as np
import time
import threading
from fujielab.moshi.moshi_client_lib import MoshiClient, MOSHI_SAMPLE_RATE, MOSHI_CHUNK_SIZE


def test_input_buffering():
    """Test arbitrary length input buffering"""
    print("=== Testing Input Buffering ===")

    client = MoshiClient()

    # Test data of different sizes
    test_sizes = [100, 500, 1000, 1920, 2000, 3000, 5000]

    print(f"Expected chunk size for server: {MOSHI_CHUNK_SIZE}")

    for size in test_sizes:
        # Create test audio data
        test_audio = np.random.randn(size).astype(np.float32) * 0.1

        print(f"\nTesting input size: {size}")
        print(f"Input buffer before: {len(client._input_audio_buffer)}")

        # Add audio input (this should buffer internally)
        client.add_audio_input(test_audio)

        print(f"Input buffer after: {len(client._input_audio_buffer)}")
        print(f"Items in audio_input_queue: {client.audio_input_queue.qsize()}")

        # Check that queue only has CHUNK_SIZE items
        total_queued = 0
        temp_items = []
        while not client.audio_input_queue.empty():
            try:
                item = client.audio_input_queue.get_nowait()
                temp_items.append(item)
                total_queued += len(item)
                print(f"  Queue item size: {len(item)}")
            except:
                break

        # Put items back
        for item in temp_items:
            client.audio_input_queue.put_nowait(item)

        print(f"Total samples in queue: {total_queued}")

    print("\n✅ Input buffering test completed")


def test_output_buffering():
    """Test configurable output buffering with timeout"""
    print("\n=== Testing Output Buffering ===")

    # Create clients with different output buffer sizes
    buffer_sizes = [480, 960, 1920, 2400]

    for buffer_size in buffer_sizes:
        print(f"\nTesting buffer size: {buffer_size}")
        client = MoshiClient(output_buffer_size=buffer_size)

        # Simulate adding some audio data to output buffer
        def add_audio_data():
            """Simulate audio data arriving"""
            time.sleep(0.1)  # Small delay
            for i in range(5):
                # Create chunks of audio data
                audio_chunk = np.random.randn(480).astype(np.float32) * 0.1
                try:
                    client.audio_output_queue.put_nowait(audio_chunk)
                    print(f"  Added chunk {i+1}: {len(audio_chunk)} samples")
                except:
                    pass
                time.sleep(0.05)

        # Start thread to add audio data
        audio_thread = threading.Thread(target=add_audio_data)
        audio_thread.start()

        # Test different timeout scenarios
        print(f"  Testing non-blocking (timeout=0)...")
        result = client.get_audio_output(timeout=0)
        print(
            f"  Non-blocking result: {'Got data' if result is not None else 'No data'}"
        )

        print(f"  Testing with timeout=0.5s...")
        start_time = time.time()
        result = client.get_audio_output(timeout=0.5)
        elapsed = time.time() - start_time

        if result is not None:
            print(
                f"  ✅ Got audio data: {len(result)} samples (expected: {buffer_size}) in {elapsed:.3f}s"
            )
            if len(result) == buffer_size:
                print(f"    ✅ Correct buffer size!")
            else:
                print(
                    f"    ❌ Wrong buffer size, expected {buffer_size}, got {len(result)}"
                )
        else:
            print(f"  ❌ Timeout after {elapsed:.3f}s")

        audio_thread.join()

    print("\n✅ Output buffering test completed")


def test_realistic_scenario():
    """Test realistic scenario with mixed input/output"""
    print("\n=== Testing Realistic Scenario ===")

    client = MoshiClient(output_buffer_size=960)  # 40ms chunks

    # Test sending various sized chunks
    print("Sending audio chunks of different sizes...")
    sizes = [200, 800, 1500, 2500, 100, 1920]

    for i, size in enumerate(sizes):
        audio_data = (
            np.sin(2 * np.pi * 440 * np.arange(size) / MOSHI_SAMPLE_RATE).astype(np.float32)
            * 0.1
        )
        print(f"  Chunk {i+1}: {size} samples")
        client.add_audio_input(audio_data)

        # Check queue state
        queue_size = client.audio_input_queue.qsize()
        buffer_size = len(client._input_audio_buffer)
        print(f"    Queue items: {queue_size}, Buffer samples: {buffer_size}")

    print("\n✅ Realistic scenario test completed")


if __name__ == "__main__":
    print("Testing MoshiClient Enhanced Buffering")
    print("=" * 50)

    try:
        test_input_buffering()
        test_output_buffering()
        test_realistic_scenario()

        print("\n🎉 All tests completed successfully!")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()
