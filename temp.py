import base64
import urllib.parse

token = "aHR0cHM6Ly9jaGV0dXN0b3JlLmNoZXR1LmNvbS9nZWFyLmh0bWw%2C"

# Step 1: Decode URL-encoded characters (like %2C -> ',')
url_decoded = urllib.parse.unquote(token)

# Step 2: Strip any trailing characters that aren't valid base64
# (here, the trailing comma from %2C)
b64_str = url_decoded.rstrip(",")

# Step 3: Fix padding — base64 length must be a multiple of 4
missing_padding = len(b64_str) % 4
if missing_padding:
    b64_str += "=" * (4 - missing_padding)

# Step 4: Decode
original_id = base64.b64decode(b64_str).decode("utf-8")

print("Decoded ID:", original_id)