# MOE Thrones · Assistente de Guilda — versão BETA 0.2

Aplicativo local (roda no seu computador, sem conta e sem internet) para guildas de **Myth of Empires: Thrones**:
calculadora recursiva de itens, catálogo de receitas, estoques, perks, calculadora de chassi de cavalo e mapas.

## Leia isto primeiro: dados reais importados, com ressalvas

Versão **beta 0.2**. Os objetos de dados do site foram recapturados com bytes intactos e decifrados (49 de 49,
autenticação AES-GCM válida, ou seja, conteúdo comprovadamente íntegro). Importados de verdade:

| Dado | Quantidade |
|---|---|
| Itens | 6.544 |
| Receitas (com bancada, nível, tempo e rendimento) | 3.742 |
| Perks/habilidades (inclui despertares de cavalo) | 2.143 |
| Marcadores de mapa do site | 6.031 (2 fora dos limites foram descartados) |

**Ressalvas importantes**
- **Edição (global × throne) é INFERIDA**, não declarada: só os manifestos de mapa dizem a edição. Em receitas e perks usei a
  ordem de carregamento no HAR (blocos grandes = compartilhado; o primeiro conjunto = global; o conjunto após o mapa
  throne = throne). Onde há as duas versões da mesma receita, as duas ficam (`r_<item>@global`, `@throne`) e a de throne é a padrão.
  Está escrito em cada registro. **Nenhum registro está "Verificado em Thrones"**: todos são "Comunitária".
- **Nomes**: as tabelas de tradução capturadas são em **russo** (quase tudo) e **português** (parcial). Não há chinês/inglês.
  Itens aparecem com o nome em russo; 526 itens não têm nenhum nome (aparecem pela chave interna). Não traduzi nada por conta própria.
- Perks: efeito mantido como "desconhecido" e fórmula não confirmada; **nenhum perk altera o cálculo**.
- Receitas não foram confirmadas contra a wiki de Thrones (a wiki só cobre ~40 receitas e o resumo não era confiável).
- Mapas: a posição dos marcadores usa a mesma conversão do código do site (origem e escala por mapa); conferi só a faixa de valores.
  No mapa, escolha "Marcadores do site" + uma camada.

## Instalar e executar (Windows)

