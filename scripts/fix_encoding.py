# Fix mojibake using ftfy
import ftfy
path = 'templates/billing_plans_public.html'
with open(path, 'r', encoding='utf-8') as f:
    raw = f.read()
fixed = ftfy.fix_text(raw)
with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(fixed)
print('Encoding fix done.')
