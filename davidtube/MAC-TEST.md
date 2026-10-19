# Teste no Mac: logo DavidTube no YouTube 21.41.5

Porquê este teste: o CI é à prova de falhas (se algo correr mal, fica o logo
original). O único risco real é um catálogo que passa na validação do
`assetutil` mas faz a app crashar no iPhone. Só tu consegues confirmar isto,
com as ferramentas da Apple e um telemóvel verdadeiro.

## 1. Pré-requisitos

- Mac com macOS e Xcode (ou só as command line tools: `xcode-select --install`),
  que trazem o `assetutil`. Confirma com `command -v assetutil`.
- `python3` e `git`.
- O IPA do YouTube 21.41.5 já descarregado (ex.: `~/Downloads/youtube.ipa`).
- Internet (o `pip` instala o Pillow num venv temporário). Se já tiveres um
  python com Pillow: `export DAVIDTUBE_PYTHON=/caminho/para/python`.

## 2. Código e helper

```sh
git clone -b davidtube-logo-assets https://github.com/DavidSobral/YouProEXTRA.git
cd YouProEXTRA
sh davidtube/mac_check.sh ~/Downloads/youtube.ipa
```

O IPA original nunca é alterado. Tudo fica em `./davidtube-check/`:
`work.ipa` (o IPA com patch), `original.car`, `patched.car`, `original.json`,
`patched.json` (saída de `assetutil --info`).

## 3. O que esperar

- `::notice::DavidTube logo patched into IPA`: tudo bem, o logo foi aplicado e
  o `assetutil` aceitou o catálogo.
- `::notice::DavidTube logo: logo not applied` / `assetutil unavailable`: nada
  foi alterado (sem `assetutil` ou nada para trocar).
- `::warning::...`: algo falhou (patch, extração ou validação) e o IPA ficou
  igual. Copia a mensagem completa.
- Resumo final: "work.ipa DIFFERS" = patch aplicado; "IDENTICAL" = não aplicado.
  Depois vêm o número de entradas dos dois JSON (o patched deve ter quase o
  mesmo número) e, para cada um dos 8 nomes (`youtube_logo`, `..._dark`,
  `..._cairo`, `..._dark_cairo`, `youtube_premium_logo`, `..._white`,
  `..._cairo`, `..._dark_cairo`), os campos antes/depois. Esperado: mesmos
  Scale/PixelWidth/PixelHeight (1x, 2x, 3x), Encoding possivelmente diferente;
  SizeOnDisk maior (o catálogo cresce uns ~3 MB, é normal).

## 4. Instalar e verificar no iPhone

1. Passa `davidtube-check/work.ipa` para o iPhone (AirDrop/Ficheiros) e instala
   com o SideStore (My Apps, `+`, escolhe o ficheiro).
2. Abre a app (tem de abrir sem crashar) e verifica o logo no cabeçalho em
   **modo escuro** e em **modo claro** (Definições do iOS, Ecrã e brilho).
3. Confirma: arestas nítidas; **sem halo escuro** à volta do logo (isso indica
   problema de alfa pré-multiplicado); tamanho e posição certos; mais nada
   mudou na interface. Se tiveres o YouTube Premium, vê também o logo Premium.

## 5. Se crashar

Definições, Privacidade e segurança, Análises e melhorias, Dados de análise:
procura `YouTube-...ips`. Partilha o ficheiro (ou as linhas `exception`,
`termination` e o início de `Thread 0 Crashed`). Pistas: frames em `CoreUI` /
`libcompression` / `lzfse` apontam para o formato do payload; `UIImage` /
`CUINamedImage` ou `nil` ao carregar a imagem apontam para flags ou pixels.

## 6. O que me enviar

Se algo falhar ou parecer estranho: faz zip de `original.json`, `patched.json`
e do texto do terminal (e o crash log, se houver) e envia. Não contêm
segredos.

## 7. Se falhar: o que tentamos a seguir

Detalhes não verificados (ver `davidtube/tools/csi.py`): blocos LZFSE
`bvx-` sem compressão, alfa pré-multiplicado, flags do cabeçalho, tamanho.

- `assetutil` rejeita o catálogo ou a app crasha ao abrir: variante com flags
  de cabeçalho `0x0` em vez de `0x10`.
- Crash em `libcompression`/LZFSE: payload ZIP ou sem compressão em vez de
  LZFSE.
- Logo com halo/bordas escuras: pixels não pré-multiplicados.
- Tudo OK no `assetutil` mas o logo não muda: manda os JSON, vemos que
  facets/entradas faltam.

Cada variante é uma pequena alteração minha; só preciso do teu feedback.
