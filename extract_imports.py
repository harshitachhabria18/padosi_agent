import ast
import os
import sys

def get_imports(path):
    imports = set()
    for root, dirs, files in os.walk(path):
        if 'venv' in dirs:
            dirs.remove('venv')
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        tree = ast.parse(f.read(), filename=file_path)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for n in node.names:
                                imports.add(n.name.split('.')[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.add(node.module.split('.')[0])
                except Exception as e:
                    pass
    return sorted(list(imports))

if __name__ == '__main__':
    project_path = sys.argv[1]
    imports = get_imports(project_path)
    for imp in imports:
        print(imp)
