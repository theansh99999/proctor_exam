import os
import glob

replacements = {
    'text-dark': 'text-body-emphasis',
    'bg-light': 'bg-body-tertiary',
    'bg-white': 'bg-body'
}

templates_dir = "templates"
count = 0
for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith(".html"):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            orig_content = content
            for old_str, new_str in replacements.items():
                content = content.replace(old_str, new_str)
                
            if content != orig_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Updated {filepath}")
                count += 1
print(f"Total files updated: {count}")
