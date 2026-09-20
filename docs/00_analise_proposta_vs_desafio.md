# Análise: proposta prévia (`legado/pipeline`) × desafio real

Data: 16/09/2026. Fontes: página oficial do desafio (todas as abas), competição
privada no Kaggle (Overview, Data, Rules, Leaderboard, Submissions), o script
oficial `kaggle_metric.py`, o conversor `json_to_submission.py`, a distribuição
final dos dados (15/09/2026, SHA-256 conferidos) e dois repositórios públicos de
participantes usados apenas como documentação do formato dos dados.

## 1. O que o desafio realmente pede

| Aspecto | Fato |
|---|---|
| Entrada | um `.txt` por parecer (UTF-8 sem BOM, LF, NFC); nome do arquivo = `documento_id` |
| Saída | **um JSON por documento**, `schema_version "1.2"`, lista `citacoes` com `id`, `inicio`, `fim` (codepoints, fim exclusivo), `trecho` (literal), `tipo` (`lei`/`jurisprudencia`), `classificacao` (`real`/`inventada`/`incompleta`), `resolucao` (`{"fonte":"jusbrasil","id_canonico":"…"}` só em `real`, senão `null`), `confianca` opcional em [0,1] |
| Submissão | `json_to_submission.py` → `submission.csv` (1 linha/doc: `inicio,fim,classe,id_canonico,confianca\|…`, `-` quando não há citação). O Kaggle aceita **só o CSV** (o zip enviado pela equipe em 14/09 deu erro) |
| Base canônica | SQLite `desafio1_bracis.db`, tabela `documentos(documento_id, id, tribunal, ano, relator, natureza, tipo, texto, texto_len)` + FTS5 `documentos_fts`. 1.014 registros: 996 acórdãos (STF 201, STJ 202, STM 200, TSE 199, TST 199), 5 súmulas, 13 dispositivos. Desde 15/09 os 18 não-acórdãos abrem com linha autodeclarada (`Súmula n. 123 do STJ`, `Artigo 321 da Lei nº 13.105, de 16 de março de 2015`) |
| Gabarito (dev) | `goldenset_offsets.csv` (com BOM → ler com `utf-8-sig`), 192 citações em 26 docs: N1 = 52 real / 32 inventada / 15 incompleta; N2 = 44 / 32 / 17. 164 `jurisprudencia`, 28 `lei`. Todos os 192 offsets batem com `texto[inicio:fim]`; todos os 95 `id_canonico` distintos existem na base |
| Classe | consequência da consulta por identificador à base fechada: 1 registro → `real`; 0 → `inventada`; sem identificador suficiente ou ≥2 candidatos sem desempate → `incompleta`. Desde 15/09, **100% das `incompleta` do dev são "tribunal + ano + relator" sem número de processo** |
| Níveis | N1 formato padrão (peso 1×); N2 ruído de OCR/abreviação/pontuação/quebra de linha (peso 2×). Garantia: **um dígito nunca vira outro dígito** — todo ruído é recuperável por normalização |
| Distratores | cabeçalho: número dos autos (CNJ), protocolo, OAB, `fls.`, valor da causa → falso positivo se extraídos. O mesmo formato CNJ no corpo é citação |
| Envelope | 1 GPU **24 GB VRAM** (L4/A10/RTX 4090), ~8 vCPUs, 32 GB RAM, **offline**, média ≤ 60 s/doc, teto 4 h. Fora disso = desclassificado |
| Modelos | só pesos abertos, referenciados por link + revisão fixa (commit); fine-tune permitido se os pesos forem publicados; decodificação determinística |
| Bundle | repositório + README + referência de modelos + requirements/Dockerfile + comando exato. Exigido das finalistas; verificação de reprodutibilidade após 30/09 |
| Prazo | submissões até **30/09/2026 23h59 BRT**; teto diário por equipe; "select up to 2 submissions" |
| Leaderboard | fase atual roda no dev set (gabarito aberto) e é referencial — 9 equipes em 1,10000; nossa equipe ("Leonardo Garcia10") em 0,90198. Reinicia quando o conjunto cego entrar (40% público / 60% privado) |

## 2. A métrica oficial, linha a linha (`kaggle_metric.py`)

1. Alinhamento por documento: matching **1-para-1 guloso por maior IoU**, com
   IoU ≥ 0,5 (em codepoints). Gabarito sem par → FN da classe esperada.
   Predição sem par → FP da classe predita, **exceto** se ≥ 90% dela estiver
   contida numa citação do gabarito já casada (componente "EXTRA" → ignorada).
2. Par casado, mesma classe: `real` só é TP se `id_canonico ∈ doc_ids` do
   gabarito; `real` com id errado → **FP de real, sem FN**. Outras classes → TP.
3. Par casado, classe diferente: FN da esperada **e** FP da predita (custa duas
   vezes). Se esperada = `inventada` e predita = `real` → conta em τ.
4. Por nível: macro-F1 sobre as classes com suporte > 0;
   `s = macroF1 · (1 − 0,5·τ)`, τ = inventada→real / total de inventada.
