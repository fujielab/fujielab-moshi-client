#!/usr/bin/env python3
"""
Moshi Client Library - Pure Python Implementation
===============================================

A reusable MoshiClient class for voice assistant integration.
No FFmpeg dependency - uses opuslib for Opus encoding/decoding.

Requirements:
- pip install websockets sounddevice numpy opuslib

Usage:
    from moshi_client_lib import MoshiClient

    client = MoshiClient()
    await client.connect("ws://localhost:8998/api/chat")

    # Send audio data (PCM float32)
    audio_data = np.array([...], dtype=np.float32)
    await client.send_audio(audio_data)

    # Get received audio data
    received_audio = await client.get_audio()

    # Get text responses
    text_response = await client.get_text()

    await client.disconnect()
"""

import asyncio
import websockets
import json
import threading
import time
import logging
import os
import numpy as np
import queue
from typing import Optional, List
import struct

# Audio processing with opuslib for Opus encoding/decoding
try:
    import opuslib

    OPUSLIB_AVAILABLE = True
except ImportError:
    print("opuslib is required for audio processing. Install with:")
    print("  pip install opuslib")
    exit(1)

# Configuration
MOSHI_SAMPLE_RATE = 24000  # Moshi uses 24kHz
MOSHI_CHANNELS = 1  # Mono
MOSHI_CHUNK_SIZE = 1920  # 80ms at 24kHz - Moshi's standard frame size
MOSHI_OPUS_FRAME_SIZE = 1920  # 80ms frames for Opus encoding

# Moshi generation parameters (same as Web interface defaults)
MOSHI_DEFAULT_TEXT_TEMPERATURE = 0.7
MOSHI_DEFAULT_TEXT_TOPK = 25
MOSHI_DEFAULT_AUDIO_TEMPERATURE = 0.8
MOSHI_DEFAULT_AUDIO_TOPK = 250
MOSHI_DEFAULT_PAD_MULT = 0.0
MOSHI_DEFAULT_REPETITION_PENALTY = 1.0
MOSHI_DEFAULT_REPETITION_PENALTY_CONTEXT = 64

# Logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce some noisy loggers
logging.getLogger("websockets").setLevel(logging.WARNING)

# Enable debug for specific components when needed
if os.environ.get("FUJIELAB_MOSHI_CLIENT_DEBUG"):
    logger.setLevel(logging.DEBUG)


class OggContainer:
    """Simple Ogg container for Opus packets"""

    def __init__(self, serial_number=42):
        self.serial_number = serial_number
        self.page_sequence = 0
        self.granule_position = 0

    def create_opus_header(self):
        """Create OpusHead header page"""
        # OpusHead packet
        opus_head = struct.pack(
            "<8sBBHIhB",
            b"OpusHead",  # Magic signature
            1,  # Version
            MOSHI_CHANNELS,  # Channel count
            3840,  # Pre-skip (80ms at 48kHz)
            MOSHI_SAMPLE_RATE,  # Input sample rate
            0,  # Output gain
            0,  # Channel mapping family
        )

        return self._create_ogg_page(opus_head, 0, 0x02)  # BOS flag

    def create_opus_tags(self):
        """Create OpusTags header page"""
        vendor = b"Python-opuslib"
        opus_tags = struct.pack("<8sI", b"OpusTags", len(vendor))
        opus_tags += vendor
        opus_tags += struct.pack("<I", 0)  # No user comments

        return self._create_ogg_page(opus_tags, 0, 0x00)

    def create_audio_page(self, opus_packet, samples_in_packet):
        """Create audio page containing Opus packet"""
        self.granule_position += samples_in_packet
        page = self._create_ogg_page(opus_packet, self.granule_position, 0x00)
        return page

    def _create_ogg_page(self, packet_data, granule_pos, page_type):
        """Create an Ogg page"""
        # Ogg page header
        header = struct.pack(
            "<4sBBQIIIB",
            b"OggS",  # Magic signature
            0,  # Version
            page_type,  # Page type flags
            granule_pos,  # Granule position
            self.serial_number,  # Bitstream serial number
            self.page_sequence,  # Page sequence number
            0,  # CRC (will be calculated)
            1,  # Number of segments
        )

        # Segment table
        segment_table = bytes([min(len(packet_data), 255)])

        # Complete page without CRC
        page_without_crc = header + segment_table + packet_data

        # Calculate CRC
        crc = self._calculate_crc(page_without_crc)

        # Insert CRC into header
        page = page_without_crc[:22] + struct.pack("<I", crc) + page_without_crc[26:]

        self.page_sequence += 1
        return page

    def _calculate_crc(self, data):
        """Calculate Ogg CRC-32"""
        # Ogg CRC polynomial: 0x04c11db7
        crc_table = []
        for i in range(256):
            crc = i << 24
            for _ in range(8):
                if crc & 0x80000000:
                    crc = (crc << 1) ^ 0x04C11DB7
                else:
                    crc <<= 1
                crc &= 0xFFFFFFFF
            crc_table.append(crc)

        crc = 0
        for byte in data:
            crc = (crc_table[((crc >> 24) ^ byte) & 0xFF] ^ (crc << 8)) & 0xFFFFFFFF

        return crc


