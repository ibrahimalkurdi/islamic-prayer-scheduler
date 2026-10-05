"""Adding a recitation to one of the audio/ folders, or deleting some, from the touch
screen or the website.

An added file lands in the folder unticked: it is played only once it is ticked in that
event's list and the settings are saved, the same as a file copied in by hand. A deleted
file is unticked at once, since the player reads the ticked list each time it plays.
Both screens offer the same folders and refuse the same files in the same words.
"""

import configparser
import os
import shutil
import tempfile

from shared import audio_lists

# The folder each event plays from, under the name the settings screens give the event.
FOLDER_LABELS = {
    "fajr": "أذان الفجر",
    "shorooq": "الشروق",
    "dhuhr": "أذان الظهر",
    "asr": "أذان العصر",
    "maghrib": "أذان المغرب",
    "isha": "أذان العشاء",
    "tahajjud": "صلاة التهجد",
    "duha": "صلاة الضحى",
    "athkar_elsabah": "أذكار الصباح",
    "athkar_elmasa": "أذكار المساء",
    "quran": "القرآن اليومي",
    "friday_quran": "سورة الكهف يوم الجمعة",
}

# Each folder's list of ticked files in config.ini; shorooq's is the sunrise event's.
CHECKED_KEYS = {folder: ("sunrise" if folder == "shorooq" else folder) + "_audio_checked"
                for folder in audio_lists.EVENT_DIRS}

MAX_BYTES = 1024 ** 3
# Room left on the card after the copy, so a large upload never fills it: the logs, the
# schedule and the next update all need space too.
FREE_MARGIN_BYTES = 200 * 1024 ** 2
MAX_NAME_BYTES = 200
CHUNK_BYTES = 1024 ** 2

EXISTS_QUESTION = "يوجد ملف بالاسم «{name}» في مجلد «{folder}».\nهل تريد استبداله بالملف الجديد؟"


class UploadError(Exception):
    """A refused upload, with the message the owner is shown."""


def folders(scheduler_dir):
    """(folder, label) for every event folder this device has, in the screens' order."""
    root = os.path.join(scheduler_dir, "audio")
    order = list(FOLDER_LABELS) + [n for n in audio_lists.EVENT_DIRS if n not in FOLDER_LABELS]
    return [(name, FOLDER_LABELS.get(name, name)) for name in order
            if os.path.isdir(os.path.join(root, name))]


def check_name(name):
    """The file name as it will be saved. config.ini keeps a list's ticked files as one
    comma-separated value, so a comma would split one file into two that do not exist."""
    name = (name or "").strip()
    if not name or name != os.path.basename(name) or name.startswith(".") or "\\" in name:
        raise UploadError("اسم الملف غير صالح")
    if not name.lower().endswith(".mp3"):
        raise UploadError("يُقبل ملف صوتي بصيغة MP3 فقط")
    if "," in name:
        raise UploadError("اسم الملف يجب ألا يحتوي على فاصلة «,» — غيّر اسمه ثم أعد المحاولة")
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        raise UploadError("اسم الملف طويل جدًا")
    return name


def target(scheduler_dir, folder, name):
    """Where the file goes. Raises UploadError for a folder or name that is refused."""
    if folder not in dict(folders(scheduler_dir)):
        raise UploadError("المجلد المختار غير موجود")
    return os.path.join(audio_lists.audio_dir(scheduler_dir, folder), check_name(name))


def exists_question(scheduler_dir, folder, name):
    """The question asked before replacing a file, or "" when there is none to replace."""
    path = target(scheduler_dir, folder, name)
    if not os.path.exists(path):
        return ""
    return EXISTS_QUESTION.format(name=f"⁨{os.path.basename(path)}⁩",
                                  folder=FOLDER_LABELS.get(folder, folder))


def looks_like_mp3(head):
    """An ID3 tag, or an MPEG audio frame's sync bits, at the start of the file."""
    return head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


def _check_size(directory, size):
    if size <= 0:
        raise UploadError("الملف فارغ")
    if size > MAX_BYTES:
        raise UploadError("حجم الملف أكبر من الحد المسموح (1 غيغابايت)")
    if shutil.disk_usage(directory).free < size + FREE_MARGIN_BYTES:
        raise UploadError("لا توجد مساحة كافية على بطاقة الذاكرة لهذا الملف")


