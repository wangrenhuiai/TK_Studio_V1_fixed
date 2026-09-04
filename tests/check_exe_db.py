"""Check EXE-created SQLite DB."""
import sqlite3
import os

db = r"C:\Users\Administrator\AppData\Local\TK_Studio\tk_studio.db"
print(f"DB exists: {os.path.exists(db)}")
print(f"DB size: {os.path.getsize(db)} bytes")

c = sqlite3.connect(db)
print(f"journal_mode: {c.execute('PRAGMA journal_mode').fetchone()[0]}")
print(f"busy_timeout: {c.execute('PRAGMA busy_timeout').fetchone()[0]}")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"tables: {tables}")

# works 表列数
cols = [r[1] for r in c.execute("PRAGMA table_info(works)").fetchall()]
print(f"works columns ({len(cols)}): {cols}")

# Chrome profile 目录
profile_dir = r"C:\Users\Administrator\AppData\Local\TK_Studio\chrome_headless_profile"
print(f"chrome_headless_profile exists: {os.path.exists(profile_dir)}")

# 日志
log_dir = r"C:\Users\Administrator\AppData\Local\TK_Studio\probes"
print(f"probes dir exists: {os.path.exists(log_dir)}")

c.close()
