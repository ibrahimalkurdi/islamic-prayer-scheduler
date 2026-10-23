"""How long a recitation plays, read from the MP3's own headers: CBR by size over bitrate,
VBR by the frame count its Xing/Info or VBRI header names, tags skipped, and anything
that is not an MP3 reported as unreadable rather than as a length.

    python3 tools/tests/test_audio_duration.py
"""
import os, sys, struct, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..",
                                "scheduler-official-touch-screen-with-raspberry-pi-4", "applications"))
from shared import audio_duration  # noqa: E402

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)

def near(name, got, want, within=0.2):
    ok = got is not None and abs(got - want) <= within
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected ~{want!r}, got {got!r}"))
    if not ok: fails.append(name)

MPEG1_128K = b"\xff\xfb\x90\x00"
MPEG1_128K_LENGTH = 417
MPEG2_64K_22050 = b"\xff\xf3\x80\x00"
MPEG2_64K_LENGTH = 72 * 64000 // 22050

def frames(header, length, count, first=b""):
    body = header + first
    out = [body + bytes(length - len(body))]
    out += [header + bytes(length - 4)] * (count - 1)
    return b"".join(out)

def id3v2(payload=2000):
    size = payload
    syncsafe = bytes(((size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F))
    return b"ID3\x04\x00\x00" + syncsafe + bytes(payload)

work = tempfile.mkdtemp()
def write(name, data):
    path = os.path.join(work, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path

print("1. a constant-bitrate file is its size over its bitrate")
cbr = write("cbr.mp3", frames(MPEG1_128K, MPEG1_128K_LENGTH, 2297))
near("about a minute", audio_duration.mp3_seconds(cbr), 2297 * MPEG1_128K_LENGTH * 8 / 128000, 0.01)
tagged = write("tagged.mp3", id3v2() + frames(MPEG1_128K, MPEG1_128K_LENGTH, 2297)
               + b"TAG" + bytes(125))
near("its tags, at either end, are not counted as sound",
     audio_duration.mp3_seconds(tagged), audio_duration.mp3_seconds(cbr), 0.01)
mpeg2 = write("mpeg2.mp3", frames(MPEG2_64K_22050, MPEG2_64K_LENGTH, 1000))
near("an MPEG-2 file, at its own rate", audio_duration.mp3_seconds(mpeg2),
     1000 * MPEG2_64K_LENGTH * 8 / 64000, 0.01)

print("2. a variable-bitrate file is the frame count its header names")
xing = MPEG1_128K + bytes(32) + b"Xing" + struct.pack(">II", 1, 100000)
vbr = write("vbr.mp3", frames(MPEG1_128K, MPEG1_128K_LENGTH, 50, xing[4:]))
near("Xing: 100000 frames of 1152 samples at 44.1 kHz", audio_duration.mp3_seconds(vbr),
     100000 * 1152 / 44100, 0.001)
info = write("info.mp3", frames(MPEG1_128K, MPEG1_128K_LENGTH, 50,
                                bytes(32) + b"Info" + struct.pack(">II", 1, 4410)))
near("Info, the same header on a constant-rate file", audio_duration.mp3_seconds(info),
     4410 * 1152 / 44100, 0.001)
vbri = write("vbri.mp3", frames(MPEG1_128K, MPEG1_128K_LENGTH, 50,
                                bytes(32) + b"VBRI" + bytes(10) + struct.pack(">I", 2205)))
near("VBRI", audio_duration.mp3_seconds(vbri), 2205 * 1152 / 44100, 0.001)

print("3. what is not an MP3 has no length")
chk("an empty file", audio_duration.mp3_seconds(write("empty.mp3", b"")), None)
chk("text", audio_duration.mp3_seconds(write("text.mp3", b"not audio at all " * 100)), None)
chk("a file that is not there", audio_duration.mp3_seconds(os.path.join(work, "gone.mp3")), None)
chk("a stray sync byte pair that no frame follows",
    audio_duration.mp3_seconds(write("stray.mp3", b"\xff\xfb\x90\x00" + b"\x01" * 2000)), None)

print("4. a list adds up, and says which it could not read")
seconds, unread = audio_duration.total_seconds(work, ["cbr.mp3", "vbri.mp3", "empty.mp3"])
near("the readable ones together", seconds,
     audio_duration.mp3_seconds(cbr) + audio_duration.mp3_seconds(vbri), 0.001)
chk("and the one it could not", unread, ["empty.mp3"])

if shutil.which("ffprobe"):
    print("5. and agrees with ffprobe")
    for name in ("cbr.mp3", "tagged.mp3", "mpeg2.mp3"):
        path = os.path.join(work, name)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", path], capture_output=True, text=True)
        near(name, audio_duration.mp3_seconds(path), float(probe.stdout.strip()), 0.1)

shutil.rmtree(work)
print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
