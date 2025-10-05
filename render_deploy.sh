#!/bin/bash
# Render deployment script

echo "Current directory: $(pwd)"
echo "Directory contents:"
ls -la

# Find the backend directory
if [ -d "backend" ]; then
    echo "Found backend directory at: $(pwd)/backend"
    BACKEND_DIR="backend"
elif [ -d "qna_backend" ]; then
    echo "Found backend directory at: $(pwd)/qna_backend"
    BACKEND_DIR="qna_backend"
else
    echo "Searching for backend directory..."
    find . -name "*backend*" -type d
    echo "Error: Cannot find backend directory"
    exit 1
fi

echo "Installing dependencies from $BACKEND_DIR/requirements.txt..."
pip install -r $BACKEND_DIR/requirements.txt

echo "Starting application from $BACKEND_DIR..."
cd $BACKEND_DIR
echo "Current directory after cd: $(pwd)"
echo "Contents of current directory:"
ls -la

# Start the Flask application
python web_api.py