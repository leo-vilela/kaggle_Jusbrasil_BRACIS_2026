# Documentos sintéticos com gabarito

Data: 16/09/2026. Código: `src/caca_alucinacao/sinteticos/` (`gerador.py`, `ruido.py`, `moldes.py`,
`cabecalhos.py`); script `scripts/gerar_sinteticos.py`; testes `tests/test_sinteticos.py`; decisão
`docs/decisoes/0004-sinteticos.md`. Especificação reproduzida: `docs/03_analise_gabarito.md` (§1
fronteiras, §2 formas, §2.6 moldes de vaga, §3 ruído N2, §4 dispositivos, §5 súmulas, §6 cabeçalhos e
distratores, §7 estatísticas, §8 inventadas) e `docs/04_analise_base.md` (a, b, c, e).

## 1. Para que serve

O dev tem 26 documentos/192 citações; o ranking é num conjunto cego com o mesmo formato. O gerador
produz, a partir da própria base canônica, quantos documentos forem necessários **com gabarito no
formato oficial**, para:

1. **Robustez** — medir detector, normalização e resolução em formas e ruídos que o dev cobre pouco
   (cada forma de §2 e cada ruído de §3 aparece dezenas de vezes em 40 documentos) e em formas que o
   dev não cobre (perfil `agressivo`, rótulos `ood:*`).
2. **Calibração** — estimar a acurácia por caminho de decisão (`calibracao.py`) com centenas de
   citações por caminho em vez de dezenas, e medir o Brier com `kaggle_metric.py`.
3. **Árbitro LLM** — `casos_llm.jsonl` com as três operações do contrato do árbitro e negativos.

## 2. Uso

```bash
PYTHONPATH=src python scripts/construir_indice.py            # se dados/indice.json não existir
PYTHONPATH=src python scripts/gerar_sinteticos.py --saida dados/sinteticos/n2_dev --n-docs 40 --nivel 2 --seed 123 --perfil dev
PYTHONPATH=src python scripts/gerar_sinteticos.py --saida dados/sinteticos/n3_ood --n-docs 40 --nivel 3 --seed 7
PYTHONPATH=src python scripts/gerar_sinteticos.py --saida dados/sinteticos/n2_ag_treino --n-docs 60 --nivel 2 --seed 321 --perfil agressivo
PYTHONPATH=src python -m unittest tests.test_sinteticos -v
```
(`make sinteticos` roda exatamente estes três comandos; os testes de detecção/resolução esperam
`n2_dev` e `n3_ood` com esses seeds e ficam "skipped" sem eles. A geração é determinística e o
`manifesto.json` grava o caminho do índice relativo à raiz — o artefato é reproduzível byte a byte
entre máquinas.)

API (`caca_alucinacao.sinteticos`):

```python
docs = gerar_conjunto(base, n_docs=40, nivel=2, seed=123, perfil="dev")   # list[Documento]
documento_id, texto, gabarito = docs[0]                                   # desempacotável
escrever_conjunto(docs, "dados/sinteticos/n2_dev", base)                 # txt/, csv, jsonl, json
validar_documento(doc)                                                    # offsets, IoU, distância, NFC
casos = gerar_casos_llm(docs, base)
linhas = ler_goldenset("dados/sinteticos/n2_dev/goldenset.csv")          # desfaz o "\\n"
```

Saída da pasta: `txt/<documento_id>.txt` (UTF-8 sem BOM, LF, NFC); `goldenset.csv` (colunas
oficiais, `utf-8-sig`, CRLF, `\n` do trecho escapado como `\\n`, como no goldenset do desafio);
`goldenset_estendido.csv` (+ `familia`, `tribunal`, `digitos`, `classe_cadeia`, `uf`, `ruidos`,
`forma`, `ood`, `origem_id`); `casos_llm.jsonl`; `estatisticas.json`; `manifesto.json`.
Os `documento_id` são `sin_n<nível>_<perfil>_<NNN>` (o `nivel` do CSV é 1, 2 ou 3; a métrica
oficial aceita o nível 3 com peso 1).

