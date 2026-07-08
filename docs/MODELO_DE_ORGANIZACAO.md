# Modelo de organizacao PARA

O Arruma Dir organiza somente depois de gerar uma previa.

## Pastas principais

- `projetos`: trabalhos ativos com resultado claro, como automacoes, codigo, escrita e engenharia.
- `areas`: responsabilidades continuas, como pessoal, saude, carreira e empresas.
- `recursos`: materiais de consulta, estudo, leitura, midia, modelos e referencias tecnicas.
- `arquivo`: itens inativos ou antigos que voce quer guardar.
- `entrada`: itens que ainda precisam de decisao humana.

## Exemplos de destinos

- `projetos/automacao_codigo`: scripts, Python, PowerShell, WSL, Rust, web apps e PLC.
- `projetos/engenharia`: CNC, lancamento de produto, projetos tecnicos e entregas de engenharia.
- `projetos/escrita`: projetos literarios, roteiros e textos autorais.
- `areas/pessoal`: documentos pessoais, exames e comprovantes.
- `areas/saude`: academia, anamnese, avaliacoes corporais e Next Fit.
- `areas/carreira`: curriculo, certificacoes e portfolio.
- `areas/empresas_financeiro`: empresas, contratos, extratos e financeiro.
- `recursos/engenharia`: CAD, SolidWorks, CATIA, MATLAB, Factory IO, FluidSIM e normas.
- `recursos/estudos`: cursos, pesquisas, atividades, SENAI e material academico.
- `recursos/leitura`: livros, artigos e itens para ler.
- `recursos/midia`: imagens, fotos, capturas, audio, video e memes.
- `recursos/modelos_office`: templates do Office, OneNote e modelos personalizados.
- `entrada/revisar`: tudo que nao tiver regra suficiente.

## Regras de seguranca

- Nenhum arquivo e apagado automaticamente.
- Arquivos repetidos exatos com marcador de copia sao movidos para `_duplicados`.
- Arquivos repetidos exatos sem marcador de copia ficam para decisao manual.
- Arquivos parecidos, mas com tamanho, extensao, data ou hash diferente, sao marcados como possiveis repetidos e ficam no lugar.
- `desktop.ini`, temporarios do OneDrive e pastas geradas pelo proprio app sao ignorados.
- Pastas numeradas como `7 - Estudos` perdem o prefixo numerico na previa.
- Pastas que ja representam um topico, como `10-engenharia`, sao mescladas no topico final.
- Pastas gerenciadas por programas e jogos ficam protegidas por padrao para nao quebrar configuracoes.
