import argparse
import asyncio
import json
import logging
import os
import shutil
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

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import TPE2, TIT2, TPE1
from mutagen.oggvorbis import OggVorbis


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

    return await shazam.recognize_song(input, proxy=args.proxy)  # type: ignore


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
    parser.add_argument("--albumcover", action="store_true", help="return url to HD album cover")

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
    advanced_group.add_argument(
        "--proxy",
        type=str,
        help="send the request to a proxy server",
    )
    advanced_group.add_argument(
        "--edit-metadata",
        action="store_true",
        help="Overwrite metadata of the song",
    )
    advanced_group.add_argument(
        "--edit-title",
        action="store_true",
        help="Overwrite title of the song",
    )
    return parser

def update_Metadata(console, title, artist, path):
    
    try:
        tag_map = {
            ".flac":  (FLAC, {"title": title, "artist": artist, "albumartist": artist}),
            ".ogg":   (OggVorbis, {"title": title, "artist": artist, "albumartist": artist}),
            ".mp3":   (MP3, {
                "TIT2": lambda audio: audio.__setitem__("TIT2", TIT2(encoding=3, text=title)),
                "TPE1": lambda audio: audio.__setitem__("TPE1", TPE1(encoding=3, text=artist)),
                "TPE2": lambda audio: audio.__setitem__("TPE2", TPE2(encoding=3, text=artist)),
            }),
        }

        ext = path.suffix.lower()

        if ext not in tag_map:
            console.print(f"[yellow]File type {ext} not supported for metadata writing.[/yellow]")
            return
        else:
            cls, tags = tag_map[ext]
            audio = cls(path)
            if ext == ".mp3":
                if audio.tags is None:
                    audio.add_tags()
                for key, func in tags.items():
                    func(audio)
            else:
                for key, value in tags.items():
                    audio[key] = value
            audio.save()

    except Exception as e:
        console.print(f"[red]Failed to update metadata for {path}: {e}[/red]")

def rename_File(console, title, artist, path):
    try:
        ext = path.suffix.lower()

        new_name = f"{title} - {artist}{ext}"
        new_path = path.with_name(new_name)

        path.rename(new_path)
    except Exception as e:
        console.print(f"[red]Failed to rename file: {e}[/red]")

def main() -> None:
    args = _parser().parse_args()
    raw = None
    track = None

    with _console() as console:
        logger.addHandler(RichHandler(console=console))
        logger.debug(f"parsed {args=}")

        if not shutil.which("ffmpeg"):
            console.print("[red]Fatal: ffmpeg not found on $PATH[/red]")
            sys.exit(1)

        try:
            raw = asyncio.run(_shaq(console, args))
            track = Serialize.full_track(raw)
        except KeyboardInterrupt:
            console.print("[red]Interrupted.[/red]")
            sys.exit(2)

        if (
            not args.json
            and track
            and track.matches
            and (args.edit_metadata or args.edit_title)
        ):
            if args.listen:
                console.print("[yellow]Metadata/Filename editing is not supported for live recordings.[/yellow]")
                return
            if args.edit_metadata:
                update_Metadata(console, track.track.title, track.track.subtitle, args.input)
            if args.edit_title:
                rename_File(console, track.track.title, track.track.subtitle, args.input)

    if args.json and raw is not None:
        json.dump(raw, sys.stdout, indent=2)

    elif track is not None:
        if not track.matches:
            print("No matches.")
            sys.exit(1)
        print(f"Track: {track.track.title}")
        print(f"Artist: {track.track.subtitle}")

        if args.albumcover and "images" in raw["track"]:
            album_cover = raw["track"]["images"]["coverart"]
            # Forces the shazam image server to fetch a
            # high-resolution album cover.
            album_cover_hq = album_cover.replace("/400x400cc.jpg", "/1000x1000cc.png")
            print(f"Album Cover: {album_cover_hq}")


