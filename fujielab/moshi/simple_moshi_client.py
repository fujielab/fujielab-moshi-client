#!/usr/bin/env python3
"""
Simple Moshi Client - Minimal Example
====================================

Simplest possible Moshi client implementation.
No functions, no classes - just the main section.

Requirements:
- pip install websockets sounddevice numpy opuslib

Usage:
    python simple_moshi_client.py
"""

import sounddevice as sd
import numpy as np
import logging
import signal
import time

from .moshi_client_lib import MoshiClient, SAMPLE_RATE, CHANNELS

# Simple logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    # Configuration
    SERVER_URL = "ws://localhost:8998/api/chat"
    BUFFER_SIZE = 1920  # Perfect match with Moshi frame size

    # Set global and module log level to WARNING
    logging.getLogger().setLevel(logging.WARNING)
    logger.setLevel(logging.WARNING)

    print("🎤 Simple Moshi Client Starting...")
    print(f"Server: {SERVER_URL}")
    print(f"Audio: {SAMPLE_RATE}Hz, {CHANNELS} channel(s), buffer={BUFFER_SIZE}")
    print("Press Ctrl+C to stop")

    # Initialize components
    client = MoshiClient(
        text_temperature=0.3,  # 0.7,
        text_topk=25,
        audio_temperature=0.5,  # 0.8,
        audio_topk=250,
        pad_mult=0.0,
        repetition_penalty=1.0,
        repetition_penalty_context=64,
    )
    audio_queue = []  # Simple list to store received audio
    running = True

    # Audio input callback - records from microphone
    def audio_input_callback(indata, frames, time, status):
        if status:
            logger.warning(f"Input status: {status}")
        if running:
            # Convert to mono and send to client
            mono_audio = np.mean(indata, axis=1) if indata.ndim > 1 else indata
            client.add_audio_input(mono_audio.astype(np.float32))

    # Audio output callback - plays received audio
    def audio_output_callback(outdata, frames, time, status):
        if status:
            logger.warning(f"Output status: {status}")

        outdata.fill(0)  # Start with silence

        # Get audio from client and add to our simple queue
        while True:
            received_audio = client.get_audio_output()
            if received_audio is None:
                break
            audio_queue.append(received_audio)

        # Play audio from queue
        output_samples = 0
        while audio_queue and output_samples < frames:
            chunk = audio_queue[0]
            remaining_frames = frames - output_samples

            if len(chunk) <= remaining_frames:
                # Use entire chunk
                outdata[output_samples : output_samples + len(chunk), 0] = chunk
                output_samples += len(chunk)
                audio_queue.pop(0)
            else:
                # Use partial chunk
                outdata[output_samples : output_samples + remaining_frames, 0] = chunk[
                    :remaining_frames
                ]
                audio_queue[0] = chunk[remaining_frames:]
                output_samples += remaining_frames

    # Signal handler for clean shutdown
    def signal_handler(signum, frame):
        global running
        print("\n🛑 Stopping...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize stream variables
    input_stream = None
    output_stream = None

    try:
        # Connect to Moshi server
        print("🔌 Connecting to Moshi server...")
        client.connect(SERVER_URL)
        print("✅ Connected!")

        # Start audio input stream (microphone)
        print("🎤 Starting microphone...")
        input_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            callback=audio_input_callback,
            blocksize=BUFFER_SIZE,
            dtype=np.float32,
        )
        input_stream.start()

        # Start audio output stream (speakers)
        print("🔊 Starting speakers...")
        output_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            callback=audio_output_callback,
            blocksize=BUFFER_SIZE,
            dtype=np.float32,
        )
        output_stream.start()

        print("🎉 Ready! Speak into microphone...")

        # Simple text output loop
        message_count = 0
        while running and client.is_connected():
            # Check for text responses
            text_response = client.get_text_output()
            if text_response:
                message_count += 1
                print(f"💬 Moshi #{message_count}: {text_response}")

            # Small delay to prevent busy waiting
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Cleanup
        running = False
        print("🧹 Cleaning up...")

        try:
            if input_stream is not None:
                input_stream.stop()
                input_stream.close()
                print("🎤 Microphone stopped")
        except:
            pass

        try:
            if output_stream is not None:
                output_stream.stop()
                output_stream.close()
                print("🔊 Speakers stopped")
        except:
            pass

        try:
            client.disconnect()
            print("🔌 Disconnected from server")
        except:
            pass

        print("✅ Cleanup complete")
        print("👋 Goodbye!")
