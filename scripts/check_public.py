"""Check the files intended for public Git distribution; never prints matching secrets."""
from pathlib import Path
import re,subprocess
root=Path(__file__).resolve().parents[1]
if (root/'.git').is_dir():
 result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True)
 paths=[root/p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
else:
 paths=[p for p in root.rglob('*') if p.is_file() and not any(x in p.relative_to(root).parts for x in ['.git','node_modules','__pycache__','.venv'])]
issues=[]
sensitive_suffixes={'.pem','.key','.p12','.pfx','.db','.sqlite','.sqlite3','.log','.pyc'}
patterns={
 'private key':r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
 'GitHub token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})',
 'private local path':r'[CD]:[\\/](?:Users[\\/]|明歌IP[\\/]|MingCoding[\\/])',
}
private_addresses=['.'.join(x) for x in [('106','53','152','168'),('43','153','230','83'),('39','108','123','154')]]
for f in paths:
 rel=f.relative_to(root).as_posix()
 if f.name=='.env' or (f.name.startswith('.env.') and not f.name.endswith('.example')) or f.suffix.lower() in sensitive_suffixes:
  issues.append((rel,'private filename'))
 try:text=f.read_text(encoding='utf-8')
 except UnicodeDecodeError:continue
 for label,pattern in patterns.items():
  if re.search(pattern,text):issues.append((rel,label))
 if any(x in text for x in private_addresses):issues.append((rel,'production address'))
if issues:
 for rel,label in issues:print(label+': '+rel)
 raise SystemExit(1)
print('PASS: checked '+str(len(paths))+' public files; no blocked credentials, data files, private paths or production addresses.')
