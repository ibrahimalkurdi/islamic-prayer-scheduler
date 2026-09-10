#!/bin/bash
# The Desktop shortcut's entry point, so setup can be re-run without a terminal.
#
# It exists rather than the shortcut calling init.sh directly for two reasons: init.sh
# asks for a sudo password and prints a long report, both of which need a terminal window
# that stays open; and a shortcut that vanishes the moment it finishes tells the person
# who clicked it nothing about whether it worked.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$HERE/init.sh"
status=$?

echo
if [[ $status -eq 0 ]]; then
    echo "تم تثبيت مكونات النظام بنجاح."
else
    echo "لم يكتمل التثبيت. رمز الخطأ: $status"
    echo "صوّر هذه النافذة وأرسلها للدعم الفني."
fi
echo
read -n 1 -r -p "اضغط أي مفتاح لإغلاق هذه النافذة..."
echo
