# arruma-dir

[![CI](https://github.com/LuizFernandoDeveloper/arruma-dir/actions/workflows/ci.yml/badge.svg)](https://github.com/LuizFernandoDeveloper/arruma-dir/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](#)

Organizador seguro de diretorios para Windows, com interface grafica, linha de comando, previa obrigatoria, deteccao de duplicatas e protecao para arvores CAD.

O projeto nasceu para resolver dois cenarios reais:

- organizar `C:\Users\luizf\OneDrive\Documentos` sem quebrar pastas criadas por programas;
- organizar `F:\projetos` seguindo padroes Ramtech/Macrotec e Opcao Industrial, preservando SolidWorks, SolidWorks Electrical, EPLAN e AutoCAD.

## Sumario

- [Visao Geral](#visao-geral)
- [Principios](#principios)
- [Gates de seguranca](#gates-de-seguranca)
- [Experiencia de operacao](#experiencia-de-operacao)
- [Interface grafica](#interface-grafica)
- [Instalacao](#instalacao)
- [Uso rapido](#uso-rapido)
- [Comandos principais](#comandos-principais)
- [Modo Documentos / PARA](#modo-documentos--para)
- [Modo Projetos / CAD](#modo-projetos--cad)
- [Protecao CAD](#protecao-cad)
- [Duplicatas](#duplicatas)
- [Troubleshooting](#troubleshooting)
- [Build do executavel](#build-do-executavel)
- [Testes](#testes)
- [Estrutura do repositorio](#estrutura-do-repositorio)
- [Disciplina de commits](#disciplina-de-commits)
- [Licenca](#licenca)

## Visao Geral

Area | Entrega
--- | ---
Documentos | Organiza arquivos pessoais pelo metodo PARA
Projetos | Classifica materiais de engenharia em uma estrutura mais legivel
Duplicatas | Detecta repetidos exatos por tamanho e SHA-256
CAD | Preserva arvores SolidWorks, Electrical, EPLAN e AutoCAD
Interface | GUI com selecao de local, previa e confirmacao digitada
Automacao | CLI para scans, relatorios, dedupe e build de `.exe`

## Principios

O `arruma-dir` foi feito para trabalhar com seguranca antes de trabalhar com velocidade.

- Nada e apagado automaticamente.
- Toda organizacao comeca por uma previa.
- A interface exige confirmacao digitada antes de mover arquivos.
- Raiz de disco e pastas de sistema sao bloqueadas.
- Duplicatas sao comparadas por tamanho e SHA-256, nao apenas pelo nome.
- Arquivos parecidos, mas diferentes, ficam para decisao manual.
- Arvores CAD sao preservadas para nao quebrar referencias internas.

## Gates de seguranca

Gate | O que bloqueia | Motivo
--- | --- | ---
Local | Raiz de disco e pastas de sistema | Evita operacao ampla demais ou perigosa
Previa | Aplicacao sem plano revisado | Toda mudanca precisa ser visivel antes
Confirmacao | Movimento real sem digitar `APLICAR` ou `MOVER` | Evita clique acidental
Raiz alterada | Aplicar depois de trocar o caminho | O plano vale apenas para a pasta escaneada
Duplicata incerta | Nome parecido com conteudo diferente | Mantem no lugar ate decisao manual
CAD | Arquivos internos de projeto CAD | Preserva referencias, caminhos relativos e metadados

## Experiencia de operacao

A saida e tratada como interface de trabalho. O objetivo e mostrar estado, risco e proximo passo sem esconder decisao importante.

Estado | Como ler
--- | ---
Previa | Nada foi movido; revise plano, repetidos e avisos
Aviso | Algo merece atencao, mas a analise continuou
Erro | A operacao parou ou aquele item nao foi processado
Quarentena | Arquivo movido para area separada, sem exclusao
CAD protegido | O item foi preservado para nao quebrar referencia

## Recursos principais

- Interface grafica em Tkinter.
- CLI para automacao e auditoria.
- Organizacao de Documentos pelo metodo PARA:
  `projetos`, `areas`, `recursos`, `arquivo` e `entrada`.
- Remocao segura de prefixos numericos em nomes de pastas.
- Classificacao por contexto, extensao e palavras-chave.
- Relatorios em JSON e CSV.
- Quarentena de duplicatas em `_duplicados`.
- Script especifico para `F:\projetos`.
- Varredura opcional de HDs externos em busca de materiais de projeto.
- Build de executavel Windows com PyInstaller.

## Interface grafica

Abra a interface:

```powershell
arruma-dir gui
```

Ou simplesmente:

```powershell
arruma-dir
```

Na tela principal voce escolhe:

- modo `Documentos / PARA`;
- modo `Projetos / CAD`;
- pasta raiz que sera analisada;
- busca de duplicatas;
- no modo Projetos/CAD, varredura de HDs externos;
- no modo Projetos/CAD, inclusao ou nao de duplicatas CAD no relatorio.

Fluxo seguro:

```text
Escolher local -> Gerar previa -> Revisar plano -> Confirmar -> Aplicar
```

Se o local for alterado depois da previa, a interface obriga gerar uma nova previa antes de aplicar.

## Instalacao

Clone o repositorio:

```powershell
git clone https://github.com/LuizFernandoDeveloper/arruma-dir.git
cd arruma-dir
```

Instale em modo desenvolvimento:

```powershell
python -m pip install -e .
```

Requisitos:

- Windows
- Python 3.10 ou superior
- Tkinter, ja incluso na maioria das instalacoes Python para Windows

## Uso rapido

Gerar previa para Documentos:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --json plano.arruma-plan.json --csv plano.arruma-plan.csv
```

Aplicar um plano revisado:

```powershell
arruma-dir apply "C:\Users\luizf\OneDrive\Documentos" --plan plano.arruma-plan.json --yes
```

Mover somente duplicatas exatas consideradas seguras para lote:

```powershell
arruma-dir dedupe "C:\Users\luizf\OneDrive\Documentos" --yes
```

Rodar varredura completa de duplicatas:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --full-duplicates --json plano.arruma-plan.json
```

Usar nomes mais compativeis com scripts e automacoes:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --compat-names --json plano.arruma-plan.json
```

## Comandos principais

Objetivo | Comando
--- | ---
Abrir interface | `arruma-dir`
Previa de Documentos | `arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --json plano.json`
Aplicar plano revisado | `arruma-dir apply "C:\Users\luizf\OneDrive\Documentos" --plan plano.json --yes`
Mover duplicatas seguras | `arruma-dir dedupe "C:\Users\luizf\OneDrive\Documentos" --yes`
Previa de projetos | `arruma-projetos scan --root "F:\projetos"`
Projetos com HD externo | `arruma-projetos scan --root "F:\projetos" --external`
Aplicar organizacao de projetos | `arruma-projetos apply --report RELATORIO.json --organize --yes`
Quarentena de duplicatas de projetos | `arruma-projetos apply --report RELATORIO.json --duplicates --yes`
Gerar executavel | `.\scripts\build_exe.ps1`

## Modo Documentos / PARA

Este modo organiza uma pasta pessoal de documentos em areas de uso claro.

Estrutura principal:

```text
Documentos
|-- entrada
|-- projetos
|-- areas
|-- recursos
|-- arquivo
`-- _duplicados
```

Exemplos de destino:

```text
projetos/automacao_codigo
areas/saude
areas/financas
recursos/engenharia
recursos/programacao
arquivo
```

Pastas criadas por aplicativos, jogos e ferramentas ficam protegidas quando o programa reconhece risco de quebra.

## Modo Projetos / CAD

O modo `Projetos / CAD` foi criado para `F:\projetos`.

Ele aprende e aplica uma organizacao mais conservadora para ambientes com engenharia, documentos de producao e CAD.

Comando principal:

```powershell
arruma-projetos scan --root "F:\projetos"
```

O relatorio padrao fica em:

```text
F:\projetos\_arruma_projetos\reports
```

Aplicar apenas organizacao revisada:

```powershell
arruma-projetos apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --organize --yes
```

Mover duplicatas exatas para quarentena:

```powershell
arruma-projetos apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --duplicates --yes
```

Vasculhar HDs externos:

```powershell
arruma-projetos scan --root "F:\projetos" --external
```

Importar candidatos encontrados em HD externo:

```powershell
arruma-projetos apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --import-external --yes
```

Mais detalhes em [docs/ORGANIZA_PROJETOS.md](docs/ORGANIZA_PROJETOS.md).

## Padroes aprendidos

### Ramtech / Macrotec

O script reconhece o padrao documentado em materiais internos de industrializacao:

```text
1- Projeto Eletrico (Eplan)
2- Projeto Eletrico (PDF)
3- Projeto Eletrico (DWG)
4- Projeto Mecanico
5- Documentos Macrotec
6- Referencias
7- Fotos
8- Documentos Inspecao
9- Documentos Projetos
10- Lista de Materiais Excel
11- Lista de Plaquetas Excel
12- Lista de Identificacoes Excel
```

Tambem separa documentos de politica, instrucao de trabalho, fluxograma, inspecao, fabricacao e caderno eletromecanico.

### Opcao Industrial

O script reconhece padroes de projeto mecanico e biblioteca:

```text
Projetos_Mecanicos
Biblioteca_Componentes
Biblioteca_Componentes/Itens_OP
Catalogos
Detalhamentos
Templates_SolidWorks
Cabos
Referencias
```

Codigos como `OP-...`, pastas numericas e revisoes `REV00` ajudam na classificacao.

## Protecao CAD

Projetos CAD nao sao tratados como arquivos comuns.

Por padrao, o sistema preserva arvores e metadados de:

- SolidWorks: `.sldprt`, `.sldasm`, `.slddrw`, `.slddrt`, `.prtdot`, `.asmdot`, `.drwdot`
- SolidWorks Electrical: `.project`, `.proj.tewzip`, `.tewzip`
- EPLAN: `.zw1`, `.zw9`, `.elk`, `.edb`, `.epj`, `.ept`
- AutoCAD: `.dwg`, `.dxf`, `.dwt`, `.dwl`, `.dwl2`, `.ctb`, `.stb`, `.pc3`, `.lin`, `.pat`, `.sv$`, `.ac$`

Duplicatas dentro dessas arvores ficam fora da quarentena automatica, a menos que voce peça explicitamente:

```powershell
arruma-projetos scan --root "F:\projetos" --include-cad-duplicates
```

Use essa opcao apenas para revisar caso a caso.

## Duplicatas

O projeto separa duplicatas em dois grupos.

Duplicata exata:

```text
mesmo tamanho + mesmo SHA-256
```

Possivel duplicata:

```text
nome parecido, mas tamanho, extensao, data ou conteudo diferente
```

Duplicatas exatas podem ser movidas para quarentena. Possiveis duplicatas ficam no lugar para decisao manual.

## Troubleshooting

### A interface nao abre

Confirme se o pacote esta instalado em modo desenvolvimento:

```powershell
python -m pip install -e .
arruma-dir gui
```

### O botao de aplicar esta bloqueado

Gere uma previa primeiro. Se voce trocou o local depois da previa, gere outra previa para aquele novo caminho.

### O scan de duplicatas ficou pesado

Use a interface com `Buscar repetidos` desmarcado ou rode pelo terminal sem duplicatas:

```powershell
arruma-dir scan "C:\Users\luizf\OneDrive\Documentos" --no-duplicates
```

### Arquivo CAD nao entrou como duplicata

Isso e esperado. O modo Projetos/CAD protege arquivos internos de SolidWorks, Electrical, EPLAN e AutoCAD por padrao.

Para apenas revisar no relatorio:

```powershell
arruma-projetos scan --root "F:\projetos" --include-cad-duplicates
```

### O GitHub Actions falhou

Rode localmente:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall src tests scripts
```

## Build do executavel

Instale dependencias de build:

```powershell
python -m pip install -e ".[build]"
```

Gere o `.exe`:

```powershell
.\scripts\build_exe.ps1
```

Saida:

```text
dist\ArrumaDir\ArrumaDir.exe
```

## Testes

Rodar testes:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Compilar arquivos Python:

```powershell
$env:PYTHONPATH = "src"
python -m compileall src tests scripts
```

## Estrutura do repositorio

```text
arruma-dir
|-- .github/workflows/ci.yml
|-- docs/
|   |-- MODELO_DE_ORGANIZACAO.md
|   `-- ORGANIZA_PROJETOS.md
|-- scripts/
|   |-- build_exe.ps1
|   `-- organiza_projetos.py
|-- src/arruma_dir/
|   |-- cli.py
|   |-- gui.py
|   |-- organizer.py
|   |-- project_organizer.py
|   `-- safety.py
|-- tests/
|-- LICENSE
|-- README.md
`-- pyproject.toml
```

## Disciplina de commits

O projeto segue uma regra simples: uma mudanca coerente por commit, diff revisado antes de gravar e nada de misturar refactor, feature e documentacao sem necessidade.

Fluxo recomendado:

```powershell
git status
git diff
git add README.md
git diff --staged
git commit -m "docs: ajusta readme operacional"
```

Para mudancas grandes, prefira separar:

- codigo;
- testes;
- documentacao;
- build/release.

## Publicacao inicial no GitHub

Para criar o repositorio local e subir para o GitHub:

```powershell
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/LuizFernandoDeveloper/arruma-dir.git
git push -u origin main
```

Neste checkout, o repositorio ja possui commits locais. Para configurar o remoto e subir:

```powershell
git branch -M main
git remote add origin https://github.com/LuizFernandoDeveloper/arruma-dir.git
git push -u origin main
```

## Aviso importante

Mesmo com travas de seguranca, organizacao de arquivos e uma operacao sensivel. Revise a previa antes de aplicar e mantenha backup dos dados importantes.

## Referencias

- [Backup_wsl-](https://github.com/LuizFernandoDeveloper/Backup_wsl-) como referencia de README operacional, gates e documentacao por fluxo.
- [wsl-vhd-automount](https://github.com/LuizFernandoDeveloper/wsl-vhd-automount) como referencia de comandos, diagnostico, troubleshooting e disciplina de operacao.
- [PARA Method](https://fortelabs.com/blog/para/) para a organizacao de documentos pessoais.
- [SolidWorks Pack and Go](https://help.solidworks.com/2023/english/SolidWorks/sldworks/c_pack_go_ovw_wpdm.htm) para preservar arquivos relacionados de modelos, montagens e desenhos.
- [SolidWorks Electrical Archive](https://help.solidworks.com/2026/english/swelec/r_swelec_archive_electrical_project.htm) para projetos arquivados e `.PROJ.TEWZIP`.
- [AutoCAD Xrefs](https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-Core/files/GUID-164C2548-91E6-476D-AFDF-6257340C2EE2.htm) para cuidado com referencias e caminhos relativos.

## Licenca

Distribuido sob a licenca MIT. Veja [LICENSE](LICENSE).
