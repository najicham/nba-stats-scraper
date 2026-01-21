#!/usr/bin/env python3
"""Generate SHA256 hashes for all model files."""

import hashlib
import glob
import os

def generate_hash(file_path: str) -> str:
    """Generate SHA256 hash of file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def main():
    # Find all model files
    patterns = [
        'ml/models/**/*.pkl',
        'ml/models/**/*.joblib',
        'models/**/*.pkl',
        'models/**/*.joblib',
    ]

    model_files = []
    for pattern in patterns:
        model_files.extend(glob.glob(pattern, recursive=True))

    if not model_files:
        print("❌ No model files found")
        return

    # Generate hashes
    for model_path in model_files:
        hash_value = generate_hash(model_path)
        hash_path = f"{model_path}.sha256"

        with open(hash_path, 'w') as f:
            f.write(hash_value)

        print(f"✅ {model_path}")
        print(f"   Hash: {hash_value[:16]}...")

    print(f"\n✅ Generated {len(model_files)} hash files")

if __name__ == '__main__':
    main()
