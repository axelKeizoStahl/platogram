#!/bin/bash

set -e

URL="$1"
LANG="en"
INLINE_REFERENCES="false"
MODEL="fireworks/llama 3.1405B"

while [[ $# -gt 0 ]]; do
    case $1 in
        --lang)
            LANG="$2"
            shift 2
            ;;
        --inline-references)
            INLINE_REFERENCES="true"
            shift
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

case "$LANG" in
  "en")
    CONTRIBUTORS_PROMPT="Thoroughly review the <context> and identify the list of contributors. Output as Markdown list: First Name, Last Name, Title, Organization. Output \"Unknown\" if the contributors are not known. In the end of the list always add \"- [Platogram](https://github.com/code-anyway/platogram), Chief of Stuff, Code Anyway, Inc.\". Start with \"## Contributors, Acknowledgements, Mentions\""
    CONTRIBUTORS_PREFILL=$'## Contributors, Acknowledgements, Mentions\n'

    INTRODUCTION_PROMPT="Thoroughly review the <context> and write \"Introduction\" chapter for the paper. Write in the style of the original <context>. Use only words from <context>. Use quotes from <context> when necessary. Make sure to include <markers>. Output as Markdown. Start with \"## Introduction\""
    INTRODUCTION_PREFILL=$'## Introduction\n'

    CONCLUSION_PROMPT="Thoroughly review the <context> and write \"Conclusion\" chapter for the paper. Write in the style of the original <context>. Use only words from <context>. Use quotes from <context> when necessary. Make sure to include <markers>. Output as Markdown. Start with \"## Conclusion\""
    CONCLUSION_PREFILL=$'## Conclusion\n'
    ;;
  "es")
    CONTRIBUTORS_PROMPT="Revise a fondo el <context> e identifique la lista de contribuyentes. Salida como lista Markdown: Nombre, Apellido, Título, Organización. Salida \"Desconocido\" si los contribuyentes no se conocen. Al final de la lista, agregue siempre \"- [Platogram](https://github.com/code-anyway/platogram), Chief of Stuff, Code Anyway, Inc.\". Comience con \"## Contribuyentes, Agradecimientos, Menciones\""
    CONTRIBUTORS_PREFILL=$'## Contribuyentes, Agradecimientos, Menciones\n'

    INTRODUCTION_PROMPT="Revise a fondo el <context> y escriba el capítulo \"Introducción\" para el artículo. Escriba en el estilo del original <context>. Use solo las palabras de <context>. Use comillas del original <context> cuando sea necesario. Asegúrese de incluir <markers>. Salida como Markdown. Comience con \"## Introducción\""
    INTRODUCTION_PREFILL=$'## Introducción\n'

    CONCLUSION_PROMPT="Revise a fondo el <context> y escriba el capítulo \"Conclusión\" para el artículo. Escriba en el estilo del original <context>. Use solo las palabras de <context>. Use comillas del original <context> cuando sea necesario. Asegúrese de incluir <markers>. Salida como Markdown. Comience con \"## Conclusión\""
    CONCLUSION_PREFILL=$'## Conclusión\n'
    ;;
  *)
    echo "Unsupported language: $LANG"
    exit 1
    ;;
esac

if { [[ -z "$FIREWORKS_API_KEY" && $MODEL == fireworks* ]] || [[ -z "$ANTHROPIC_API_KEY" && $MODEL == anthropic* ]] }; then
    echo "Your model's api key is not set, set either FIREWORKS_API_KEY or ANTHROPIC_API_KEY accordingly"
    echo "If you mean to use an anthropic model instead of a fireworks model, use the --model parameter followed by the model's name"
    echo "Obtain api keys by signing into https://www.anthropic.com/ or https://fireworks.ai/"
    echo "Then run: export FIREWORKS_API_KEY=<your-api-key>, or ANTHROPIC_API_KEY"
    exit 1
fi

