# ADR 0004 — Documentos sintéticos com gabarito: gerador determinístico a partir da base

Data: 16/09/2026. Estado: aceita. Escopo: `src/caca_alucinacao/sinteticos/` (`gerador.py`,
`ruido.py`, `moldes.py`, `cabecalhos.py`), `scripts/gerar_sinteticos.py`, `tests/test_sinteticos.py`,
`docs/05_sinteticos.md`.

## Contexto

O conjunto de desenvolvimento tem 26 documentos e 192 citações; o ranking final é num conjunto cego
"com o mesmo formato, os mesmos níveis e distribuição de classes equivalente". Com 192 citações não
dá para (i) medir a robustez do detector/normalizador/resolução a formas e ruídos que o dev não
cobre, (ii) calibrar a confiança por caminho de decisão sem sobreajuste, nem (iii) avaliar o árbitro
LLM em casos suficientes. `docs/03_analise_gabarito.md` é uma especificação medida (fronteiras,
formas, ruído, distratores, estatísticas) e `docs/04_analise_base.md` descreve o que a base sabe
(números próprios, ambiguidades, súmulas e dispositivos). Isso basta para um gerador que reproduza a
distribuição do dev com números **reais** da base.

## Decisões

1. **Gabarito por construção, nunca por detector.** Cada citação é gerada a partir de um registro da
   base (ou de uma perturbação verificada contra o índice) e o span é registrado no momento em que o
   texto é montado. A classe é a consequência da consulta ao índice: `real` ⇔ número próprio de um
   registro (`por_digitos`), `inventada` ⇔ nenhum registro tem o número (conferido a cada geração;
   idem para súmula/dispositivo nas tabelas derivadas), `incompleta` ⇔ família `vaga` com
   tribunal + ano + relator reais e **multiplicidade ≥ 2** em `por_relator_ano`. Um gabarito que
   dependesse do detector reproduziria os erros que queremos medir.
2. **Offsets em codepoints, texto NFC/LF/sem BOM, quebra de linha por troca de espaço.** A
   diagramação em linhas de 92–106 chars substitui espaços por `\n` (mesmo número de codepoints),
   de modo que os offsets registrados antes da quebra continuam válidos e o span pode conter `\n`
   em qualquer posição — exatamente o que o dev mostra (18 spans N1 e 29 N2 com quebra). Uma
   fração dos spans é "protegida" (tratada como uma palavra) para reproduzir essas taxas.
3. **Ruído aplicado por partes, com rótulo.** Uma citação é uma lista de partes (`classe`,
   `conector`, `espaco`, `numero`, `sep`, `uf`…); `ruido.py` muta partes com as taxas de docs/03 §3
   e devolve rótulos (`nbsp`, `separador_uf_nao_padrao`, `ocr_letra_em_digito`…), gravados na
   coluna `ruidos` do gabarito estendido. Garantias mantidas: dígito nunca vira dígito; letra por
   dígito no máximo uma por número, nunca no primeiro caractere (a normalização exige dígito ASCII
   inicial — ADR 0001); UF nunca sofre OCR; no máximo uma quebra de linha vinda do ruído por span.
   Invariante testado: `digitos_canonicos(trecho) == digitos` para 100 % das citações de processo
   (exceto o rótulo `ood:ocr_primeiro_digito`, só no perfil agressivo).
   **Rodada 2 (R4-01, revisor 1):** o perfil agressivo também põe uma letra por dígito no número de
   súmula/tema/artigo e no ano da citação vaga (`ood:ocr_fora_do_processo`, 20 %); o perfil `dev`
   não, porque o dev só mostrou OCR em números de processo (5/5 eventos — evidência fraca, p ≈ 0,09,
   mas é o que foi medido). Invariante testado em `tests/test_sinteticos.py`: cada span assim marcado é
   detectado com fronteira exata e resolvido na classe do gabarito.
4. **Dois perfis, três níveis.** `dev` usa só formas observadas no dev (`moldes.CLASSES[*]["dev"]`
   e `["n2"]`, conectores/separadores medidos, moldes A–E). `agressivo` acrescenta formas
   *out-of-distribution* rotuladas `ood:*`: siglas que a base tem mas o dev nunca citou (ARE, EREsp,
   MS, RO, RRAg, AIRR, EI, HC…), conectores (`n.º`, `número`), separadores e abreviações inéditos,
   número antigo do TSE, registro do STJ, chaves ambíguas que a cadeia distingue, súmulas reais no
   mundo mas fora da base, moldes de vaga novos e armadilhas com tribunal/ano sem relator. Nível 1 =
   sem ruído; nível 2 = taxas de §3; nível 3 = ruído combinado e implica `agressivo`. A métrica
   oficial dá peso 1 a níveis desconhecidos, então o nível 3 pode ser avaliado com `kaggle_metric.py`.
5. **Frases próprias.** Nenhuma frase do conjunto de desenvolvimento é transcrita; as frases-molde,
   de enchimento e as armadilhas sem identificador (§6.3) foram escritas para o projeto e seguem só
   o *padrão* (artigo antes do span, pontuação depois, seções, fechamento). As armadilhas entram na
   numeração dos `citacao_id` e ficam fora do gabarito, como no dev (lacunas de numeração).
6. **Formato de saída = goldenset oficial** (`nivel, documento_id, citacao_id, inicio, fim, trecho,
   tipo, classificacao, id_canonico`, utf-8-sig, CRLF, `\n` escapado como `\\n` no trecho) mais
   `goldenset_estendido.csv` (família, tribunal, dígitos, cadeia, UF, ruídos, forma, ood, registro
   de origem) e `casos_llm.jsonl` no formato combinado com o árbitro (`normalizar_citacao`,
   `classificar_span`, `escolher_candidato`), incluindo negativos (armadilhas, CNJ do cabeçalho) e
   casos "vizinho a 1–2 dígitos" com resposta `null`.
7. **Determinismo total.** `random.Random(f"caca-alucinacao:{versão}:{seed}:{nível}:{perfil}:{i}")`
   por documento; nenhuma iteração sobre `set` define ordem; a base é lida por listas ordenadas.
   Mesmo seed ⇒ mesmos bytes.

## Consequências

- O gerador depende só de `BaseCanonica` (índice JSON) e da API preservada de
  `base_canonica.digitos`/`classes`/`normativos`; não importa `normalizacao.py` diretamente.
- Distribuição obtida (40 docs N2, seed 123): real 50 %, inventada 34 %, incompleta 16 %; `lei`
  15 %; 4–9 citações/doc (mediana 8); distância mínima entre spans 80 chars.
- O que **não** é reproduzido: prosa com sentido jurídico real (é enchimento coerente por matéria),
  ementas transcritas, citações repetidas no mesmo documento, `incompleta` com número (o dev não
  tem), inventadas por "classe trocada com número real" (ambíguas pela definição oficial; ficam de
  fora do gabarito e são monitoradas à parte), duplicatas textuais puras da base (sem resposta única).
- Rejeitado: gerar com LLM (não determinístico, sem garantia de gabarito) e usar o detector para
  anotar (circular).
