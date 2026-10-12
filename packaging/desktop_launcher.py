"""PyInstaller Windows portable entry point — no side effects until main()."""
from athenz.desktop import main

if __name__ == '__main__':
    main()
