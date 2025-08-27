import os
import shutil
import subprocess

DATA_DIR = "scheduled_data"

# Create data dir if missing
os.makedirs(DATA_DIR, exist_ok=True)

# Clear all user files (reset)
for filename in os.listdir(DATA_DIR):
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.isfile(file_path):
        open(file_path, "w").close()  # clear contents

print("✅ Reset complete. Launching Flask app...\n")

# Run the app
subprocess.run(["python", "app.py"])
EOF
