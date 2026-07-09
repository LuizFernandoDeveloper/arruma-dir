# Organizador de projetos

Este script e especifico para `F:\projetos`.

Ele aprende a estrutura Ramtech/Macrotec a partir dos documentos em:

```text
F:\projetos\projetos\Ramtech\Estudos referentes a macrotec
```

## Modelo aprendido

### Ramtech / Macrotec

- A pasta de projeto segue a ideia `numero do projeto + PV + cliente`.
- Subpastas padrao:
  - `1- Projeto Eletrico (Eplan)`
  - `2- Projeto Eletrico (PDF)`
  - `3- Projeto Eletrico (DWG)`
  - `4- Projeto Mecanico`
  - `5- Documentos Macrotec`
  - `6- Referencias`
  - `7- Fotos`
  - `8- Documentos Inspecao`
  - `9- Documentos Projetos`
  - `10- Lista de Materiais Excel`
  - `11- Lista de Plaquetas Excel`
  - `12- Lista de Identificacoes Excel`
- Documentacao para producao envolve identificacao de projeto, formulario de inspecao, desenho de fabricacao e caderno eletromecanico.
- Duplicatas exatas sao detectadas por tamanho e SHA-256.

### Opcao Industrial

A pasta `F:\projetos\organizar\4- Projeto Mecanico` mostra um padrao diferente, mais ligado a CAD mecanico e biblioteca SolidWorks:

- Projetos mecanicos numerados, por exemplo `000005 - Dispositivo...` e `047-007-000-REV00 - ...`.
- Itens/catalogo com codigo `OP-...`, como suportes, garras, pincas, ventosas e compensadores.
- `Catalogo Opcao` com catalogos PDF, `Codigos OP.xlsx`, detalhamentos, capa, garras, mordentes, perfil, SMC, tesouras e conexoes.
- `00000 - Componentes` como biblioteca de componentes mecanicos.
- `Solid\01 - Opcao Industrial` como templates SolidWorks (`.slddrt`, `.PRTDOT`, `.asmdot`).
- `CABOS` e `MODELOS DE CABOS` como area propria.
- `REFERENCIA` e `Linha Modelo 4` como referencias de montagem/modelo.
- `solid-eletrical\estudoDeCaso\.project` indica pacote/arvore de projeto/exportacao: o `.project`, o HTML, JS e a pasta `_arquivos` devem permanecer juntos.

Destinos canonicos:

- `projetos/Opcao/Projetos_Mecanicos`
- `projetos/Opcao/Biblioteca_Componentes`
- `projetos/Opcao/Biblioteca_Componentes/Itens_OP`
- `projetos/Opcao/Catalogos`
- `projetos/Opcao/Detalhamentos`
- `projetos/Opcao/Templates_SolidWorks`
- `projetos/Opcao/Cabos`
- `projetos/Opcao/Referencias`

## Regra de seguranca para CAD/eletrica

O script preserva arvores de CAD por padrao. Ele pode mover uma pasta inteira quando ela foi classificada com seguranca, mas nao desmonta arquivos internos de SolidWorks, SolidWorks Electrical, EPLAN ou AutoCAD.

Arquivos protegidos por padrao incluem:

- SolidWorks: `.sldprt`, `.sldasm`, `.slddrw`, `.slddrt`, `.prtdot`, `.asmdot`, `.drwdot`
- SolidWorks Electrical: `.project`, `.proj.tewzip`, `.tewzip`
- EPLAN: `.zw1`, `.zw9`, `.elk`, `.edb`, `.epj`, `.ept`
- AutoCAD: `.dwg`, `.dxf`, `.dwt`, `.dwl`, `.dwl2`, `.ctb`, `.stb`, `.pc3`, `.lin`, `.pat`, `.sv$`, `.ac$`

Duplicatas dentro dessas arvores ficam fora da quarentena automatica. Para incluir mesmo assim:

```powershell
python scripts\organiza_projetos.py scan --root "F:\projetos" --include-cad-duplicates
```

Use essa opcao apenas para gerar relatorio e revisar caso a caso. Em CAD, mesmo dois arquivos iguais podem estar ali para manter caminho relativo, revisao congelada ou pacote exportado.

Referencias usadas para a regra:

- SolidWorks Pack and Go: https://help.solidworks.com/2023/english/SolidWorks/sldworks/c_pack_go_ovw_wpdm.htm
- SolidWorks Electrical archive: https://help.solidworks.com/2026/english/swelec/r_swelec_archive_electrical_project.htm
- EPLAN backup/restore: https://www.eplan.help/en-us/Infoportal/Content/Plattform/2.9/Content/htm/bakbackupdlggui_k_prinzip.htm
- AutoCAD Xrefs e caminhos relativos: https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-Core/files/GUID-164C2548-91E6-476D-AFDF-6257340C2EE2.htm

## Gerar relatorio

```powershell
$env:PYTHONPATH = "src"
python scripts\organiza_projetos.py scan --root "F:\projetos"
```

O relatorio fica em:

```text
F:\projetos\_arruma_projetos\reports
```

O log completo da execucao fica em:

```text
F:\projetos\_arruma_projetos\logs
```

Para mostrar detalhes tambem no terminal:

```powershell
python scripts\organiza_projetos.py scan --root "F:\projetos" --verbose
```

## Vasculhar HDs externos

Somente drives removiveis por padrao:

```powershell
python scripts\organiza_projetos.py scan --root "F:\projetos" --external
```

Drive especifico:

```powershell
python scripts\organiza_projetos.py scan --root "F:\projetos" --external --external-drive "G:\"
```

O script copia candidatos para `F:\projetos\_arruma_projetos\entrada_hds` somente quando voce aplicar com `--import-external --yes`.

Popular base compara os HDs escolhidos com a base atual por conteudo. Arquivos que ja existem na base sao ignorados; o relatorio fica apenas com candidatos ausentes e destinos dentro de `F:\projetos\projetos`.

```powershell
python scripts\organiza_projetos.py scan --root "F:\projetos" --populate-base --external-drive "E:\" --external-drive "H:\"
```

Na interface grafica, use o campo de HDs externos, clique `Popular base`, revise a aba Plano e clique `Popular base` novamente para copiar.

## Aplicar

Primeiro revise o JSON gerado. Depois:

```powershell
python scripts\organiza_projetos.py apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --organize --yes
```

Mover duplicatas exatas para quarentena:

```powershell
python scripts\organiza_projetos.py apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --duplicates --yes
```

Importar candidatos encontrados em HD externo:

```powershell
python scripts\organiza_projetos.py apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --import-external --yes
```

Quando o relatorio foi gerado com `--populate-base`, este mesmo apply copia somente os candidatos ausentes para a base canonica.

Sem `--yes`, o comando simula.

Para aplicar simulando e ver tudo no terminal:

```powershell
python scripts\organiza_projetos.py apply --report "F:\projetos\_arruma_projetos\reports\projetos-report-YYYYMMDD-HHMMSS.json" --organize --verbose
```

## Criar template de projeto Ramtech

```powershell
python scripts\organiza_projetos.py template "P20051-792589 - BEM BRASIL" --root "F:\projetos" --yes
```

## Criar template de projeto mecanico Opcao

```powershell
python scripts\organiza_projetos.py template-opcao "047-007-000-REV00 - MONTAGEM DO FORNO" --root "F:\projetos" --yes
```
