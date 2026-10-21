# Export the page's embedded catalog and accepted differences to catalog.json for the Telegram bot.
import json, re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
cat = json.loads(re.search(r'const CATALOG = (\[.*?\]\]);', s).group(1))
acc = re.search(r"const ACCEPT_BASE = (\{.*?\});", s).group(1)
acc = json.loads(acc.replace("'", '"'))
json.dump({'catalog': cat, 'accept': acc}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(cat), acc)
