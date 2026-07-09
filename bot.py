import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from kevlarbot.handlers import main

if __name__ == "__main__":
    main()
