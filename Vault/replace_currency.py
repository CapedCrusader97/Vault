import os
def replace_in_dir(d):
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith('.html') or f.endswith('.py'):
                path = os.path.join(root, f)
                with open(path, 'r', encoding='utf-8') as file:
                    content = file.read()
                if '$' in content:
                    content = content.replace('$', '₹')
                    with open(path, 'w', encoding='utf-8') as file:
                        file.write(content)
                    print(f'Replaced in {path}')

replace_in_dir('Vault')