def save(stream, size, path):
    """Write `size` bytes read from `stream` to `path`. The file appears whole or not at
    all: it is written beside its final name and renamed into place, so the player never
    picks up half a recitation. Raises UploadError."""
    directory = os.path.dirname(path)
    _check_size(directory, size)
    handle, partial = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=directory)
    try:
        with os.fdopen(handle, "wb") as out:
            remaining = size
            first = True
            while remaining:
                chunk = stream.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise UploadError("انقطع رفع الملف قبل اكتماله، أعد المحاولة")
                if first and not looks_like_mp3(chunk):
                    raise UploadError("الملف المختار ليس ملفًا صوتيًا بصيغة MP3")
                first = False
                out.write(chunk)
                remaining -= len(chunk)
        os.chmod(partial, 0o644)
        os.replace(partial, path)
    except OSError as error:
        raise UploadError(f"تعذّر حفظ الملف:\n{error}")
    finally:
        if os.path.exists(partial):
            os.unlink(partial)
    return os.path.basename(path)


def copy(source, path):
    """save() for a file on this device - the touch screen's picker."""
    try:
        size = os.path.getsize(source)
        with open(source, "rb") as stream:
            return save(stream, size, path)
    except OSError as error:
        raise UploadError(f"تعذّر قراءة الملف:\n{error}")


def _ticked(ini_path, folder):
    config = configparser.ConfigParser(interpolation=None)
    config.read(ini_path, encoding="utf-8")
    section = config["Settings"] if config.has_section("Settings") else {}
    key = CHECKED_KEYS.get(folder, "")
    enable = audio_lists.EVENT_ENABLE_KEYS.get(key, "")
    on = str(section.get(enable, "False")).strip().lower() == "true"
    return config, key, enable, on, audio_lists.checked_from_config(section.get(key, ""))


def _existing(scheduler_dir, folder, names):
    paths = [target(scheduler_dir, folder, name) for name in names]
    if not paths:
        raise UploadError("لم يتم تحديد أي ملف للحذف")
    gone = [os.path.basename(p) for p in paths if not os.path.isfile(p)]
    if gone:
        raise UploadError("الملف غير موجود: " + "، ".join(f"⁨{n}⁩" for n in gone))
    return paths


def delete_question(scheduler_dir, ini_path, folder, names):
    """The question asked before deleting: which files, and what it does to the event
    when some of them are ticked. Raises UploadError for a file that is not there."""
    paths = _existing(scheduler_dir, folder, names)
    _config, _key, _enable, on, ticked = _ticked(ini_path, folder)
    label = FOLDER_LABELS.get(folder, folder)
    names = [os.path.basename(p) for p in paths]
    text = (f"سيتم حذف {'الملف التالي' if len(names) == 1 else f'الملفات التالية ({len(names)})'} "
            f"نهائيًا من مجلد «{label}»:\n")
    text += "\n".join(f"• ⁨{n}⁩" for n in names) + "\n"
    if ticked & set(names):
        text += "\nمن بينها ملفات محددة للتشغيل، وستُزال من قائمة المجلد."
        if on and not ticked - set(names):
            text += f"\nولن يبقى ملف محدد لـ«{label}»، فسيتم إيقافه."
        text += "\n"
    return text + "\nلا يمكن التراجع عن الحذف. هل تريد المتابعة؟"


def delete(scheduler_dir, ini_path, folder, names):
    """Delete the files and untick them in config.ini - switching the event off when it
    is left with none ticked. Returns (deleted names, the files still ticked, whether the
    event was switched off). Raises UploadError, having deleted nothing, for a refused
    name."""
    paths = _existing(scheduler_dir, folder, names)
    deleted = []
    try:
        for path in paths:
            os.remove(path)
            deleted.append(os.path.basename(path))
    except OSError as error:
        raise UploadError(f"تعذّر حذف الملف:\n{error}")
    finally:
        config, key, enable, on, ticked = _ticked(ini_path, folder)
        left = ticked - set(deleted)
        switched_off = False
        if config.has_section("Settings") and key and left != ticked:
            config["Settings"][key] = audio_lists.checked_to_config(sorted(left))
            if on and not left:
                config["Settings"][enable] = "False"
                switched_off = True
            with open(ini_path, "w", encoding="utf-8") as handle:
                config.write(handle)
    return deleted, sorted(left), switched_off
