# ARC-TPL-071 — Template is already split

'template split' moves the inline variables/formats/locales/preview_data sections of a one-file template into sidecar files. It refuses when a sidecar already exists, because the template is already in directory form and re-splitting would have nothing to move or could clobber a sidecar.

**Typical fix:** Edit the existing sidecar files directly — there is no reverse 'join' command. If you deliberately merged sections back inline and want to re-split, delete the leftover sidecar files first.
