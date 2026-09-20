# Arquitetura do verificador

```
.txt ─▶ texto ─▶ deteccao ─▶ normalizacao ─▶ base_canonica ─▶ resolucao ─▶ calibracao ─▶ contrato (JSON 1.2)
          │          │                                             │
          │          └── candidatos "fracos" ──▶ llm.arbitro ◀─────┘  (só casos residuais)
          └── fim_do_cabecalho (distratores)
```

Pacote: `src/caca_alucinacao/`. Idioma: português (nomes, docstrings, docs).
Núcleo **sem dependências** além da biblioteca padrão (o container da
organização roda offline; `numpy`/`pandas` só entram pelo `kaggle_metric.py`
oficial; `torch`/`transformers` só pelo árbitro LLM, opcional em runtime via
`--arbitro nenhum`).

## Convenções obrigatórias

- Python ≥ 3.10, `from __future__ import annotations`, type hints em tudo.
- Offsets sempre em **codepoints** da `str` lida com `encoding="utf-8"` e
  normalizada NFC (idempotente nos dados distribuídos). Nunca passar por bytes.
- Determinismo: nenhuma iteração sobre `set` define ordem de saída; desempates
  explícitos; `PYTHONHASHSEED=0` no Docker.
- Testes com `unittest` (não há `pytest` disponível no ambiente de
  desenvolvimento). Arquivos `tests/test_*.py`; rodar com
  `python -m unittest discover -s tests -v`.
- Nenhum trecho literal do gabarito em código ou testes (os dados não podem ser
  redistribuídos): testes usam números sintéticos que preservam o padrão.
- Logs via `logging`, nunca `print` dentro do pacote.

## Módulos e interfaces

### `texto.py`
```python
def carregar(caminho: Path) -> str                      # UTF-8 tal como no disco: sem NFC, sem traduzir \r\n
def carregar_com_codificacao(caminho: Path) -> tuple[str, str]   # (texto, "utf-8" | "cp1252" | "utf-8-replace")
def documento_id(caminho: Path) -> str                  # stem
def nivel_do_documento(documento_id: str) -> int        # "n2" → 2, senão 1
def fim_do_cabecalho(texto: str) -> int                 # offset onde começa a prosa
def linhas_com_offsets(texto: str) -> list[tuple[int, int, str]]
```
`fim_do_cabecalho`: o cabeçalho é o bloco inicial de metadados (endereçamento
em caixa alta, "Autos nº", "Processo nº", partes, protocolo, OAB, valor da
causa). Termina na primeira linha de prosa (frase longa com minúsculas e
pontuação) — ou nas frases curtas de prosa imediatamente antes dela; uma ementa
em caixa mista sem prefixo seguida de `Autos nº`/`Chave: valor` ainda é
cabeçalho. Tudo antes dele é zona de distratores: números CNJ ali **não** são
citações, e o número do cabeçalho repetido no corpo (`Nestes autos nº …`)
também não. Uma linha longa em caixa mista que identifica os autos (`Apelação Cível nº <CNJ>
da Comarca de …`) nas primeiras linhas ainda é cabeçalho, e um parágrafo de prosa todo em
CAIXA ALTA (frases longas, ≥ 30 % de palavras gramaticais, um sinal de oração) é prosa
(rodada 3). `pipeline.carregar_texto` delega a `carregar` (um só carregador); um arquivo que
não é UTF-8 é lido como cp1252 (offsets preservados) antes de cair na substituição por U+FFFD,
sempre com log ERROR.

### `normalizacao.py`
```python
def sem_acento(texto: str) -> str
def chave_textual(texto: str) -> str                    # minúsculas, sem acento, espaços colapsados
def separar_uf(trecho: str) -> tuple[str, str | None]   # "REsp 1.234.567/SP" → ("REsp 1.234.567", "SP")
def corrigir_ocr_em_numero(grupo: str) -> str           # "34567l9" → "3456719"; só letras confundíveis, só dentro de grupo numérico
def digitos_do_identificador(trecho: str) -> str        # núcleo numérico só dígitos ("" se não há)
def numeros_do_texto(texto: str) -> list[str]           # todos os números canônicos (para indexar a base)
def classe_processual_canonica(trecho: str) -> str | None  # "Rec. Esp." / "R.Esp." / "Recurso Especial" → "RESP"
def tolerante(a: str, b: str, max_erros: int = 1) -> bool  # comparação de palavras com ruído (rn↔m, acento, 1 troca)
```
Regras: (1) separar UF **antes** de corrigir OCR (o `S` de `/SP` viraria 5);
(2) letra só vira dígito quando colada a dígitos dentro do grupo numérico
(`AREspEI` não pode virar `AREsp1`); (3) mapa de confusões: `O/o→0`, `l/I/|→1`,
`S/s→5`, `g/q→9`, `G→6`, `B→8`, `Z/z→2`, `rn→m` em palavras; (4) quebras de
linha, espaços e pontuação dentro do número são removidos; (5) o padrão CNJ
`NNNNNNN-DD.AAAA.J.TR.OOOO` produz 20 dígitos com o sequencial preenchido com
zeros à esquerda; (6) números de 4 a 8 dígitos ("1.741.799", "66.987",
"7.557.199") ficam como estão, sem zeros à esquerda.