5. Brier só sobre pares casados **com** confiança (y=1 se acerto pleno):
   `b = clip(0,10·(1 − brier), 0, 0,10)`; `score_nível = s·(1 + b)`.
6. `score_final = (1·N1 + 2·N2) / 3`. Máximo teórico 1,1000.
7. **Erro fatal:** duas predições no mesmo documento com IoU ≥ 0,5 entre si
   invalidam a submissão (`ParticipantVisibleError`). Também: `real` sem
   `id_canonico` numérico, classe fora do enum, `inicio ≥ fim`, documento
   ausente na submissão.

Consequências de decisão:
- Perder um span custa 1 FN; um span espúrio custa 1 FP. Extrair "a mais"
  dentro de uma citação já casada é grátis **só** se o componente extra tiver
  IoU < 0,5 com a predição principal — duas predições do mesmo documento com
  IoU ≥ 0,5 são erro fatal (`ParticipantVisibleError`); a fusão garante
  interseção zero entre spans emitidos. Extrair fora não é grátis.
- Para uma citação do gabarito `real`, chutar `real` com o melhor candidato
  (1 FP se errar o id) é melhor que dizer `incompleta` (1 FN + 1 FP).
- Chamar `inventada` de `real` custa 1 FN + 1 FP **e** τ; é o erro a evitar.
- Confiança: usar a acurácia empírica do caminho de decisão, nunca 1,0 cego.

## 3. Veredito sobre a proposta prévia (BM25 + Qwen 9B cross-encoder + GBDT)

| # | Problema | Por que invalida |
|---|---|---|
| 1 | Trata como recuperação semântica + classificação supervisionada | A classe é função determinística da cardinalidade da consulta por **identificador**. BM25/semântica sobre inteiro teor devolve quem *cita* o número, não quem *é* o processo (armadilha documentada pela organização). Um REsp inventado casa semanticamente com dezenas de acórdãos do mesmo tema → `inventada→real` (τ) |
| 2 | Módulo 0 (spans) tratado como "bônus" | É a etapa central: span perdido = FN, distrator = FP. Os regex não cobrem prefixos encadeados (`AgInt no AREsp`), sufixo de UF, quebra de linha no identificador, nem OCR (`5UMULA`, `1.46g.781`, `34567l9`) |
| 3 | `incompleta` = "jurisprudência do STJ" | Essas frases **saíram** do gabarito (01/09 e 15/09). Hoje `incompleta` = tribunal + ano + relator, sem número |
| 4 | Esquemas de dados inventados (`base_referencia.csv`, `citacoes.csv`, `gabarito.csv`) | Dados reais: SQLite + `txt/` + `goldenset_offsets.csv` (BOM). Saída real: um JSON por documento, `schema_version`, `id`, `tipo` real (`lei`/`jurisprudencia`), `resolucao.fonte` |
| 5 | Métrica F1-macro "solta" sobre tabela | Oficial: alinhamento IoU, penalidade τ, Brier, pesos 1×/2×, regras de erro fatal (sobreposição) |
| 6 | GBDT com 5-fold em 192 citações | Ruído estatístico; sobreajuste ao dev; o ranking é no conjunto cego |
| 7 | `Qwen/Qwen2.5-9B-Instruct`, "24 GB de RAM", sem revisão fixa | Modelo inexistente (há 7B/14B; Qwen3-8B); o limite é **VRAM** de 24 GB; regras exigem link + commit hash e decodificação determinística |
| 8 | Um JSON único `{"documentos": [...]}` | Formato oficial é um arquivo por documento + CSV via conversor oficial |

O que se aproveita: a ideia de um cliente LLM com backends intercambiáveis
(mock/transformers/vLLM), o script de limite de potência (`nvidia-smi -pl`) e
o cuidado com fallbacks. Todo o resto é reescrito.

## 4. Decisões de arquitetura (resumo; detalhes em `02_arquitetura.md`)

1. **Núcleo determinístico** (regex por família + detector de cabeçalho +
   normalização de OCR + índice de números próprios por tribunal + resolução por
   cardinalidade) decide a esmagadora maioria dos casos e é 100% reproduzível.
2. **Árbitro LLM de pesos abertos (Qwen)** só nos casos residuais, com saída
   estruturada, `temperature=0`, revisão fixa, cache em disco, e sem poder
   inventar `id_canonico`: só escolhe entre candidatos que o índice devolveu ou
   normaliza um identificador que depois é consultado deterministicamente.
3. **Confiança calibrada por caminho de decisão** (acurácia empírica com
   suavização), medida pelo Brier no dev; nunca 1,0.
4. **Avaliação local = script oficial** (`kaggle_metric.py`) + diagnóstico
   (matriz de confusão, τ, Brier, lista de erros por documento).
5. **Robustez ao conjunto cego** medida com documentos sintéticos gerados a
   partir da própria base (números reais, ruído N2 amostrado do gerador), não
   só com os 26 documentos de desenvolvimento.
6. Bundle: Docker (offline), `make`, README, MANIFESTO de modelos, testes.
