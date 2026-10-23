"""How long a recitation plays, read from the MP3 itself.

Settings show when the daily Quran ends: its start plus every ticked file, played one
after another. Read from the file's own headers, not by a tool: ffprobe is on some
devices only because something else pulled it in, and nothing installs it. A VBR file
names its frame count in a Xing/Info or VBRI header; a CBR file is its size over its
bitrate.
"""

import os
import struct

BITRATES_KBPS = {
    (1, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
# How far past the tag to look for the first frame: some encoders pad there.
SYNC_SEARCH_BYTES = 64 * 1024


def frame_header(data, at):
    """The frame header at `at` as (version, layer, bitrate bps, sample rate, samples per
    frame, frame length, mono), or None when these four bytes are not one."""
    if at + 4 > len(data) or data[at] != 0xFF or data[at + 1] & 0xE0 != 0xE0:
        return None
    b1, b2, b3 = data[at + 1], data[at + 2], data[at + 3]
    version_bits, layer_bits = (b1 >> 3) & 3, (b1 >> 1) & 3
    bitrate_index, rate_index = b2 >> 4, (b2 >> 2) & 3
    if version_bits == 1 or layer_bits == 0 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    version = 1 if version_bits == 3 else 2
    layer = 4 - layer_bits
    bitrate = BITRATES_KBPS[(version, layer)][bitrate_index] * 1000
    rate = SAMPLE_RATES[version_bits][rate_index]
    padding = (b2 >> 1) & 1
    if layer == 1:
        samples, length = 384, (12 * bitrate // rate + padding) * 4
    else:
        samples = 576 if layer == 3 and version == 2 else 1152
        length = samples // 8 * bitrate // rate + padding
    return version, layer, bitrate, rate, samples, length, (b3 >> 6) == 3


def tag_size(data):
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | (byte & 0x7F)
    return 10 + size + (10 if data[5] & 0x10 else 0)


def mp3_seconds(path):
    """The playing time of an MP3 in seconds, or None if it cannot be read as one."""
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as handle:
            head = handle.read(10)
            start = tag_size(head)
            handle.seek(start)
            data = handle.read(SYNC_SEARCH_BYTES)
            handle.seek(max(0, total - 128))
            has_v1_tag = handle.read(3) == b"TAG"
    except OSError:
        return None

    for at in range(len(data) - 4):
        frame = frame_header(data, at)
        if frame is None:
            continue
        version, layer, bitrate, rate, samples, length, mono = frame
        following = at + length
        if following + 4 <= len(data) and frame_header(data, following) is None:
            continue
        break
    else:
        return None

    side = (17 if mono else 32) if version == 1 else (9 if mono else 17)
    xing = at + 4 + side
    if data[xing:xing + 4] in (b"Xing", b"Info") and len(data) >= xing + 12:
        flags = struct.unpack(">I", data[xing + 4:xing + 8])[0]
        if flags & 1:
            frames = struct.unpack(">I", data[xing + 8:xing + 12])[0]
            return frames * samples / rate
    vbri = at + 4 + 32
    if data[vbri:vbri + 4] == b"VBRI" and len(data) >= vbri + 18:
        frames = struct.unpack(">I", data[vbri + 14:vbri + 18])[0]
        return frames * samples / rate

    audio_bytes = total - start - at - (128 if has_v1_tag else 0)
    return audio_bytes * 8 / bitrate if audio_bytes > 0 else None


def total_seconds(directory, names):
    """The ticked files' playing time together, and the names that could not be read."""
    seconds, unread = 0.0, []
    for name in names:
        length = mp3_seconds(os.path.join(directory, name))
        if length is None:
            unread.append(name)
        else:
            seconds += length
    return seconds, unread