Níveis e perfis: `--nivel 1` sem ruído; `--nivel 2` ruído com as taxas de §3; `--nivel 3` ruído
combinado (implica `--perfil agressivo`). `--perfil dev` = só formas vistas no dev
(*in-distribution*); `--perfil agressivo` = formas inéditas rotuladas `ood:*` (pode ser combinado
com nível 1 ou 2 para isolar "forma nova" de "ruído").

Validação interna obrigatória (levanta `AssertionError` na geração): `trecho == texto[inicio:fim]`
em 100 % das citações; nenhum par de spans com IoU ≥ 0,5; distância mínima entre spans ≥ 60 chars;
NFC; sem CR/BOM; `real` ⇔ `id_canonico`.

## 3. O que é reproduzido fielmente

| Aspecto (docs/03) | Como |
|---|---|
| §0 distribuição | plano por documento sorteado com os pesos do dev: família processo 60 % / vaga 18 % / dispositivo 15 % / súmula 6,5 % / tema 0,5 %; dentro de processo 65 % real, dispositivo 50 %, súmula 45 %. Resultado (40 docs N2, seed 123): real 48 %, inventada 32 %, incompleta 20 %; `lei` 14 %; 4–9 citações/doc, mediana 7–8 |
| §1 fronteiras | span = partes concatenadas: processo do 1º token da cadeia (inclusive `processo nº`, `TST-`, prefixos, ordinais) até o último dígito ou a UF (com `)`); súmula até o número ou `do <T>`; tema até `da repercussão geral`; dispositivo até o diploma inteiro; vaga até a última palavra do nome. Palavra anterior sempre artigo (`o/a/os/no/na/nos/do/da/dos`), caractere seguinte `,`, `.`, espaço ou `\n` + minúscula (testado) |
| §2.1 classes | cadeia de classe **do registro** (`por_digitos` → `classe_propria`), com sigla/extenso/caixa alta/pontos/abreviações medidas (`moldes.CLASSES`), conectores `no/na/nos` por gênero, hífen no TST/TSE (`TST-ED-E-ED-RR-…`, `AgR-REspe`, misto `ED no AgR-REspe`), ordinais (`Segundo AgR na Rcl`); prefixos omitidos em ~3 % |
| §2.2 conector | N1: nenhum 53 % / `nº` 47 %; N2: `n°`, `Nº`, `No`, `n.`; espaço, espaço duplo, NBSP, `\n` |
| §2.3 número | curto com/sem pontos (17 % sem pontos já no N1), CNJ com sequencial curto (TSE/TST) ou de 7 dígitos (STM, PJe), sem pontuação após o hífen, com espaços, quebra dentro, `--`, `.-\n`, `-\n.`, `. `, letra por dígito (`l O S g G`, uma por número, nunca no início) |
| §2.4 UF | N1 `/UF`; N2 `/ `, `-`, ` - `, ` – `, ` (UF)`, `\n- `; UF do registro; ausente em CNJ TST/TSE e em 15 % dos CNJ do STM |
| §2.5 | `TST-` (com espaço opcional) e `processo nº`/`Processo nº` em ~55 % das citações TST |
| §2.6 vaga | moldes A–E com tribunal + ano + relator de um registro real, multiplicidade ≥ 2 em `por_relator_ano`; nomes de 2–4 palavras, caixa alta 37 %, quebra antes/dentro do nome, `Rel.  Min.`, `Rel.\nMin.`, OCR `proferldo`/`dc`, `ã`/`l` no nome; molde C só com Reclamação/AREsp/RHC/REsp; molde D só `Rcl`/`APL` |
| §3 ruído | taxas por família em `ruido.TAXAS_N2`, rótulos iguais aos da tabela de §3 na coluna `ruidos`; OCR de corpo em 3,8 % das palavras (`e→c`, `a→ã`, `c→e`, `m→rn`, `i→l`), dígito em palavra em caixa alta (`DO5`) raro; artigo antes do span nunca sofre OCR |
| §4 dispositivos | 13 reais da base (chave `(diploma, artigo)`), formas `art.`/`art`/`artigo`, ordinal ≤ 9, inciso/alínea/parágrafo em 25 %, diploma por sigla/extenso/número da lei; inventadas: artigo acima do último do diploma, artigo real sob outro diploma (`art. 319 da CF`), diploma fora da base (`Lei nº 9.504/1997`, `13.467/2017`) |
| §5 súmulas | 5 reais; inventadas com número acima dos verbetes (STF > 900, SV > 180, TSE > 160, STJ > 700, TST > 500) ou tribunal errado; `5UMULA`, `SÚMULA`, `Súm.`, quebra antes/dentro de `do STF`; tema `Tema N.NNN da repercussão geral` (`Tcma` no N2) sempre inventado |
| §6 cabeçalho | endereçamento em caixa alta por matéria, `Autos nº`/`Processo nº` + CNJ com J variado (conferido contra o índice), partes, `Protocolo`, `Memorial`, `Valor da causa`, `Relator`, `Autoridade coatora`, `Sessão de julgamento`, título da peça, variante `PARECER JURÍDICO Nº` + `Referência: autos nº`; abertura com `(OAB/UF NNNNNN)`; prosa começa depois (nenhum span antes de `meta["fim_cabecalho"]`) |
| §6.2/6.3 distratores | datas por extenso, `fls. NNN/NNN`, `R$`, `NN%` no corpo; 10 frases-armadilha sem identificador (numeradas nos `citacao_id`, ausentes do gabarito → lacunas como no dev) |
| §7 | uma citação por frase, ≥ 1 frase de ligação entre citações (distância mínima observada 73–98), sem número repetido no documento, sem registro repetido |
| §8 inventadas | 50 % por perturbação de 1–2 dígitos de um número real (vizinho, UF diferente), 50 % fora das faixas (Rcl 5 dígitos, RE/REsp/AREsp 7, RHC, STM `7001500–7999999`); **todas** conferidas contra `candidatos_por_numero` (0 número próprio) |
| docs/04 b | no perfil `dev` só chaves não ambíguas (o dev não amostra duplicatas); no `agressivo`, chaves ambíguas que a cadeia distingue (`ood:numero_ambiguo`), nunca duplicatas textuais |

