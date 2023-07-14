# shaq

A bare-bones CLI client for [Shazam](https://www.shazam.com/home).

![shaq in action](https://github.com/woodruffw/shaq/assets/3059210/9bf22a57-2c7b-48d8-9707-f3d7f9d9a2f4)

## Installation

`shaq` is available via `pip` or `pipx`:

```bash
pip install shaq
pipx install shaq
```

If you run into installation errors, make sure that you have PortAudio
installed. On Debian-based systems:

```bash
sudo apt install -y portaudio19-dev
```

## Usage

Detect by listening to the system microphone:

```bash
# shaq listens for 10 seconds by default
shaq --listen

# tell shaq to listen for 15 seconds instead
shaq --listen --duration 15
```

Detect from an audio file on disk:

```bash
# shaq truncates the input to 10 seconds
shaq --input obscure.mp3

# ...which can be overriden
shaq --input obscure.mp3 --duration 15
```

See `shaq --help` for more options.

## The name?

[Shazam](https://www.shazam.com/home),
[Shazaam](https://en.wikipedia.org/wiki/Kazaam#%22Shazaam%22),
[Kazaam](https://en.wikipedia.org/wiki/Kazaam),
[Shaquille O'Neal](https://en.wikipedia.org/wiki/Shaquille_O%27Neal).
