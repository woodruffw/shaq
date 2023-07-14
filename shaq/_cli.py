import argparse
import asyncio
import json
import logging
import os
import sys
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import pyaudio
from pydub import AudioSegment
from rich import progress
from rich.console import Console
from rich.logging import RichHandler
from rich.status import Status
from shazamio import Serialize, Shazam

logging.basicConfig(
    level=os.environ.get("SHAQ_LOGLEVEL", "INFO").upper(),
    format="%(message)s",
    datefmt="[%X]",
)

_DEFAULT_CHUNK_SIZE = 1024
_FORMAT = pyaudio.paInt16
_DEFAULT_CHANNELS = 1
_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_DURATION = 10

logger = logging.getLogger(__name__)


@contextmanager
def _console() -> Iterator[Console]:
    """
    Temporarily dups and nulls the standard streams, while yielding a
    rich `Console` on the dup'd stderr.

    This is done because of PyAudio's misbehaving internals.
    See: https://stackoverflow.com/questions/67765911
    """
    try:
        # Save stdout and stderr, then clobber them.
        dup_fds = (os.dup(sys.stdout.fileno()), os.dup(sys.stderr.fileno()))
        null_fds = tuple(os.open(os.devnull, os.O_WRONLY) for _ in range(2))
        os.dup2(null_fds[0], sys.stdout.fileno())
        os.dup2(null_fds[1], sys.stderr.fileno())

        dup_stderr = os.fdopen(dup_fds[1], mode="w")
        yield Console(file=dup_stderr)
    finally:
        # Restore the original stdout and stderr; close everything except
        # the original FDs.
        os.dup2(dup_fds[0], sys.stdout.fileno())
        os.dup2(dup_fds[1], sys.stderr.fileno())

        for fd in [*null_fds, *dup_fds]:
            os.close(fd)


@contextmanager
def _pyaudio() -> Iterator[pyaudio.PyAudio]:
    try:
        p = pyaudio.PyAudio()
        yield p
    finally:
        p.terminate()


def _listen(console: Console, args: argparse.Namespace) -> bytearray:
    with _pyaudio() as p, BytesIO() as io, wave.open(io, "wb") as wav:
        # Use the same parameters as shazamio uses internally for audio
        # normalization, to reduce unnecessary transcoding.
        wav.setnchannels(args.channels)
        wav.setsampwidth(p.get_sample_size(_FORMAT))
        wav.setframerate(args.sample_rate)

        stream = p.open(format=_FORMAT, channels=args.channels, rate=args.sample_rate, input=True)
        for _ in progress.track(
            range(0, args.sample_rate // args.chunk_size * args.duration),
            description="shaq is listening...",
            console=console,
        ):
            wav.writeframes(stream.read(args.chunk_size))

        stream.close()

        # TODO: Optimize if necessary; this makes at least one pointless copy.
        return bytearray(io.getvalue())


def _from_file(console: Console, args: argparse.Namespace) -> AudioSegment:
    with Status(f"Extracting from {args.input}", console=console):
        input = AudioSegment.from_file(args.input)

        # pydub measures things in milliseconds
        duration = args.duration * 1000
        return input[:duration]


async def _shaq(console: Console, args: argparse.Namespace) -> dict[str, Any]:
    input: bytearray | AudioSegment
    if args.listen:
        input = _listen(console, args)
    else:
        input = _from_file(console, args)

    shazam = Shazam(language="en-US", endpoint_country="US")
    return await shazam.recognize_song(input)  # type: ignore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--listen", action="store_true", help="detect from the system's microphone"
    )
    input_group.add_argument("--input", type=Path, help="detect from the given audio input file")

    parser.add_argument(
        "-d",
        "--duration",
        metavar="SECS",
        type=int,
        default=_DEFAULT_DURATION,
        help="only analyze the first SECS of the input (microphone or file)",
    )
    parser.add_argument(
        "-j", "--json", action="store_true", help="emit Shazam's response as JSON on stdout"
    )

    advanced_group = parser.add_argument_group(
        title="Advanced Options",
        description="Advanced users only: options to tweak recording, transcoding, etc. behavior.",
    )
    advanced_group.add_argument(
        "--chunk-size",
        type=int,
        default=_DEFAULT_CHUNK_SIZE,
        help="read from the microphone in chunks of this size; only affects --listen",
    )
    advanced_group.add_argument(
        "--channels",
        type=int,
        choices=(1, 2),
        default=_DEFAULT_CHANNELS,
        help="the number of channels to use; only affects --listen",
    )
    advanced_group.add_argument(
        "--sample-rate",
        type=int,
        default=_DEFAULT_SAMPLE_RATE,
        help="the sample rate to use; only affects --listen",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    with _console() as console:
        logger.addHandler(RichHandler(console=console))
        logger.debug(f"parsed {args=}")

        try:
            raw = asyncio.run(_shaq(console, args))
            track = Serialize.full_track(raw)
        except KeyboardInterrupt:
            console.print("[red]Interrupted.[/red]")
            sys.exit(2)

    if args.json:
        json.dump(raw, sys.stdout, indent=2)
    else:
        track = Serialize.full_track(raw)
        if not track.matches:
            print("No matches.")
        else:
            print(f"Track: {track.track.title}")
            print(f"Artist: {track.track.subtitle}")

    if not track.matches:
        sys.exit(1)
