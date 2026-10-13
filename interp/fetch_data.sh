#!/bin/sh
# NTREX-128 (CC-BY-SA-4.0, github.com/MicrosoftTranslator/NTREX): the same
# 1,997 news sentences in 128 languages, including regional variants.
set -e
cd "$(dirname "$0")/data"
for l in eng-US eng-GB eng-IN spa spa-MX por por-BR fra fra-CA deu ita rus zho-CN jpn arb hin kor tur vie swa; do
  [ -f "newstest2019-ref.$l.txt" ] || curl -sfL -o "newstest2019-ref.$l.txt" \
    "https://raw.githubusercontent.com/MicrosoftTranslator/NTREX/main/NTREX-128/newstest2019-ref.$l.txt"
done
ls | wc -l