class OpusEncoder:
    """Opus encoder using opuslib"""

    def __init__(self, sample_rate=MOSHI_SAMPLE_RATE, channels=MOSHI_CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_size = MOSHI_OPUS_FRAME_SIZE  # 20ms at 24kHz = 480 samples

        # Create Opus encoder
        try:
            self.encoder = opuslib.Encoder(
                fs=sample_rate, channels=channels, application=opuslib.APPLICATION_VOIP
            )
        except Exception as e:
            raise Exception(f"Could not create Opus encoder: {e}") from e

        # Create Ogg container
        self.ogg_container = OggContainer()

        # Initialize with headers
        self.headers_sent = False
        self.audio_buffer = np.array([], dtype=np.float32)

        logger.info(f"Opus encoder initialized: {sample_rate}Hz, {channels} channel(s)")

    def get_headers(self):
        """Get Opus headers as Ogg pages"""
        if not self.headers_sent:
            opus_head = self.ogg_container.create_opus_header()
            opus_tags = self.ogg_container.create_opus_tags()
            self.headers_sent = True
            return [opus_head, opus_tags]
        return []

    def encode(self, audio_data: np.ndarray) -> List[bytes]:
        """Encode audio data and return Ogg pages"""
        if audio_data is None or len(audio_data) == 0:
            return []

        # Add to buffer
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_data])

        pages = []

        # Process complete frames
        while len(self.audio_buffer) >= self.frame_size:
            # Extract one frame
            frame = self.audio_buffer[: self.frame_size]
            self.audio_buffer = self.audio_buffer[self.frame_size :]

            # Convert to 16-bit PCM for Opus
            pcm_data = (frame * 32767).astype(np.int16)

            try:
                # Encode with Opus
                opus_packet = self.encoder.encode(pcm_data.tobytes(), self.frame_size)

                # Create Ogg page
                ogg_page = self.ogg_container.create_audio_page(
                    opus_packet, self.frame_size
                )
                pages.append(ogg_page)

            except Exception as e:
                logger.error(f"Opus encoding error: {e}")

        return pages

    def close(self):
        """Close encoder"""
        if hasattr(self, "encoder"):
            del self.encoder


class OggPageParser:
    """Simple Ogg page parser for extracting Opus packets"""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list:
        """Feed data and return completed Ogg pages"""
        if not data:
            return []

        self.buffer.extend(data)
        pages = []

        while True:
            # Find Ogg page start
            magic_pos = self.buffer.find(b"OggS")
            if magic_pos == -1:
                # Keep only last 3 bytes in case OggS is split
                if len(self.buffer) > 3:
                    self.buffer = self.buffer[-3:]
                break

            # Remove data before magic
            if magic_pos > 0:
                del self.buffer[:magic_pos]

            # Check if we have enough data for header
            if len(self.buffer) < 27:
                break

            # Get page segments count
            page_segments = self.buffer[26]
            header_len = 27 + page_segments

            if len(self.buffer) < header_len:
                break

            # Calculate total page size
            segment_table = self.buffer[27:header_len]
            body_len = sum(segment_table)
            total_len = header_len + body_len

            if len(self.buffer) < total_len:
                break

            # Extract complete page
            page = bytes(self.buffer[:total_len])
            pages.append(page)

            # Remove processed page
            del self.buffer[:total_len]

        return pages


