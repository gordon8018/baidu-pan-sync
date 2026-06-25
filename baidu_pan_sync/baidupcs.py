from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class BaiduPcsGo:
    binary: Path
    config_dir: Path
    runner: Runner = subprocess.run

    def command(self, *args: str) -> list[str]:
        return [str(self.binary), *args]

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        import os
        env = os.environ.copy()
        env["BAIDUPCS_GO_CONFIG_DIR"] = str(self.config_dir)
        return self.runner(
            self.command(*args),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def download_file(self, remote_path: str, part_path: Path) -> None:
        part_path.parent.mkdir(parents=True, exist_ok=True)
        # Record files present before download so we can detect newly created file(s)
        before = {p.name for p in part_path.parent.iterdir() if p.is_file()}
        
        # Try direct download first
        download_failed = False
        try:
            result = self.run("download", remote_path, "--saveto", str(part_path.parent))
            # Check if download actually retrieved data (not 0B)
            if '0B' in result.stdout or '数据总量: 0' in result.stdout:
                download_failed = True
        except subprocess.CalledProcessError as e:
            download_failed = True
        
        # If direct download failed, try alternatives
        if download_failed:
            basename = Path(remote_path).name
            parts = remote_path.split('/')
            found = False
            
            # Try removing problematic intermediate path segments (apps/bypy)
            # Example: /auto-sync/st_stocks/apps/bypy/A股交易基础数据/file.csv
            #          might actually be at /auto-sync/st_stocks/A股交易基础数据/file.csv
            if 'apps' in parts and 'bypy' in parts:
                try:
                    # Remove both 'apps' and 'bypy'
                    filtered = [p for p in parts if p not in ('apps', 'bypy', '')]
                    shorter_path = '/' + '/'.join(filtered)
                    result = self.run("download", shorter_path, "--saveto", str(part_path.parent))
                    if '0B' not in result.stdout and '数据总量: 0' not in result.stdout:
                        found = True
                except:
                    pass
            
            # Try removing each directory level one by one
            if not found:
                for skip_pos in range(1, len(parts) - 1):
                    shorter_path = '/'.join(parts[:skip_pos] + parts[skip_pos+1:])
                    try:
                        result = self.run("download", shorter_path, "--saveto", str(part_path.parent))
                        if '0B' not in result.stdout and '数据总量: 0' not in result.stdout:
                            found = True
                            break
                    except:
                        continue
            
            if not found:
                # Try full remote file search as last resort
                candidate = self._find_remote_file('/', basename, max_depth=4)
                if candidate is not None:
                    try:
                        self.run("download", candidate, "--saveto", str(part_path.parent))
                    except:
                        raise
                else:
                    raise FileNotFoundError(f"Could not download: {remote_path}")

        # Detect newly created file(s) to handle potential filename encoding/normalization differences
        after_files = [p for p in part_path.parent.iterdir() if p.is_file()]
        after = {p.name for p in after_files}
        new = after - before
        
        if new:
            # If multiple new files, pick the most recently modified file
            if len(new) == 1:
                new_name = new.pop()
                (part_path.parent / new_name).replace(part_path)
                return
            newest = max(after_files, key=lambda p: p.stat().st_mtime)
            newest.replace(part_path)
            return

        # Fallback: check for the expected filename
        expected = part_path.parent / Path(remote_path).name
        if expected.exists():
            expected.replace(part_path)
            return

        raise FileNotFoundError(f"BaiduPCS-Go did not create expected file: {expected}")

    def _find_remote_file(self, base: str, target_basename: str, max_depth: int = 3) -> str | None:
        # Breadth-first search limited to max_depth to find a file matching target_basename
        from collections import deque

        queue = deque([(base.rstrip('/'), 0)])
        seen = set()
        while queue:
            dirpath, depth = queue.popleft()
            if depth > max_depth:
                continue
            if dirpath in seen:
                continue
            seen.add(dirpath)
            try:
                result = self.run('ls', dirpath)
            except Exception:
                continue
            out = (result.stdout or '') + (result.stderr or '')
            # Each non-empty line may contain a filename at the end; split lines and extract tail words
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Skip header/footer lines that don't look like file rows
                if line.startswith('#') or '目录' in line or '文件' in line:
                    # try to heuristically extract name after whitespace columns
                    parts = line.split()
                    if parts:
                        name = parts[-1]
                    else:
                        continue
                else:
                    parts = line.split()
                    name = parts[-1] if parts else line
                # Compose candidate path
                candidate = f"{dirpath.rstrip('/')}/{name}"
                # If name matches target basename, return candidate
                if name == target_basename:
                    return candidate
                # If this entry looks like a directory (ends with '/'), enqueue
                if line.endswith('/') or '目录' in line or name.endswith('/'):
                    subdir = candidate.rstrip('/')
                    queue.append((subdir, depth + 1))
        return None

    def ensure_remote_dir(self, remote_path: str) -> None:
        self.run("mkdir", remote_path)

    def transfer_share(self, url: str, passcode: str, remote_transfer_root: str) -> None:
        self.ensure_remote_dir(remote_transfer_root)
        self.run("cd", remote_transfer_root)
        self.run("transfer", url, passcode)
