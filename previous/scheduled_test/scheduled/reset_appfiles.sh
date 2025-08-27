
FILE=$1
if [ -z "$FILE" ]; then
  echo "❌ Usage: ./reset_appfiles.sh filename.py"
  exit 1
fi

TIMESTAMP=$(date +%Y-%m-%d_%H-%M)
mkdir -p old_versions

# Move current file to archive
mv "$FILE" "old_versions/${FILE%.py}_$TIMESTAMP.py" 2>/dev/null

# Prompt to create new version
echo "📝 Paste new content for $FILE (Ctrl+D to save)"
cat > "$FILE"

echo "✅ $FILE replaced and archived as old_versions/${FILE%.py}_$TIMESTAMP.py"