class OpusDecoder:
    """Opus decoder for Ogg-wrapped Opus packets"""

    def __init__(self, sample_rate=MOSHI_SAMPLE_RATE, channels=MOSHI_CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels

        # Create Opus decoder
        try:
            self.decoder = opuslib.Decoder(fs=sample_rate, channels=channels)
        except Exception as e:
            raise Exception(f"Could not create Opus decoder: {e}") from e

        # Initialize state
        self.headers_received = 0
        self.ogg_parser = OggPageParser()

        logger.info(f"Opus decoder initialized: {sample_rate}Hz, {channels} channel(s)")

    def decode(self, ogg_data: bytes) -> Optional[np.ndarray]:
        """Decode Ogg/Opus data"""
        if not ogg_data:
            return None

        try:
            # Check if this looks like an Ogg page
            if not ogg_data.startswith(b"OggS"):
                logger.debug(
                    f"Not an Ogg page, trying direct packet decode: {len(ogg_data)} bytes"
                )
                # Try direct Opus packet decode for raw data
                try:
                    pcm_data = self.decoder.decode(ogg_data, MOSHI_OPUS_FRAME_SIZE)
                    audio_samples = (
                        np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
                        / 32767.0
                    )
                    if len(audio_samples) > 0:
                        logger.info(
                            f"Successfully decoded direct packet: {len(audio_samples)} samples"
                        )
                        return audio_samples
                except Exception as e:
                    logger.debug(f"Direct decode failed: {e}")
                return None

            # Parse Ogg pages
            pages = self.ogg_parser.feed(ogg_data)

            audio_chunks = []

            for page in pages:
                # Extract packet from Ogg page
                packet = self._extract_packet_from_page(page)
                if not packet:
                    logger.debug("No packet extracted from Ogg page")
                    continue

                # Check if this is a header packet
                if packet.startswith(b"OpusHead") or packet.startswith(b"OpusTags"):
                    self.headers_received += 1
                    logger.info(
                        f"Received header packet {self.headers_received}: {len(packet)} bytes"
                    )
                    continue

                logger.debug(f"Trying to decode Opus packet: {len(packet)} bytes")

                # Decode Opus packet
                try:
                    # Try decoding with different frame sizes for flexibility
                    frame_sizes = [
                        MOSHI_OPUS_FRAME_SIZE,
                        240,
                        480,
                        960,
                        1920,
                    ]  # 10ms, 20ms, 40ms, 80ms

                    for frame_size in frame_sizes:
                        try:
                            pcm_data = self.decoder.decode(packet, frame_size)

                            # Convert from 16-bit PCM to float32
                            audio_samples = (
                                np.frombuffer(pcm_data, dtype=np.int16).astype(
                                    np.float32
                                )
                                / 32767.0
                            )

                            if len(audio_samples) > 0:
                                audio_chunks.append(audio_samples)
                                logger.debug(
                                    f"Successfully decoded with frame size {frame_size}: {len(audio_samples)} samples"
                                )
                                break  # Success, don't try other frame sizes

                        except Exception as frame_e:
                            logger.debug(f"Frame size {frame_size} failed: {frame_e}")
                            continue

                except Exception as e:
                    logger.debug(f"All Opus decode attempts failed: {e}")

            # Combine all audio chunks
            if audio_chunks:
                combined_audio = np.concatenate(audio_chunks)
                logger.info(
                    f"Successfully decoded audio: {len(combined_audio)} samples, max={np.max(np.abs(combined_audio)):.4f}"
                )
                return combined_audio

        except Exception as e:
            logger.error(f"Decoding error: {e}")

        return None

    def _extract_packet_from_page(self, page: bytes) -> Optional[bytes]:
        """Extract packet data from Ogg page"""
        if len(page) < 27:
            logger.debug(f"Page too short: {len(page)} bytes")
            return None

        try:
            # Parse Ogg header
            if not page.startswith(b"OggS"):
                logger.debug("Invalid Ogg page magic")
                return None

            page_segments = page[26]
            header_len = 27 + page_segments

            if len(page) < header_len:
                logger.debug(
                    f"Page header incomplete: need {header_len}, have {len(page)}"
                )
                return None

            # Get segment table
            segment_table = page[27:header_len]

            # Calculate expected packet length from segment table
            expected_packet_len = sum(segment_table)

            # Extract packet data
            packet_data = page[header_len : header_len + expected_packet_len]

            if len(packet_data) != expected_packet_len:
                logger.debug(
                    f"Packet length mismatch: expected {expected_packet_len}, got {len(packet_data)}"
                )
                return None

            logger.debug(
                f"Extracted packet: {len(packet_data)} bytes from {page_segments} segments"
            )
            return packet_data

        except Exception as e:
            logger.debug(f"Error extracting packet: {e}")
            return None

    def close(self):
        """Close decoder"""
        if hasattr(self, "decoder"):
            del self.decoder


class MoshiClient:
    """
    Moshi Client Library (Thread-based)

    A reusable client for Moshi voice assistant that handles WebSocket communication
    in a separate thread, providing simple synchronous methods for audio I/O.

    Example usage:
        client = MoshiClient()
        client.connect("ws://localhost:8998/api/chat")

        # Send audio data (thread-safe)
        audio_input = np.array([...], dtype=np.float32)  # PCM data
        client.add_audio_input(audio_input)

        # Get responses (thread-safe)
        audio_output = client.get_audio_output()  # Returns np.ndarray or None
        text_response = client.get_text_output()  # Returns str or None

        client.disconnect()
    """

    def __init__(
        self,
        text_temperature=MOSHI_DEFAULT_TEXT_TEMPERATURE,
        text_topk=MOSHI_DEFAULT_TEXT_TOPK,
        audio_temperature=MOSHI_DEFAULT_AUDIO_TEMPERATURE,
        audio_topk=MOSHI_DEFAULT_AUDIO_TOPK,
        pad_mult=MOSHI_DEFAULT_PAD_MULT,
        repetition_penalty=MOSHI_DEFAULT_REPETITION_PENALTY,
        repetition_penalty_context=MOSHI_DEFAULT_REPETITION_PENALTY_CONTEXT,
        output_buffer_size=MOSHI_CHUNK_SIZE,
    ):
        """
        Initialize MoshiClient with generation parameters.

        Args:
            text_temperature: Text generation temperature (0.2-1.2, default: 0.7)
            text_topk: Text generation top-k (10-500, default: 25)
            audio_temperature: Audio generation temperature (0.2-1.2, default: 0.8)
            audio_topk: Audio generation top-k (10-500, default: 250)
            pad_mult: Padding multiplier (-4 to 4, default: 0.0)
            repetition_penalty: Repetition penalty (1.0-2.0, default: 1.0)
            repetition_penalty_context: Repetition penalty context (0-200, default: 64)
            output_buffer_size: Size of audio chunks returned by get_audio_output (default: 1920)
        """
        # Generation parameters
        self.text_temperature = text_temperature
        self.text_topk = text_topk
        self.audio_temperature = audio_temperature
        self.audio_topk = audio_topk
        self.pad_mult = pad_mult
        self.repetition_penalty = repetition_penalty
        self.repetition_penalty_context = repetition_penalty_context
        self.output_buffer_size = output_buffer_size

        # Thread-safe queues for communication
        self.audio_input_queue = queue.Queue()  # Input: PCM data to send
        self.text_output_queue = queue.Queue()  # Output: Text responses
        self._raw_audio_queue = queue.Queue(
            maxsize=150
        )  # Raw audio payloads for background decoding (increased for better buffering)

        # Audio buffering for arbitrary-length input/output
        self._input_audio_buffer = np.array(
            [], dtype=np.float32
        )  # Buffer for input audio
        self._output_audio_buffer = np.array(
            [], dtype=np.float32
        )  # Buffer for output audio
        self._buffer_lock = threading.Lock()  # Lock for thread-safe buffer access

        # Thread management
        self._communication_thread = None
        self._running = threading.Event()
        self._connected = threading.Event()

        # Internal components (used by communication thread)
        self._websocket = None
        self._encoder = None
        self._decoder = None
        self._loop = None

        logger.info("MoshiClient initialized")

    def _build_websocket_url(self, base_url: str) -> str:
        """Build WebSocket URL with generation parameters"""
        from urllib.parse import urlparse, urlunparse, urlencode

        # Parse the base URL
        parsed = urlparse(base_url)

        # Build query parameters
        params = {
            "text_temperature": str(self.text_temperature),
            "text_topk": str(self.text_topk),
            "audio_temperature": str(self.audio_temperature),
            "audio_topk": str(self.audio_topk),
            "pad_mult": str(self.pad_mult),
            "repetition_penalty": str(self.repetition_penalty),
            "repetition_penalty_context": str(self.repetition_penalty_context),
            "text_seed": str(42),  # Fixed seed for reproducibility
            "audio_seed": str(42),  # Fixed seed for reproducibility
        }

        # Build the final URL
        query_string = urlencode(params)
        final_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                query_string,
                parsed.fragment,
            )
        )

        logger.debug(f"WebSocket URL with parameters: {final_url}")
        return final_url

    def connect(self, uri: str):
        """
        Connect to Moshi server (synchronous, thread-based).

        Args:
            uri: WebSocket URI (e.g., "ws://localhost:8998/api/chat")
        """
        if self._running.is_set():
            raise RuntimeError("Client is already connected")

        logger.info("Starting MoshiClient connection...")

        # Start communication thread
        self._communication_thread = threading.Thread(
            target=self._communication_thread_main, args=(uri,), daemon=True
        )
        self._communication_thread.start()

        # Wait for connection to be established
        if not self._connected.wait(timeout=30.0):  # Increased timeout
            self._running.clear()
            raise RuntimeError("Connection timeout")

        logger.info("MoshiClient connected successfully")

    def disconnect(self):
        """Disconnect from Moshi server (synchronous)"""
        if not self._running.is_set():
            return

        logger.info("Disconnecting MoshiClient...")

        # Signal shutdown
        self._running.clear()

        # Wait for thread to finish
        if self._communication_thread and self._communication_thread.is_alive():
            self._communication_thread.join(timeout=5.0)

        # Clear connection flag
        self._connected.clear()

        logger.info("MoshiClient disconnected")

    def add_audio_input(self, audio_data: np.ndarray):
        """
        Add PCM audio data to input queue (thread-safe, arbitrary length).

        The audio data will be buffered internally and sent to the server in
        CHUNK_SIZE (1920 sample) chunks as required by Moshi.

        Args:
            audio_data: PCM audio data as numpy array (float32, mono, 24kHz)
        """
        if not self.is_connected():
            logger.warning("Client is not connected, ignoring audio input")
            return

        if audio_data is None or len(audio_data) == 0:
            return

        # Ensure correct format
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        with self._buffer_lock:
            # Add new audio data to input buffer
            self._input_audio_buffer = np.concatenate(
                [self._input_audio_buffer, audio_data]
            )

            # Send complete chunks to the server
            while len(self._input_audio_buffer) >= MOSHI_CHUNK_SIZE:
                # Extract one chunk
                chunk = self._input_audio_buffer[:MOSHI_CHUNK_SIZE].copy()
                self._input_audio_buffer = self._input_audio_buffer[MOSHI_CHUNK_SIZE:]

                # Send chunk to encoder queue
                try:
                    self.audio_input_queue.put_nowait(chunk)
                except queue.Full:
                    logger.warning("Audio input queue full, dropping frame")
                    break

    def get_audio_output(self, timeout: Optional[float] = None) -> Optional[np.ndarray]:
        """
        Get received audio data (thread-safe, configurable size and timeout).

        Waits until the configured output_buffer_size amount of audio data is available,
        or until timeout expires.

        Args:
            timeout: Maximum time to wait for data in seconds. If None, waits indefinitely.
                    If 0, returns immediately (non-blocking).

        Returns:
            PCM audio data as numpy array (float32, mono, 24kHz) with length=output_buffer_size,
            or None if timeout expires before enough data is available
        """
        start_time = time.time()
        logger.debug(f"get_audio_output called with timeout={timeout}")

        while True:
            with self._buffer_lock:
                # Check if we have enough data in the output buffer
                if len(self._output_audio_buffer) >= self.output_buffer_size:
                    # Extract the requested amount
                    result = self._output_audio_buffer[: self.output_buffer_size].copy()
                    old_buffer_size = len(self._output_audio_buffer)
                    self._output_audio_buffer = self._output_audio_buffer[
                        self.output_buffer_size :
                    ]
                    new_buffer_size = len(self._output_audio_buffer)
                    logger.info(
                        f"📤 get_audio_output: extracted {len(result)} samples, buffer: {old_buffer_size} → {new_buffer_size}"
                    )
                    return result

            # Check timeout
            if timeout is not None:
                if timeout == 0:
                    return None  # Non-blocking mode, no data available
                elif time.time() - start_time >= timeout:
                    return None  # Timeout expired

            # # Small sleep to prevent busy waiting and allow decoder to process more data
            # time.sleep(0.001)

    def get_text_output(self) -> Optional[str]:
        """
        Get received text response (thread-safe, non-blocking).

        Returns:
            Text response as string or None if no text available
        """
        try:
            return self.text_output_queue.get_nowait()
        except queue.Empty:
            return None

    def is_connected(self) -> bool:
        """Check if client is connected (thread-safe)"""
        return self._running.is_set() and self._connected.is_set()

    def _communication_thread_main(self, uri: str):
        """Main function for communication thread"""
        try:
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # Run async main
            self._loop.run_until_complete(self._async_communication_main(uri))

        except Exception as e:
            logger.error(f"Communication thread error: {e}")
            self._connected.clear()
        finally:
            if self._loop:
                self._loop.close()

    async def _async_communication_main(self, uri: str):
        """Async main function for communication"""
        try:
            # Build URL with generation parameters
            final_uri = self._build_websocket_url(uri)
            logger.debug(f"Connecting to: {final_uri}")

            # Initialize audio components
            try:
                logger.info("Initializing Opus encoder...")
                self._encoder = OpusEncoder()
                logger.info("Opus encoder initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Opus encoder: {e}")
                raise

            try:
                logger.info("Initializing Opus decoder...")
                self._decoder = OpusDecoder()
                logger.info("Opus decoder initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Opus decoder: {e}")
                raise

            # Connect to WebSocket with optimized settings for high-throughput
            self._websocket = await websockets.connect(
                final_uri,
                max_size=2**23,  # 8MB buffer (default is 1MB) for high-throughput
            )
            self._running.set()

            # Wait for handshake
            await self._wait_for_handshake()

            # Signal connection established
            self._connected.set()

            # Start background audio decoder worker
            logger.info("Starting audio decoder worker...")
            decoder_task = asyncio.create_task(self._audio_decoder_worker())

            # Start receiver loop FIRST to capture all server responses
            logger.info("Starting receiver loop...")
            receiver_task = asyncio.create_task(self._receiver_loop())
            await asyncio.sleep(0.01)  # Give receiver a chance to start

            # Start sender loop for audio data
            logger.info("Starting sender loop...")
            sender_task = asyncio.create_task(self._sender_loop())
            await asyncio.sleep(0.01)  # Give sender a chance to start

            logger.info("Both tasks started, entering main loop...")

            # Wait for shutdown signal while both tasks run
            try:
                while self._running.is_set():
                    # Check if either task is done (error condition)
                    if sender_task.done():
                        try:
                            await sender_task  # Re-raise any exception
                        except Exception as e:
                            logger.error(f"Sender task failed: {e}")
                            break

                    if receiver_task.done():
                        try:
                            await receiver_task  # Re-raise any exception
                        except Exception as e:
                            logger.error(f"Receiver task failed: {e}")
                            break

                    if decoder_task.done():
                        try:
                            await decoder_task  # Re-raise any exception
                        except Exception as e:
                            logger.error(f"Decoder task failed: {e}")
                            break

                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Main loop error: {e}")

            logger.info("Shutting down, cancelling tasks...")
            # Cancel tasks
            sender_task.cancel()
            receiver_task.cancel()
            decoder_task.cancel()

            try:
                await sender_task
            except asyncio.CancelledError:
                logger.debug("Sender task cancelled")
                pass

            try:
                await receiver_task
            except asyncio.CancelledError:
                logger.debug("Receiver task cancelled")
                pass

            try:
                await decoder_task
            except asyncio.CancelledError:
                logger.debug("Decoder task cancelled")
                pass

        except Exception as e:
            logger.error(f"Async communication error: {e}")
            raise
        finally:
            # Cleanup
            if self._websocket:
                await self._websocket.close()
                self._websocket = None

            if self._encoder:
                self._encoder.close()
                self._encoder = None

            if self._decoder:
                self._decoder.close()
                self._decoder = None

            self._connected.clear()

    async def _wait_for_handshake(self):
        """Wait for server handshake - matches working implementation"""
        logger.info("Waiting for server handshake...")

        # Check if websocket is available
        if not self._websocket:
            raise RuntimeError("WebSocket is not connected")

        # Wait for handshake message
        message = await self._websocket.recv()
        logger.info(
            f"Received handshake message: type={type(message)}, len={len(message) if hasattr(message, '__len__') else 'N/A'}"
        )

        if isinstance(message, bytes) and len(message) > 0 and message[0] == 0:
            logger.info("Server handshake successful - completing handshake")
            # Send Opus headers after handshake (matching working implementation)
            await self._send_opus_headers()
        else:
            logger.error(f"Invalid handshake from server: {message}")
            raise RuntimeError("Invalid handshake from server")

    async def _send_opus_headers(self):
        """Send Opus headers to server"""
        if not self._websocket:
            raise RuntimeError("WebSocket is not connected")
        if not self._encoder:
            raise RuntimeError("Opus encoder is not initialized")

        headers = self._encoder.get_headers()
        for header in headers:
            if not self._running.is_set():
                break
            await self._websocket.send(b"\x01" + header)
            logger.info(f"Sent Opus header: {len(header)} bytes")
            await asyncio.sleep(0.01)  # Small delay between headers

    async def _sender_loop(self):
        """Background task for sending audio data"""
        logger.info("Sender loop started - FRAME-ALIGNED MODE")

        if not self._websocket:
            logger.error("WebSocket is None in sender loop")
            return

        if not self._encoder:
            logger.error("Opus encoder is None in sender loop")
            return

        sent_chunks = 0
        try:
            while self._running.is_set():
                try:
                    # Get audio data from thread-safe queue
                    try:
                        audio_data = self.audio_input_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # Encode to Opus using PurePythonOpusEncoder
                    ogg_pages = self._encoder.encode(audio_data)

                    # Send each Ogg page
                    for ogg_page in ogg_pages:
                        if not self._running.is_set():
                            break
                        sent_chunks += 1
                        send_time = time.time()
                        await self._websocket.send(b"\x01" + ogg_page)
                        # logger.info(f"→ Sent audio chunk #{sent_chunks}: {len(ogg_page)} bytes at {send_time:.3f}")

                        # Small delay to prevent overwhelming server
                        await asyncio.sleep(0.001)

                except Exception as e:
                    if self._running.is_set():
                        logger.error(f"Sender error: {e}")
                    break
        except Exception as e:
            logger.error(f"Sender loop error: {e}")
        finally:
            logger.info(f"→ Sender loop ended, total chunks sent: {sent_chunks}")

    async def _receiver_loop(self):
        """ULTRA-FAST receiver loop - optimized for maximum throughput"""
        logger.info("ULTRA-FAST receiver loop started")
        message_count = 0
        consecutive_timeouts = 0
        last_message_time = time.time()

        # Check WebSocket state immediately
        if not self._websocket:
            logger.error("WebSocket is None in receiver loop")
            return

        while self._running.is_set():
            try:
                # ULTRA-SHORT timeout for maximum responsiveness
                message = await asyncio.wait_for(self._websocket.recv(), timeout=0.0001)
                message_count += 1
                consecutive_timeouts = 0
                current_time = time.time()

                # ULTRA-MINIMAL logging - only every 100th message
                if message_count % 100 == 1:
                    time_since_last = current_time - last_message_time
                    logger.info(
                        f"★ MSG #{message_count}: len={len(message) if hasattr(message, '__len__') else 'N/A'}, gap={time_since_last:.3f}s"
                    )
                    last_message_time = current_time

                if isinstance(message, bytes) and len(message) > 0:
                    # IMMEDIATE non-blocking processing
                    self._handle_message_sync(message)

            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                # Don't sleep on timeout - keep polling aggressive
                continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"WebSocket connection closed in receiver: {e}")
                break
            except Exception as e:
                logger.error(f"Receiver error: {type(e).__name__}: {e}")
                # Don't break on individual message errors
                continue

        logger.info(
            f"★ ULTRA-FAST receiver ended, total messages: {message_count}, timeouts: {consecutive_timeouts}"
        )

    async def _audio_decoder_worker(self):
        """Background worker to decode audio without blocking receiver"""
        logger.info("Audio decoder worker started")
        decoded_count = 0

        if not self._decoder:
            logger.error("Opus decoder is None in audio decoder worker")
            return

        while self._running.is_set():
            try:
                # Get raw audio payload from queue - completely non-blocking
                try:
                    payload, timestamp = self._raw_audio_queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)  # Small sleep to prevent busy waiting
                    continue

                # Decode in background
                try:
                    # Log raw payload details for debugging
                    if decoded_count < 10 or decoded_count % 100 == 1:
                        logger.info(
                            f"🔍 Payload #{decoded_count}: {len(payload)} bytes, type={type(payload)}, starts with: {payload[:20].hex() if len(payload) >= 20 else payload.hex()}"
                        )

                    audio_data = self._decoder.decode(payload)
                    if audio_data is not None and len(audio_data) > 0:
                        decoded_count += 1

                        # Add to the buffering system
                        with self._buffer_lock:
                            old_size = len(self._output_audio_buffer)
                            self._output_audio_buffer = np.concatenate(
                                [self._output_audio_buffer, audio_data]
                            )
                            new_size = len(self._output_audio_buffer)

                        # Enhanced logging after buffer update
                        if decoded_count <= 50 or decoded_count % 100 == 1:
                            rms = np.sqrt(np.mean(audio_data**2))
                            max_amp = np.max(np.abs(audio_data))
                            logger.info(
                                f"🔊 Buffer updated #{decoded_count}: {old_size} → {new_size} samples (+{len(audio_data)})"
                            )
                            logger.info(
                                f"✅ Decoded #{decoded_count}: {len(audio_data)} samples, RMS={rms:.4f}, Max={max_amp:.4f}, buffer={new_size}"
                            )
                    else:
                        logger.warning(
                            f"❌ Decode failed or empty result for payload #{decoded_count}: {len(payload)} bytes"
                        )

                except Exception as decode_error:
                    logger.warning(
                        f"❌ Decode exception for payload #{decoded_count}: {decode_error}"
                    )

            except Exception as e:
                logger.error(f"Audio decoder worker error: {e}")
                break

        logger.info(f"Audio decoder worker ended, total decoded: {decoded_count}")

    def _handle_message_sync(self, message: bytes):
        """SYNCHRONOUS ULTRA-FAST message handling - zero async overhead"""
        if len(message) < 1:
            return

        msg_type = message[0]
        payload = message[1:] if len(message) > 1 else b""

        if msg_type == 0:  # Server handshake
            pass  # No processing needed

        elif msg_type == 1:  # Audio data
            if payload:
                # Enhanced logging for audio message analysis
                if not hasattr(self, "_audio_msg_count"):
                    self._audio_msg_count = 0
                self._audio_msg_count += 1

                if self._audio_msg_count <= 20 or self._audio_msg_count % 100 == 1:
                    logger.info(
                        f"🎵 Audio MSG #{self._audio_msg_count}: {len(payload)} bytes, starts: {payload[:16].hex() if len(payload) >= 16 else payload.hex()}"
                    )

                # Data format confirmed: Server sends Opus-encoded data, not pre-decoded PCM
                # Previous investigation showed PCM interpretation yields garbage values (RMS=inf, Max=2.69e36)
                # Current pipeline works correctly: WebSocket → Opus decode → 1920 samples @ 24kHz

                # Queue decoding in background thread to avoid blocking
                try:
                    self._raw_audio_queue.put_nowait((payload, time.time()))
                except queue.Full:
                    # Drop oldest frame if queue full
                    try:
                        dropped_payload, _ = self._raw_audio_queue.get_nowait()
                        self._raw_audio_queue.put_nowait((payload, time.time()))
                        logger.warning(
                            f"🗑️  Dropped audio payload: {len(dropped_payload)} bytes (queue full)"
                        )
                    except queue.Empty:
                        pass

        elif msg_type == 2:  # Text response
            if payload:
                try:
                    # Try JSON first
                    text_data = json.loads(payload.decode("utf-8"))
                    if isinstance(text_data, dict) and "text" in text_data:
                        text = text_data["text"]
                        # Minimal logging for text
                        if len(text.strip()) > 0:
                            logger.info(f"Moshi: {text}")
                            try:
                                self.text_output_queue.put_nowait(text)
                            except queue.Full:
                                logger.debug("Text queue full")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Try direct UTF-8 decode
                    try:
                        text = payload.decode("utf-8").strip()
                        if text:
                            logger.info(f"Moshi: {text}")
                            try:
                                self.text_output_queue.put_nowait(text)
                            except queue.Full:
                                logger.debug("Text queue full")
                    except UnicodeDecodeError:
                        logger.debug(
                            f"Failed to decode text payload: {len(payload)} bytes"
                        )
        else:
            logger.debug(f"Unknown message type: {msg_type}")

    async def _handle_message(self, message: bytes):
        """Handle incoming message (legacy method for compatibility)"""
        self._handle_message_sync(message)


# Export main class
__all__ = ["MoshiClient", "MOSHI_SAMPLE_RATE", "MOSHI_CHANNELS", "MOSHI_CHUNK_SIZE"]