1. Instale o **Python 3.10 ou mais novo** (https://www.python.org/downloads/ — marque "Add Python to PATH").
2. Descompacte o ZIP numa pasta.
3. Dê dois cliques em **`executar.bat`**. O navegador abre em http://127.0.0.1:8765.
4. Para fechar, feche a janela preta.

Não há nada para instalar com `pip`: usa só a biblioteca padrão do Python (SQLite incluso).
Linux/macOS: `./executar.sh`. Seus dados ficam em `data/moe.db` (faça backup desse arquivo ou use a aba Dados).

## As abas

| Aba | O que faz |
|---|---|
| **Calculadora de itens** | Fila de fabricação com vários itens e quantidades; expande receitas intermediárias recursivamente; soma materiais compartilhados **antes** de arredondar lotes; usa estoques; escolhe receita alternativa ou "coletar"; avisa ciclos, receitas ausentes e origem desconhecida; checkboxes coletado/separado/produzido; salva, duplica e exclui planos; divide por responsável; exporta CSV e lista de compras. |
| **Catálogo** | Busca por nome (pt/en/中文), ID, categoria, bancada, material, civilização, DLC, perk e validação. Mostra receitas, onde o item é usado e a fonte. Permite cadastrar itens e receitas. |
| **Estoques** | Vários estoques (pessoal, depósito, aliados) combináveis na calculadora. |
| **Perks** | Consulta com filtros. Só perks com **fórmula confirmada** de rendimento alteram o cálculo; o resto nunca mexe nos materiais. |
| **Cavalos** | Chassi: `base = painel − 0,16 × soma dos bônus das habilidades`, despertar compatível por cor, estábulo e comparação lado a lado. **Não prevê filhotes** (regras de cruzamento não foram encontradas). |
| **Mapas** | Os 4 mapas com arraste e zoom e marcadores seus. |
| **Dados** | Importar/exportar (JSON, CSV UTF-8 com BOM para Excel, backup completo), inventário dos 16 arquivos de dados do site, legenda de validação. |

## Como colocar dados (escolha um)

1. **Recapturar do site (recomendado).** Siga o cabeçalho de `tools/capturar_dados_site.js` (colar no console do
   navegador com o site aberto). Envie o `moe_objetos.json` gerado. Depois, `tools/descriptografar_moed.py` decodifica
   (experimental: o formato do envelope ainda é hipótese) e a aba **Dados → Importar arquivo do site** carrega
   `craftingStructures.json` e `perk.json`.
2. **Planilhas/JSON seus.** Colunas em `data/modelos/` (itens, receitas, ingredientes, perks). Aba Dados → Importar.
3. **Cadastro manual** na aba Catálogo.

## Mapas completos

Vêm só 16 tiles (zoom 0 dos 4 mapas). Para baixar os 1.344 restantes (zooms 1 a 3), com verificação SHA-256 e
pausa entre pedidos: `python tools\baixar_tiles.py` (≈ 10 a 15 minutos). Os nomes dos mapas na tela são **provisórios**
(derivados do ID interno). Que esses 4 sejam os mapas de Thrones foi informado por você; não deu para verificar.

## Testes

`python -m unittest discover -s tests -v` — 40 testes (calculadora, API, importadores, cavalos, mapas). Os dados de
teste são sintéticos (prefixo `teste_`) e ficam separados do catálogo.

## Validação dos dados

Todo registro tem um destes estados: Verificado (Thrones) · Corroborado · Jogo original · Comunitária ·
Tradução não confirmada · Pendente · Conflitante. Registros vindos do site entram como **Comunitária**: a calculadora
avisa quando usa receitas ainda não verificadas em fonte de Thrones.

## Limitações conhecidas desta beta

- Decifrados mas sem importador: drops de chefes, tesouros, afixos, soldados, generais, condados, plantio (plantio: fórmula não capturada).
- Regras de herança/cruzamento de cavalos não encontradas.
- `capturar_dados_site.js`, `baixar_tiles.py` e `descriptografar_moed.py` não puderam ser testados contra o site real
  (rede bloqueada onde foram escritos); o decodificador foi testado só com dados sintéticos.
- A calculadora soma toda a demanda de um intermediário antes de arredondar; o site arredonda por nível, então
  em cadeias com o mesmo item em níveis diferentes o resultado pode divergir do dele (o seu briefing pede a soma).
- Tradução para português: nomes de atributos de cavalo são provisórios; itens mantêm o nome original em chinês.

Imagens e dados do jogo pertencem à Angela Game; uso pessoal da sua guilda.

## Mapas e marcadores do moe-map.com (13/10/2026)
- Fonte: HAR do moe-map.com (Enj0y, v1.9.3a). Os `data.json` são texto puro, sem criptografia; ficam em `data/fontes/moe-map.com/`.
- Três mapas, chamados pelo site de **legacy**, **xizhou** e **v1**: 1.302 marcadores (fortalezas, minas, campos, animais, elites, senhores das feras, objetos). Nomes em inglês; ícones e tiles vieram do mesmo HAR.
- Aba Mapas: escolha "moe-map.com — …" e, em "Marcadores do site", "moe-map.com". Seus marcadores próprios (clique no mapa) convivem com eles.
- **Não confirmado:** qual mapa é do Thrones e qual é do jogo original. O site só os chama legacy/xizhou/v1.
- Coordenadas (mundo −4000…4000, y para cima) calibradas visualmente sobre o legacy; xizhou e v1 assumem a grade inteira ocupada, sem conferência visual.
- Zonas, níveis e estradas (polígonos) do site ainda não são desenhados. Para reimportar: `python tools/importar_moemap.py`.
- Menu lateral de filtros (beta 0.3.1): com "moe-map.com" ativo aparece à esquerda do mapa a lista de grupos (Fortalezas, Animais, Objetos, Minas, Campos, Elite mobs, Beast Lords) com contagem e ícone, caixa por grupo, "Remover tudo" / "Habilitar tudo" e filtro por facção. Nomes traduzidos para pt-BR por tabela própria; o que não está nela fica em inglês.
