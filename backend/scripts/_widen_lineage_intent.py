from pathlib import Path

p = Path("app/services/retrieval/query_expansion.py")
t = p.read_bytes().decode("utf-8")
old = '    ("lineage", ("来源系统", "血缘", "溯源", "来源表", "上游")),'
new = '    ("lineage", ("来源系统", "血缘", "溯源", "来源表", "上游", "来自哪里", "来自哪个", "来自")),'
assert t.count(old) == 1, t.count(old)
p.write_bytes(t.replace(old, new).encode("utf-8"))
print("patched lineage rule")
