#!/usr/bin/env python3
"""
Simple Moshi Client - Minimal Example
====================================

Simplest possible Moshi client implementation with CLI overrides.
No functions, no classes - just the main section.

Requirements:
- pip install websockets sounddevice numpy opuslib soxr

Usage examples:
    # Default
    python simple_moshi_client.py

    # Change server URL and audio I/O sample rate
    python simple_moshi_client.py -s ws://localhost:8998/api/chat -r 48000

    # Tune MOSHI generation parameters
    python simple_moshi_client.py --text-temperature 0.5 --audio-temperature 0.7 --text-topk 40
"""

import sounddevice as sd
import numpy as np
import logging
import signal
import time
import soxr
import argparse

from .moshi_client_lib import MoshiClient, MOSHI_SAMPLE_RATE, MOSHI_CHANNELS

# Simple logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Simple Moshi client (voice chat)")
    parser.add_argument("-s", "--server", default="ws://localhost:8998/api/chat", help="Moshi server WebSocket URL")
    parser.add_argument("-r", "--audio-io-sample-rate", type=int, default=16000, help="Audio I/O sample rate for microphone/speaker (Hz)")
    parser.add_argument("-b", "--buffer-size", type=int, default=1920, help="Audio block size (frames) for I/O and client output buffer")

    # Moshi generation parameters (CLI overrides)
    parser.add_argument("--text-temperature", type=float, default=0.7, help="Text generation temperature")
    parser.add_argument("--text-topk", type=int, default=25, help="Text generation top-k")
    parser.add_argument("--audio-temperature", type=float, default=0.8, help="Audio generation temperature")
    parser.add_argument("--audio-topk", type=int, default=250, help="Audio generation top-k")
    parser.add_argument("--pad-mult", type=float, default=0.0, help="Padding multiplier")
    parser.add_argument("--repetition-penalty", type=float, default=1.0, help="Repetition penalty")
    parser.add_argument("--repetition-penalty-context", type=int, default=64, help="Repetition penalty context size")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="WARNING", help="Logging level")

    args = parser.parse_args()

    # Derived configuration
    SERVER_URL = args.server
    AUDIO_IO_SAMPLE_RATE = args.audio_io_sample_rate
    BUFFER_SIZE = args.buffer_size  # Often matches MOSHI frame size (1920)

    # Set global and module log level to WARNING
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    logger.setLevel(getattr(logging, args.log_level))

    print("🎤 Simple Moshi Client Starting...")
    print(f"Server: {SERVER_URL}")
    print(f"Audio: {MOSHI_SAMPLE_RATE}Hz, {MOSHI_CHANNELS} channel(s), buffer={BUFFER_SIZE}")
    print(f"Audio I/O: {AUDIO_IO_SAMPLE_RATE}Hz")
    print("Press Ctrl+C to stop")

    # Create resamplers based on runtime configuration (streaming)
    # soxr uses absolute rates instead of ratio and maintains internal state.
    input_resampler = soxr.ResampleStream(
        AUDIO_IO_SAMPLE_RATE,  # input rate from mic
        MOSHI_SAMPLE_RATE,     # target rate for model
        MOSHI_CHANNELS,        # channels
        dtype='float32',       # we operate on float32
        quality='VHQ',         # very high quality to match previous 'sinc_best'
    )
    output_resampler = soxr.ResampleStream(
        MOSHI_SAMPLE_RATE,     # input rate from model
        AUDIO_IO_SAMPLE_RATE,  # target rate for speakers
        MOSHI_CHANNELS,
        dtype='float32',
        quality='VHQ',
    )

    # Initialize components
    client = MoshiClient(
        text_temperature=args.text_temperature,
        text_topk=args.text_topk,
        audio_temperature=args.audio_temperature,
        audio_topk=args.audio_topk,
        pad_mult=args.pad_mult,
        repetition_penalty=args.repetition_penalty,
        repetition_penalty_context=args.repetition_penalty_context,
        output_buffer_size=BUFFER_SIZE,
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

            # Ensure float32 for soxr stream
            mono_audio = mono_audio.astype(np.float32, copy=False)

            # Resample to model sample rate
            resampled_mono_audio = input_resampler.resample_chunk(mono_audio, last=False)

            client.add_audio_input(resampled_mono_audio.astype(np.float32, copy=False))

    # Audio output callback - plays received audio
    audio_buffer = np.zeros((0,), dtype=np.float32)  # Buffer to hold leftover audio between calls
    def audio_output_callback(outdata, frames, time, status):
        global running, audio_buffer
        if status:
            logger.warning(f"Output status: {status}")

        outdata.fill(0)  # Start with silence

        try:
            received_audio = None
            while len(audio_buffer) < frames and running and client.is_connected():
                # Get audio from client and play it
                received_audio = client.get_audio_output(timeout=5)  # Block and wait

                if received_audio is not None:
                    # Ensure float32 for soxr stream
                    received_audio = received_audio.astype(np.float32, copy=False)

                    # Resample to audio I/O sample rate
                    resampled_received_audio = output_resampler.resample_chunk(received_audio, last=False)

                    audio_buffer = np.concatenate((audio_buffer, resampled_received_audio))

            if len(audio_buffer) < frames and received_audio is None:
                logger.error("Received audio is None - stopping client")
                running = False
                return

            audio_to_play = audio_buffer[:frames]
            audio_buffer = audio_buffer[frames:]

            if len(audio_to_play) != frames:
                logger.error(
                    f"Audio frame size mismatch: received {len(audio_to_play)}, expected {frames} - stopping client"
                )
                running = False
                return

            outdata[:, 0] = audio_to_play

        except Exception as e:
            logger.error(f"Error in audio output callback: {e} - stopping client")
            running = False

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
            samplerate=AUDIO_IO_SAMPLE_RATE,
            channels=MOSHI_CHANNELS,
            callback=audio_input_callback,
            blocksize=BUFFER_SIZE,
            dtype=np.float32,
        )
        input_stream.start()

        # Start audio output stream (speakers)
        print("🔊 Starting speakers...")
        output_stream = sd.OutputStream(
            samplerate=AUDIO_IO_SAMPLE_RATE,
            channels=MOSHI_CHANNELS,
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