Invariante verificado em 1.000 documentos (5 seeds × 5 combinações): `digitos_canonicos(trecho)
== digitos` e `separar_uf(trecho)[1] == uf` para 100 % das citações de processo sem
`ood:ocr_primeiro_digito` — o ruído nunca destrói a chave.

## 4. O que é aproximado

- **Prosa**: enchimento coerente por matéria (cível, penal, trabalhista, eleitoral, militar) com
  frases próprias; não há argumentação real nem ementas transcritas. O detector não deve depender
  disso, mas um árbitro LLM verá texto mais repetitivo que o real.
- **Taxas de ruído**: calibradas às contagens de §3 (93 citações N2), com combinação independente
  por ruído; no dev alguns ruídos podem ser correlacionados de forma que não medimos.
- **Quebra de linha**: diagramação a 92–106 colunas + proteção de ~55 % (N1) / 60 % (N2) dos spans
  reproduz as taxas de §3.2 em média (N1 ≈ 15 %, N2 ≈ 35 % dos spans com `\n`), não a posição
  exata.
- **Nomes de relator**: título-caso derivado do campo `relator` da base (`Min. FULANO` → `Fulano`),
  com partículas às vezes maiúsculas; sobrenomes muito compostos são recortados a 2–4 palavras.
- **Vaga**: multiplicidade exigida ≥ 2 (dev: ≥ 4); a coluna `forma` traz `candidatos=N`.
- **Cadeia TSE**: `ARESP` de registros do TSE é grafado `AREsp` (a base canoniza `AGRAVO EM RECURSO
  ESPECIAL` e `… ELEITORAL` para siglas distintas; o dev cita `AREspEl`).

## 5. In-distribution × out-of-distribution (perfil `agressivo`)

Tudo com rótulo `ood:*` na coluna `ruidos` e `ood=1`:

| rótulo | o que é |
|---|---|
| `ood:classe_inedita` | sigla que existe na base mas nunca foi citada no dev: ARE, EREsp, EAREsp, MS, HC, AP, RO, AIRR, RRAg, ROT, EI, CJ, CP, RDI, AIJE, PC, AC, ADI… (reais e inventadas) |
| `ood:forma_classe` | abreviação/sigla plausível não vista: `REsp.`, `Rcl.`, `Ag.Reg.`, `Emb. Decl.`, `R.H.C.`, `Apelação`, `Recurso de Revista`, `RECLAMAÇÃO`… |
| `ood:conector` | `n.º`, `N.º`, `número`, `num.` (docs/03 §2.2 registra que não ocorrem no dev) |
| `ood:separador_uf` | ` / `, `–` colado, ` — `, `(UF)` colado, ` /UF`, `/\nUF` |
| `ood:ocr_em_cnj` | letra por dígito dentro de CNJ (no dev só em número curto); `ood:ocr_primeiro_digito` letra no 1º caractere (irrecuperável por construção — ADR 0001) |
| `ood:ocr_fora_do_processo` | letra por dígito (mapa do dev, nunca no 1º dígito) no número de súmula/tema/artigo e no ano da citação vaga (20 % de cada família no N3). O dev só mostrou o fenômeno em números de processo (5/5 eventos, p ≈ 0,09 sob amostragem uniforme — evidência fraca), então fica fora do perfil `dev`; o detector tolera e corrige (`numero_com_ocr`, `ano_canonico`; revisão rodada 2, R4-01) |
| `ood:numero_antigo_tse`, `ood:registro_stj` | número sequencial antigo do TSE; registro `AAAA/NNNNNNN-D` do STJ |
| `ood:numero_ambiguo` | número próprio de ≥ 2 registros com cadeias diferentes (resposta = cadeia exata) |
| `ood:forma_sumula`, `ood:sumula_fora_da_base` | `Sumula`, `Súmula nº`, `Enunciado nº`; súmulas reais no mundo (STJ 7, STF 279, SV 11…) ausentes da base ⇒ `inventada` pela base fechada |
| `ood:forma_art`, `ood:forma_diploma`, `ood:dispositivo` | `Art.`, `Artigo`, `art.º`; `CF/88`, `CRFB`, `NCPC`, `Decreto-Lei nº 5.452/1943`, `Lei nº 8.078/1990`; leis fora da base com artigo que existe no mundo (`Lei nº 8.429/1992`, `9.099/1995`, `14.133/2021`, `Código Penal`) |
| `ood:molde_vaga` | moldes F–H (`decisão do STJ de 2021, relatada pelo Min. …`, `aresto do TSE, 2019, Relator Ministro …`, `julgado do STF, 2023, Rel. Min. …`) |
| armadilhas `armadilha_ood` (só em `casos_llm.jsonl`) | frases com tribunal + ano sem relator, ou "Ministro relator" sem ano — não são citação |

O nível 3 combina esses rótulos com taxas de ruído maiores (`ruido.TAXAS_N3`: letra por dígito
25 %, NBSP 40 %, sem pontos 50 %, OCR de corpo 6 %). Um score alto em `n2_dev` e baixo em `n3`
indica sobreajuste às formas do dev; a coluna `ruidos` permite a matriz de erros por rótulo.

## 6. Casos para o árbitro LLM (`casos_llm.jsonl`)

Uma linha por caso, `{"operacao", "documento_id", "citacao_id", "trecho", "contexto", "esperado"}`:

- `normalizar_citacao` (uma por citação de processo): `esperado = {"classe_cadeia": ["ED","AGINT","ARESP"],
  "numero_digitos": "1234567", "uf": "SP"|null, "tribunal": "STJ"|null, "eh_citacao": true}` — o
  tribunal é o do registro (real) ou o implícito pela classe (inventada; `null` para Rcl/HC/MS/AR).
- `classificar_span` (todas as citações + negativos): `trecho` é a janela de ±90 chars, `contexto`
  ±200; `esperado = {"eh_citacao", "familia", "tipo", "inicio_rel", "fim_rel"}` relativos ao
  `trecho`. Negativos (`eh_citacao: false`, demais `null`): frases-armadilha, distratores numéricos
  (datas, fls., R$, %) e o CNJ do cabeçalho (`rotulo`).
