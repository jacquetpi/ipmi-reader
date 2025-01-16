import re

# Sample input as a multiline string (replace this with your actual command output)
ipmi_output = """
Temp             | 01h | ok  |  3.1 | 31 degrees C
Temp             | 02h | ok  |  3.2 | 28 degrees C
Inlet Temp       | 05h | ok  |  7.1 | 23 degrees C
GPU1 Temp        | 89h | ok  |  7.1 | 33 degrees C
GPU2 Temp        | 8Ah | ns  |  7.1 | Disabled
GPU3 Temp        | 62h | ns  |  7.1 | Disabled
GPU4 Temp        | 63h | ns  |  7.1 | Disabled
GPU5 Temp        | 64h | ns  |  7.1 | Disabled
GPU6 Temp        | 65h | ns  |  7.1 | Disabled
GPU7 Temp        | FCh | ns  |  7.1 | Disabled
GPU8 Temp        | FDh | ok  |  7.1 | 34 degrees C
Exhaust Temp     | 06h | ok  |  7.1 | 28 degrees C
"""

# Parse the output
result = {}
for line in ipmi_output.strip().split("\n"):
    match = re.match(r"(.+?)\s+\|\s+([0-9A-Fa-f]{2}h)\s+\|\s+\w+\s+\|\s+[\d.]+\s+\|\s+(.+)", line)
    if match:
        label = match.group(1).strip()
        address = match.group(2).strip()
        value = match.group(3).strip()
        result[label] = {"address": address, "value": value}

# Print the result
print(result)