echo "Indexing $URL..."
if [ -z "$ASSEMBLYAI_API_KEY" ]; then
    echo "ASSEMBLYAI_API_KEY is not set. Retrieving text from URL (subtitles, etc)."

    if [ -n "$1" = "--images" ]; then
        plato --images "$URL" --lang "$LANG" > /dev/null
    else
        plato "$URL" --lang "$LANG" > /dev/null
    fi
else
    echo "Transcribing audio to text using AssemblyAI..."

    if [ "$2" = "--images" ]; then
        plato --images "$URL" --assemblyai-api-key $ASSEMBLYAI_API_KEY --lang "$LANG" > /dev/null
    else
        plato "$URL" --assemblyai-api-key $ASSEMBLYAI_API_KEY --lang "$LANG" > /dev/null
    fi
fi

echo "Fetching title, abstract, passages, and references..."
TITLE=$(plato --model "$MODEL" --title "$URL" --lang "$LANG")
ABSTRACT=$(plato --model "$MODEL" --abstract "$URL" --lang "$LANG")
PASSAGES=$(plato --model "$MODEL" --passages --chapters --inline-references "$URL" --lang "$LANG")
echo "--------------------------PASSAGES------"
echo "$PASSAGES"
echo "--------------------------PASSAGES------"
REFERENCES=$(plato --model "$MODEL" --references "$URL" --lang "$LANG")
CHAPTERS=$(plato --model "$MODEL" --chapters "$URL" --lang "$LANG")

echo "Generating Contributors..."
CONTRIBUTORS=$(plato \
    --model "$MODEL" \
    --query "$CONTRIBUTORS_PROMPT" \
    --generate \
    --context-size large \
    --prefill "$CONTRIBUTORS_PREFILL" \
    "$URL" --lang "$LANG")

echo "Generating Introduction..."
INTRODUCTION=$(plato \
    --model "$MODEL" \
    --query "$INTRODUCTION_PROMPT" \
    --generate \
    --context-size large \
    --inline-references \
    --prefill "$INTRODUCTION_PREFILL" \
    "$URL" --lang "$LANG")

echo "Generating Conclusion..."
CONCLUSION=$(plato \
    --model "$MODEL" \
    --query "$CONCLUSION_PROMPT" \
    --generate \
    --context-size large \
    --inline-references \
    --prefill "$CONCLUSION_PREFILL" \
    "$URL" --lang "$LANG")

# Without References
echo "Generating Documents..."
(
    echo $'# '"$TITLE"$'\n'
    echo $'## Origin\n\n'"$URL"$'\n'
    echo $'## Abstract\n\n'"$ABSTRACT"$'\n'
    echo "$CONTRIBUTORS"$'\n'
    echo $'## Chapters\n\n'"$CHAPTERS"$'\n'
    echo "$INTRODUCTION"$'\n'
    echo $'## Discussion\n\n'"$PASSAGES"$'\n'
    echo "$CONCLUSION"$'\n'
) | \
    sed -E 's/\[\[([0-9]+)\]\]\([^)]+\)//g' | \
    sed -E 's/\[([0-9]+)\]//g' | \
    tee \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-no-refs.docx" --from markdown) \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-no-refs.pdf" --from markdown --pdf-engine=xelatex) \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-no-refs.md" --from markdown) > /dev/null

# With References
(
    echo $'# '"$TITLE"$'\n'
    echo $'## Origin\n\n'"$URL"$'\n'
    echo $'## Abstract\n\n'"$ABSTRACT"$'\n'
    echo "$CONTRIBUTORS"$'\n'
    echo $'## Chapters\n\n'"$CHAPTERS"$'\n'
    echo "$INTRODUCTION"$'\n'
    echo $'## Discussion\n\n'"$PASSAGES"$'\n'
    echo "$CONCLUSION"$'\n'
    echo $'## References\n\n'"$REFERENCES"$'\n'
) | \
    tee \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-refs.docx" --from markdown) \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-refs.pdf" --from markdown --pdf-engine=xelatex) \
    >(pandoc -o "$(echo "$TITLE" | sed 's/[^a-zA-Z0-9]/_/g')-refs.md" --from markdown) > /dev/null

wait