- `escolher_candidato` (processo): `candidatos = [{id_canonico, documento_id, tribunal, ano, relator,
  classe_propria, uf, cabecalho}]`; `esperado = {"indice": i}` para real (candidatos do índice se a
  chave é ambígua; senão o registro certo + 3 do mesmo tribunal/classe) e `{"indice": null}` para
  inventadas por perturbação, em que o **vizinho a 1–2 dígitos** está entre os candidatos — o caso
  que mede a penalidade τ.

## 7. Como usar para calibração e robustez

1. Gerar `n1_dev`, `n2_dev` (seeds distintos para treino/validação da calibração) e `n3`.
2. Rodar o pipeline (`caca_alucinacao.cli`) sobre `txt/` e avaliar com `kaggle_metric.py` usando
   `goldenset.csv` como solução (converter para o `solution.csv` do Kaggle como se faz com o dev).
3. Calibração: agrupar por `caminho` da `Decisao` e estimar a acurácia com suavização; conferir o
   Brier por nível; **não** reaproveitar o seed de treino na validação.
4. Robustez: cruzar erros com `goldenset_estendido.csv` (`ruidos`, `forma`, `ood`) para obter a
   taxa de acerto por rótulo; a diferença `n2_dev` × `n3` mede generalização.
5. Árbitro: `casos_llm.jsonl` com o backend `mock` (regressão) e com o modelo real (acurácia por
   operação; para `escolher_candidato` medir separadamente os casos com `indice: null`).

## 8. Limitações

- O gerador reproduz a **especificação medida** (docs/03/04), não o gerador original da organização;
  formas do conjunto cego fora dessa especificação não são cobertas além do perfil `agressivo`.
- Não gera `incompleta` com número, citações repetidas, enumerações (`REsp X e AREsp Y`), spans
  aninhados, nem inventadas "número real com classe/tribunal trocado" (classe ambígua pela definição
  oficial; monitorar à parte).
- A "verdade" de súmulas/dispositivos/temas é a base fechada: súmulas e artigos reais no mundo mas
  ausentes da base são `inventada` (perfil `agressivo`), o que penaliza um árbitro com conhecimento
  de mundo — deliberado, é a regra do desafio.
- Ambiguidade real da base (16 % de registros duplicados) não é amostrada no perfil `dev`; no
  `agressivo` só quando a cadeia de classes distingue. Duplicatas textuais puras não têm resposta
  única e ficam de fora.
- A prosa é sintética e repetitiva; conclusões sobre o árbitro LLM em texto natural devem ser
  confirmadas no dev.
- Relatores com nome corrompido na base (`DESEMBARGADOR CONVOCADO…`) são recortados; o teste de
  multiplicidade usa `relator_compativel` (tolerância de 1 edição), a mesma da resolução.

## 9. Conjuntos adversariais dos revisores (`scripts/adversarial/`)

Complementam este gerador com formas construídas por revisores independentes (32 conjuntos de 10–12
documentos, rodadas 1–4 de revisão): siglas e conectores inéditos, ruído de OCR combinado, moldes
de vaga em outras ordens, enumerações, atos normativos como distratores, layouts de cabeçalho,
órgãos não jurisdicionais. Todos têm **gabarito por construção** a partir de `dados/indice.json`
e seeds fixas (`gerar_adversarial*.py`; `make adversarial` = `scripts/adversarial/rodar_todos.sh`
regenera tudo em `dados/adversarial/<conjunto>/{txt,goldenset.csv,gabarito_notas.csv}` e roda a
métrica oficial em cada um; `erros.py <conjunto>` cruza os erros com as notas). Política de dados:
os geradores não contêm nenhum número da base — artigos e súmulas são consultados por POSIÇÃO na
tabela do índice (`artigo_k`, `sumula_k`) e as formas com OCR são montadas em tempo de execução
(`com_ocr`); `verificar_vazamento.py` os varre como qualquer arquivo versionado. Os scores por
conjunto estão nas ADRs 0005/0006 ("Revisão da rodada N").
