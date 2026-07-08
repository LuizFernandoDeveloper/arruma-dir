# Arruma Dir

Arruma Dir e um organizador seguro para a pasta Documentos do Windows. Ele usa o metodo PARA, cria uma previa, sugere destinos, padroniza nomes, encontra repetidos por hash e so move arquivos quando voce confirma.

O alvo inicial do projeto e:

```text
C:\Users\luizf\OneDrive\Documentos
```

## O que ele faz

- Organiza pelo metodo PARA: `projetos`, `areas`, `recursos`, `arquivo` e `entrada`.
- Usa subpastas por contexto, como `projetos/automacao_codigo`, `areas/saude` e `recursos/engenharia`.
- Remove prefixos numericos de pastas como `7 - Estudos` ou `10-engenharia`.
- Mantem uma previa antes de qualquer mudanca real.
- Protege pastas criadas por programas e jogos, como Battlefield, OneNote, Office, MATLAB, SolidWorks e Visual Studio.
- Detecta repetidos exatos por tamanho + SHA-256, nao apenas pelo nome.
- Marca possiveis repetidos quando o nome parece igual mas existe diferenca de tamanho, extensao, data ou conteudo.
- Move em lote somente repetidos exatos com marcador claro de copia, como `(1)`, `Copia`, `copy` ou `duplicado`.
- Mantem possiveis repetidos no lugar ate voce decidir.
- Mantem repetidos exatos sem marcador de copia para decisao manual, evitando mexer em caches, demos e pastas de programa.
- Tem interface grafica em Tkinter e comandos de terminal.
- Pode ser empacotado como `.exe` com PyInstaller.

## Instalar em modo desenvolvimento

```powershell
cd F:\codex\Arruma-dir
python -m pip install -e .
```

## Abrir a interface

```powershell
arruma-dir gui
```

Sem argumentos, o app tambem abre a interface:

```powershell
arruma-dir
```

Na interface voce escolhe:

- o modo `Documentos / PARA` ou `Projetos / CAD`;
- a pasta raiz que sera organizada;
- se a previa deve buscar repetidos;
- no modo Projetos/CAD, se deve vasculhar HDs externos e se duplicatas CAD devem entrar no relatorio.

Por seguranca, a interface bloqueia raiz de disco e pastas de sistema, exige previa antes de aplicar e pede confirmacao digitada para qualquer movimentacao real.

## Gerar uma previa pelo terminal

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --json plano.arruma-plan.json --csv plano.arruma-plan.csv
```

Por padrao, a busca de repetidos usa limite de tempo e ignora arquivos muito grandes para a interface continuar responsiva. Para uma varredura completa:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --full-duplicates --json plano.arruma-plan.json
```

Para nomes mais faceis de ler por scripts, use:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --compat-names --json plano.arruma-plan.json
```

## Aplicar a organizacao

Primeiro gere e revise o JSON. Depois rode:

```powershell
arruma-dir apply "C:\Users\luizf\OneDrive\Documentos" --plan plano.arruma-plan.json --yes
```

Sem `--yes`, o comando mostra uma simulacao.

## Mover repetidos

```powershell
arruma-dir dedupe "C:\Users\luizf\OneDrive\Documentos" --yes
```

Somente copias exatas com marcador claro de copia vao para:

```text
C:\Users\luizf\OneDrive\Documentos\_duplicados
```

Arquivos parecidos com diferencas ficam na previa e no JSON para revisao manual.

Para mover todos os duplicados exatos, inclusive os que nao tem marcador de copia, use:

```powershell
arruma-dir dedupe "C:\Users\luizf\OneDrive\Documentos" --all-exact --yes
```

## Organizar F:\projetos

O projeto tambem inclui um script especifico para `F:\projetos`, aprendendo o padrao Ramtech/Macrotec e Opcao Industrial.

```powershell
arruma-projetos scan --root "F:\projetos"
```

Ele gera relatorio antes de mover qualquer coisa, procura duplicatas exatas e pode vasculhar HDs externos. Arvores de SolidWorks, SolidWorks Electrical, EPLAN e AutoCAD sao preservadas por padrao para nao quebrar referencias de CAD.

Veja [docs/ORGANIZA_PROJETOS.md](docs/ORGANIZA_PROJETOS.md).

## Gerar o .exe

```powershell
.\scripts\build_exe.ps1
```

O executavel fica em:

```text
dist\ArrumaDir\ArrumaDir.exe
```

## Modelo de organizacao

Veja [docs/MODELO_DE_ORGANIZACAO.md](docs/MODELO_DE_ORGANIZACAO.md).

## Licenca

MIT. Veja [LICENSE](LICENSE).
