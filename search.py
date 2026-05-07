#!/usr/bin/env python3
"""
File search tool: git history + filesystem with pattern matching.
Searches for files matching patterns (e.g., *.env, secrets, apikey) in:
  1. Git commit history (to find accidentally committed files)
  2. Current filesystem
"""

import subprocess
import re
import sys
import os
from pathlib import Path
from typing import Set, List
import argparse


def search_git_history(pattern: str, repo_path: str = ".") -> List[str]:
    """Search for files in git history matching the pattern."""
    results = set()
    
    try:
        # Get all commits
        commits = subprocess.check_output(
            ["git", "rev-list", "--all"],
            cwd=repo_path,
            text=True,
            stderr=subprocess.DEVNULL
        ).strip().split("\n")
        
        if not commits or commits == [""]:
            return []
        
        for commit in commits:
            if not commit:
                continue
            try:
                # List all files in this commit
                files = subprocess.check_output(
                    ["git", "ls-tree", "-r", "--name-only", commit],
                    cwd=repo_path,
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip().split("\n")
                
                for file in files:
                    if file and _matches_pattern(file, pattern):
                        results.add(file)
            except subprocess.CalledProcessError:
                continue
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    
    return sorted(list(results))


def search_filesystem(pattern: str, root_path: str = ".") -> List[str]:
    """Search filesystem for files matching the pattern."""
    results = []
    
    try:
        root = Path(root_path).resolve()
        
        for item in root.rglob("*"):
            # Skip .git and hidden directories
            if ".git" in item.parts or any(p.startswith(".") for p in item.parts[len(root.parts):]):
                continue
            
            if _matches_pattern(item.name, pattern):
                results.append(str(item.relative_to(root)))
    except (OSError, PermissionError):
        pass
    
    return sorted(results)


def _matches_pattern(filename: str, pattern: str) -> bool:
    """
    Check if filename matches pattern.
    Supports:
      - Glob patterns: *.env, secrets*, *apikey*
      - Regex patterns: (wrapped in /pattern/)
      - Exact matches
    """
    # Regex pattern (e.g., /^\.env\..*$/)
    if pattern.startswith("/") and pattern.endswith("/"):
        try:
            return bool(re.search(pattern[1:-1], filename))
        except re.error:
            return False
    
    # Glob pattern
    if "*" in pattern or "?" in pattern:
        from fnmatch import fnmatch
        return fnmatch(filename, pattern)
    
    # Exact or substring match
    return pattern.lower() in filename.lower()


def print_results(git_files: List[str], fs_files: List[str], pattern: str):
    """Pretty print search results."""
    print(f"\n🔍 Search Results for: {pattern}\n")
    
    if git_files:
        print(f"📦 Found in git history ({len(git_files)}):")
        for f in git_files[:20]:  # Limit to first 20
            print(f"   git: {f}")
        if len(git_files) > 20:
            print(f"   ... and {len(git_files) - 20} more")
    
    if fs_files:
        print(f"\n📁 Found in filesystem ({len(fs_files)}):")
        for f in fs_files[:20]:  # Limit to first 20
            print(f"   fs:  {f}")
        if len(fs_files) > 20:
            print(f"   ... and {len(fs_files) - 20} more")
    
    if not git_files and not fs_files:
        print("✅ No matches found")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Search for files in git history and filesystem",
        epilog="""
Examples:
  python search.py "*.env"           # Find .env files
  python search.py "*apikey*"        # Find files with 'apikey'
  python search.py "secrets"         # Find files containing 'secrets'
  python search.py "/^\.env\..*$/"   # Regex: .env.* files
  python search.py "*.pem" --git-only
  python search.py "*password*" --fs-only /path/to/search
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("pattern", help="Pattern to search (glob, substring, or /regex/)")
    parser.add_argument("--git-only", action="store_true", help="Search git history only")
    parser.add_argument("--fs-only", action="store_true", help="Search filesystem only")
    parser.add_argument("--path", "-p", default=".", help="Root path to search (default: current dir)")
    parser.add_argument("--repo", "-r", default=".", help="Git repo path (default: current dir)")
    
    args = parser.parse_args()
    
    git_files = []
    fs_files = []
    
    if not args.fs_only:
        git_files = search_git_history(args.pattern, args.repo)
    
    if not args.git_only:
        fs_files = search_filesystem(args.pattern, args.path)
    
    print_results(git_files, fs_files, args.pattern)
    
    # Exit with error code if secrets found
    if git_files or fs_files:
        sys.exit(0)  # Found matches
    else:
        sys.exit(1)  # No matches


if __name__ == "__main__":
    main()