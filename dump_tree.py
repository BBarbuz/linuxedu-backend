#!/usr/bin/env python3
import os
import sys

ALLOWED_EXTENSIONS = {
    ".py",
    ".env"
}

EXCLUDED_DIRS = {
    "venv", ".venv", "__pycache__", "node_modules", ".git"
}



def dump_directory_tree(root_dir, output_file):
    """
    Przechodzi po całym drzewie folderów i zapisuje ścieżki + zawartość plików tekstowych
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# Zawartość drzewa katalogów: {root_dir}\n")
        f.write(f"# Wygenerowano: {os.path.abspath(root_dir)}\n\n")
        
        for root, dirs, files in os.walk(root_dir):
            # Pomijamy ukryte foldery (opcjonalnie)
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in EXCLUDED_DIRS]
            
            level = root.replace(root_dir, '').count(os.sep)
            indent = '  ' * level
            
            # Ścieżka do bieżącego folderu
            rel_path = os.path.relpath(root, root_dir)
            if rel_path == '.':
                rel_path = ''
            f.write(f"\n{'/' + rel_path if rel_path else root_dir}\n")
            f.write(f"{'─' * (len(rel_path) + 1 if rel_path else len(root_dir))}\n")
            
            # Pliki w folderze
            for file in sorted(files):
                ext = os.path.splitext(file)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue

                file_path = os.path.join(root, file)
                rel_file_path = os.path.join(rel_path, file) if rel_path != '.' else file
                
                try:
                    # Próba odczytu pliku tekstowego
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file_content:
                        content = file_content.read()
                        
                        f.write(f"\n{indent}{rel_file_path}\n")
                        f.write(f"{indent}{'─' * (len(rel_file_path) - indent.count('  '))}\n")
                        
                        # Zapisujemy zawartość z numeracją linii jeśli plik > 1 linii
                        if len(content.strip().split('\n')) > 1:
                            for i, line in enumerate(content.split('\n'), 1):
                                f.write(f"{indent}  {i:3d} | {line}\n")
                        else:
                            f.write(f"{indent}  {content.strip()}\n")
                        
                        f.write("\n")
                        
                except (UnicodeDecodeError, PermissionError, IsADirectoryError):
                    # Plik binarny/nieczytelny lub brak dostępu
                    f.write(f"{indent}{rel_file_path} [BINARNY/NIECZYTELNY]\n\n")
                except Exception as e:
                    f.write(f"{indent}{rel_file_path} [BŁĄD: {str(e)}]\n\n")

if __name__ == "__main__":
    # Domyślnie bieżący folder
    root_directory = os.getcwd()
    output_filename = "tree_dump.txt"
    
    # Opcjonalny argument: inny folder i nazwa pliku
    if len(sys.argv) > 1:
        root_directory = sys.argv[1]
    if len(sys.argv) > 2:
        output_filename = sys.argv[2]
    
    print(f"Przeszukuję: {os.path.abspath(root_directory)}")
    print(f"Wynik zapiszę do: {output_filename}")
    print("-" * 50)
    
    try:
        dump_directory_tree(root_directory, output_filename)
        print(f"✅ Zakończono! Zapisano do: {os.path.abspath(output_filename)}")
    except KeyboardInterrupt:
        print("\n⚠️  Przerwano przez użytkownika")
    except Exception as e:
        print(f"❌ Błąd: {e}")
