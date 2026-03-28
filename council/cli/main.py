#!/usr/bin/env python3
"""
TheCouncil CLI entry point.

This module serves as the command-line interface for running council debates.
It imports and delegates to the core council module's main() function.
"""

from council.core.council import main

if __name__ == "__main__":
    main()