### `deteccao/`
```python
@dataclass(frozen=True)
class Achado:
    inicio: int; fim: int; trecho: str
    familia: str          # "processo" | "sumula" | "dispositivo" | "tema" | "vaga"
    tipo: str             # "jurisprudencia" | "lei"
    dados: dict[str, str] # grupos já isolados: classe, numero, uf, tribunal, ano, relator, artigo, diploma, sumula, vinculante...
    origem: str           # "regex:<nome>" | "llm"
    forca: float          # 0-1, confiança da detecção (regex estrito = 1.0; padrão amplo = menor)

def detectar(texto: str) -> list[Achado]   # ordenados por posição, sem sobreposição (IoU < 0,5 garantido)
```
Sub-módulos: `padroes.py` (blocos de regex reutilizáveis: siglas processuais,
conectores `n.º/nº/n./No/n°`, número com ruído, UF com separadores
`/SP`, `- SP`, `(SP)`, `–SP`, quebras de linha), `processo.py`, `sumula.py`,
`dispositivo.py`, `tema.py`, `vaga.py`, `distratores.py`, `fusao.py`
(resolve sobreposições: prefixo encadeado + classe principal = um só span; o
maior span vence; nunca dois achados com IoU ≥ 0,5).

Fronteiras do span seguem o gabarito (ver `docs/03_analise_gabarito.md`):
o span vai do primeiro token da classe processual (inclusive prefixos
encadeados como `AgInt no`, `EDcl no`) até a UF (inclusive) ou o último dígito;
súmula vai de `Súmula` até o tribunal (`do STJ`) quando presente; dispositivo
vai de `art.` até o diploma (`do CPC`, `da Constituição Federal`, `da Lei
nº 8.078/1990`); `vaga` vai de `julgado/acórdão/decisão/<classe>` até o fim do
nome do relator.

### `base_canonica/`
```python
@dataclass(frozen=True)
class Registro: documento_id: str; id_canonico: int; tribunal: str | None; ano: int | None; relator: str | None; natureza: str; texto_len: int; classe_propria: str | None

def construir_indice(caminho_db: Path) -> dict        # offline; serializável em JSON
class BaseCanonica:
    @classmethod de_arquivo(caminho_json) / de_banco(caminho_db)
    def candidatos_por_numero(self, digitos: str) -> list[Registro]          # números PRÓPRIOS (cabeçalho), nunca citações no corpo
    def candidatos_por_numero_e_classe(self, digitos: str, classe: str | None, tribunal: str | None) -> list[Registro]
    def sumula(self, tribunal: str | None, vinculante: bool, numero: int) -> Registro | None
    def dispositivo(self, diploma: str, artigo: str) -> Registro | None     # diploma canônico: "CPC","CC","CLT","CF","CPP","CPM","CDC","CE","LC64"
    def por_relator_ano(self, tribunal: str | None, ano: int | None, relator: str | None) -> list[Registro]
    def cabecalho(self, documento_id: str, n: int = 600) -> str            # p/ árbitro LLM
```
Índice de números próprios: por tribunal, o número do processo está no
cabeçalho (STF/STJ/TSE/STM, primeiras centenas de chars) ou na fórmula
`autos de <classe> nº TST-…` (TST, ~char 1.000) e no rodapé. O índice guarda,
por registro: dígitos canônicos (todas as formas: 7 dígitos, 20 dígitos CNJ,
registro `2019/0123456-7`), classe processual própria (`REsp`, `AgInt no AREsp`,
`RHC`…), tribunal, UF. Cobertura exigida: **96/96 citações `real` do dev
resolvem pelo índice**; número que aparece só no corpo de outros acórdãos
**não** entra. Súmulas e dispositivos: tabelas derivadas da primeira linha dos
18 registros (não à mão), com aliases de diploma (`CPC` = Lei 13.105/2015;
`CC` = Lei 10.406/2002; `CLT` = Decreto-Lei 5.452/1943; `CF`/`CF/88`/
`Constituição Federal`/`Constituição da República`; `CPP` = DL 3.689/1941;
`CPM` = DL 1.001/1969; `CDC` = Lei 8.078/1990; `Código Eleitoral` = Lei
4.737/1965; `LC 64/1990`).

