# default-audio

Audio that ships **with a release**. Every folder here mirrors one under `audio/`:

    default-audio/shorooq/athan.mp3   ->   audio/shorooq/athan.mp3

`apply_settings.sh` copies each file into place after every update, creating the folder if
it is not there. A file is copied **once per device**: the path is recorded in
`var/seeded-audio`, so a recitation the owner deletes does not come back on the next
nightly update, and a file already in `audio/` under the same name is never overwritten.

`audio/` itself is never part of a release - it is the owner's own music and runs to
hundreds of megabytes. This folder is the way to put a starting recitation on a device
without asking someone to copy it there by hand.

Folder names must match a real event, or nothing will ever play the file;
`tools/make_release.sh` checks them and asks before building a release with a name it does
not recognise. The events are the folders under `audio/`.

Keep it small. Every device downloads the whole payload on every update, so
`make_release.sh` refuses to build above `MAX_RELEASE_MB` (25 MB by default).
