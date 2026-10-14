"""Generate original ambient music from oscillators, with no sampled recordings.

Run: python assets/bgm/generate_bgm.py
Produces three 45-second stereo MP3s at 128 kbps. Requires NumPy and ffmpeg.
"""
from pathlib import Path
import subprocess
import numpy as np

RATE = 44100
DURATION = 45


def synthesize(path: Path, roots, melody):
    frames = RATE * DURATION
    stereo = np.zeros((frames, 2), dtype=np.float64)
    chord_seconds = 5.625
    for bar in range(8):
        start = round(bar * chord_seconds * RATE)
        stop = min(frames, start + round((chord_seconds + 1.) * RATE))
        t = np.arange(stop - start) / RATE
        attack = np.minimum(1, t / .65)
        release = np.minimum(1, (len(t) / RATE - t) / 1.3)
        envelope = attack * release
        root = roots[bar % len(roots)]
        intervals = (0, 4, 7, 14) if bar % 4 != 1 else (0, 3, 7, 14)
        chord = np.zeros_like(t)
        for semitone in intervals:
            frequency = 440 * 2 ** ((root + semitone - 69) / 12)
            chord += (np.sin(2 * np.pi * frequency * t)
                      + .16 * np.sin(2 * np.pi * frequency * 2 * t)) / 4
        chord *= envelope * .16
        stereo[start:stop, 0] += chord
        stereo[start:stop, 1] += chord * .96
        # A sparse, gentle bell pattern over the held harmony.
        for beat, interval in enumerate(melody):
            note_start = start + round(beat * chord_seconds / len(melody) * RATE)
            note_stop = min(frames, note_start + RATE * 3)
            nt = np.arange(note_stop - note_start) / RATE
            frequency = 440 * 2 ** ((root + 12 + interval - 69) / 12)
            note = (np.sin(2 * np.pi * frequency * nt)
                    + .08 * np.sin(2 * np.pi * frequency * 3 * nt))
            note *= np.minimum(1, nt / .025) * np.exp(-nt * 1.7) * .06
            pan = .25 if beat % 2 else .75
            stereo[note_start:note_stop, 0] += note * pan
            stereo[note_start:note_stop, 1] += note * (1 - pan)
    # Both ends reach zero, making repeats free of discontinuity clicks.
    fade = np.minimum(1, np.arange(frames) / (RATE * 1.2))
    fade *= np.minimum(1, np.arange(frames)[::-1] / (RATE * 1.8))
    stereo *= fade[:, None]
    stereo *= .7 / max(.01, np.abs(stereo).max())
    pcm = (stereo * 32767).astype('<i2')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 's16le', '-ar', str(RATE),
                    '-ac', '2', '-i', 'pipe:0', '-c:a', 'libmp3lame', '-b:a', '128k',
                    str(path)], input=pcm.tobytes(), check=True)
    print(f'{path.name}: {DURATION}s stereo / 128kbps / original synthesized audio')


if __name__ == '__main__':
    directory = Path(__file__).resolve().parent
    for name, roots, melody in [
        ('bgm.mp3', [48, 45, 53, 55], [7, 14, 4, 7]),
        ('gentle_steps.mp3', [50, 47, 55, 57], [0, 7, 14, 7]),
        ('quiet_light.mp3', [53, 50, 58, 60], [4, 7, 14, 4]),
    ]:
        synthesize(directory / name, roots, melody)