### `resolucao.py`
```python
@dataclass(frozen=True)
class Decisao:
    classificacao: str; id_canonico: int | None; caminho: str; candidatos: tuple[int, ...]; detalhes: dict

def resolver(achado: Achado, base: BaseCanonica) -> Decisao
```
Caminhos (`caminho` é a chave da calibração), por família:
- `processo`: dígitos → candidatos próprios; filtro por tribunal (inferido da
  classe/UF/contexto) e por classe processual (`REsp` ≠ `AREsp` ≠ `AgInt no
  AREsp` — mas a classe **principal** casa mesmo com prefixo encadeado
  diferente, decidir com os dados); 1 → `real`; 0 → `inventada`; ≥ 2 → tentar
  desempate por classe/tribunal/UF/ano; sem desempate → árbitro LLM; se ainda
  ambíguo → `incompleta`.
- `sumula`: tabela derivada; ausente → `inventada`; sem número → `incompleta`.
- `dispositivo`: (diploma, artigo) na tabela → `real`; diploma coberto e artigo
  ausente → `inventada`; artigo sem diploma identificável → `incompleta`.
- `tema`: sem registro na base → `inventada` (confirmar com dados) .
- `vaga` (tribunal+ano+relator, sem número): `incompleta` direto.

### `calibracao.py`
```python
def confianca(decisao: Decisao, achado: Achado, tabela: dict[str, float]) -> float
def ajustar(tabela_inicial, avaliacoes) -> dict[str, float]   # acurácia empírica por caminho com suavização (Laplace), teto 0,98
```

### `llm/`
```python
class Arbitro(Protocol):
    def normalizar_citacao(self, trecho: str, contexto: str) -> dict | None      # {"classe","numero","uf","tribunal"} ou None
    def escolher_candidato(self, trecho, contexto, candidatos: list[dict]) -> int | None   # índice em candidatos ou None (ambíguo)
    def e_citacao(self, trecho, contexto) -> dict | None                          # {"familia","tipo","inicio_rel","fim_rel"} ou None
```
Backends: `mock` (heurístico, para testes), `transformers` (bf16, greedy,
`do_sample=False`, seed fixa), `vllm` (opcional). Modelo: `Qwen/Qwen2.5-7B-Instruct`
com revisão fixa em `MANIFESTO_MODELO.md`. Cache em disco por hash do prompt.
Saída sempre JSON validado; falha de parsing = abstenção (`None`), nunca
exceção que derrube o documento. Limite de VRAM: `torch.cuda.set_per_process_memory_fraction`
para ≤ 24 GB quando a GPU tiver mais.

### `contrato.py`, `pipeline.py`, `cli.py`
Schema 1.2, `id_canonico` emitido como **string** (exemplo oficial) — o
conversor e a métrica aceitam string ou inteiro. `validar(saida, texto)`
confere todos os campos, `trecho == texto[inicio:fim]`, ausência de pares com
IoU ≥ 0,5 (erro fatal na métrica), `resolucao` coerente com a classe.
CLI: `python -m caca_alucinacao.cli --input <txt/> --output <json/> --db <db> [--indice <json>] [--arbitro nenhum|mock|transformers|vllm]`.

## Scripts
- `scripts/preparar_dados.py` — zip → `dados/`, SHA-256, validação de offsets.
- `scripts/construir_indice.py` — índice de números próprios → `dados/indice.json`.
- `scripts/avaliar.py` — roda `kaggle_metric.py` oficial sobre `saida/` e imprime diagnóstico completo (por nível, por classe, τ, Brier, confusões, erros por documento).
- `scripts/gerar_submissao.py` — `json_to_submission.py` oficial + validação + zip dos JSONs.
- `scripts/gerar_sinteticos.py` — documentos sintéticos com citações reais da base + ruído N2 (para robustez e calibração).
- `scripts/treinar_calibracao.py` — ajusta `calibracao.json`.
- `scripts/baixar_modelo.sh`, `scripts/limitar_gpu.ps1`.

