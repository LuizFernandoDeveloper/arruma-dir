import sys
from pathlib import Path


if __name__ == "__main__" and __package__ is None:
    # Permite executar o app.py diretamente, adicionando o diretorio 'src'
    # ao path para que o pacote 'arruma_dir' possa ser encontrado.
    package_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(package_root))

from arruma_dir.gui import run


if __name__ == "__main__":
    run()
