import os

with open("file_list.txt", "w") as out:
    for root, dirs, files in os.walk("."):
        for f in files:
            path = os.path.join(root, f)
            out.write(path + "\\n")

print("✅ File list saved to file_list.txt")