## Adendo (16/09, após a Fase 1)

- `tipos.py` define `Achado`, `Decisao`, `iou` e os enums; **todos** os módulos
  importam de lá (não redefinir dataclasses).
- `base_canonica/` já existe como protótipo validado (índice com cobertura 96/96;
  `digitos.py`, `classes.py`, `normativos.py`). `normalizacao.py` deve absorver
  `digitos.py`/`classes.py` como implementação única; `base_canonica.digitos` e
  `base_canonica.classes` continuam existindo como re-exports para não quebrar o
  índice.
- Especificações medidas: `docs/03_analise_gabarito.md` (detector, fronteiras,
  ruído, distratores, moldes de `vaga`) e `docs/04_analise_base.md`
  (índice, ambiguidades, resolução). Em caso de conflito com este documento,
  valem os documentos 03/04 (são medidos nos dados).
- Testes: `unittest`; rode só os seus arquivos durante o desenvolvimento
  (`python -m unittest tests.test_x -v`); a suíte inteira roda na integração.
- Testes com dados reais ficam sob `@unittest.skipUnless(TEM_DADOS, ...)` e
  nunca imprimem trechos do gabarito.

## Adendo (16/09, revisão da rodada 1)

- Três revisores independentes (correção, generalização, engenharia) apontaram 34 achados;
  as correções estão registradas nas ADRs 0001, 0005 e 0006 (seções "Revisão da rodada 1")
  e cobertas por `tests/test_revisao_rodada1.py` e `tests/test_vazamento.py`.
- Política de dados: nenhum trecho/número/nome do gabarito ou da base em arquivo versionado;
  `scripts/analise/verificar_vazamento.py` deriva a lista proibida do catálogo local e falha
  o `make lint`/`make testar` se algo vazar. Todos os exemplos de código, testes e docs são
  sintéticos (números fora da base, nomes fictícios, formas de OCR construídas).
- Engenharia: saneamento O(n log n) com teto de 5 000 achados/doc; escrita por documento dentro
  do `try`; pasta de saída conferida na partida (a imagem roda como root de propósito — bind
  mount de `/data/out`); banco/calibração/`--output` inválidos → código 2 com mensagem; `.TXT`
  aceito e entradas ignoradas listadas no log; `submission_jsons.zip` reprodutível byte a byte;
  (rodada 3) falha na carga do árbitro recua para o núcleo (`arbitro=None`, log ERROR); pasta de
  entrada sem `.txt` mas com `.txt` em subpastas → log ERROR nomeando-as; `dados/indice.json`
  guarda `banco.sha256`/`bytes` e o CLI reconstrói o índice quando o banco montado difere;
  `csv.field_size_limit` ampliado em `avaliar.py`/`gerar_submissao.py` (célula `citacoes` de
  milhares de citações); `make sinteticos` gera `n2_dev`/`n3_ood`/`n2_ag_treino` com os seeds
  documentados e o `manifesto.json` grava o índice relativo à raiz;
  `Dockerfile.llm` com torch 2.7.1 + CUDA 12.8, `HF_HOME` apontado para `/modelos/hf`,
  `requirements-llm.txt` pinado e `torch.use_deterministic_algorithms(True, warn_only=True)`.
- (rodada 4) lote vazio → código 2 com mensagem (nunca um "sucesso" de zero JSONs); arquivos
  ocultos (`.x.txt`, `._x.txt`) ignorados com aviso; `cp1252` só quando o arquivo não tem NENHUMA
  sequência UTF-8 multibyte válida (um UTF-8 com um byte espúrio cai em `replace`, sem deslocar
  offsets); `texto._RE_PROSA` e `processo._RE_NOME_EXTENSO` ancorados (linha de 100 KB de
  minúsculas em < 1 s); `.dockerignore` com `**/__pycache__/` e `**/*.pyc` (+ limpeza na imagem);
  geradores adversariais versionados em `scripts/adversarial/` (`make adversarial`); mensagens de
  `preparar_dados.py` (AUSENTE ≠ DIVERGE) e de `preparar_saida` (root/`--user`) corrigidas; o
  árbitro é residual por desenho (0 chamadas no dev; ADR 0003).
