import os
import sys
import tempfile
from datetime import datetime, timedelta

def convert():
    if len(sys.argv) < 3:
        print("Usage: python3 00_al_awail_convert_csv.py <input_file> <output_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        sys.exit(1)

    with open(input_file, 'r', encoding='utf-8') as f_in:
        lines = f_in.readlines()

    # Find the line where the actual data starts by looking for the "Date" header
    data_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Date"):
            data_start = i + 1
            break

    def add_offset(time_str, mins):
        try:
            t = datetime.strptime(time_str, "%H:%M") + timedelta(minutes=mins)
            return t.strftime("%H:%M")
        except ValueError:
            return time_str

    out_lines = []
    for line in lines[data_start:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(';')
        if len(parts) >= 7:
            date_str = parts[0]

            # Parse the date components (assuming YYYY-MM-DD)
            try:
                year, month, day = date_str.split('-')
                # Remove leading zeros from month and day
                month = str(int(month))
                day = str(int(day))
            except ValueError:
                continue # Skip lines with malformed dates

            # Add 1 hour to all times to convert GMT+2 to GMT+3
            fajr = add_offset(parts[1], 60)
            sunrise = add_offset(parts[2], 60)  # Shuruq
            dhuhr = add_offset(parts[3], 60)
            asr = add_offset(parts[4], 60)
            # Maghrib gets 1 hour for GMT+3 plus 2 extra minutes offset
            maghrib = add_offset(parts[5], 62)
            isha = add_offset(parts[6], 60)

            out_lines.append(f"{month},{day},{fajr},{sunrise},{dhuhr},{asr},{maghrib},{isha}\n")

    if not out_lines:
        print(f"Error: no prayer time rows could be parsed from {input_file}.")
        sys.exit(1)

    # Write to a temp file first, then atomically replace the destination, so a failed
    # conversion can never destroy the user's existing prayer times file.
    out_dir = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f_out:
            f_out.write("Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha\n")
            f_out.writelines(out_lines)
        os.replace(tmp_path, output_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    print(f"Successfully converted {len(out_lines)} rows. Output saved to: \n{output_file}")

if __name__ == "__main__":
    convert()
