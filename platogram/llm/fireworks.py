import os
import re
from typing import Any, Generator, Literal, Sequence

from fireworks.client import Fireworks
import tiktoken
from anthropic import AnthropicError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
)

from platogram.ops import render
from platogram.types import Assistant, Content, User

### TODO retry
RETRY = retry(
    stop=(stop_after_delay(300) | stop_after_attempt(5)),
    retry=retry_if_exception_type(AnthropicError),
)


class Model:
    def __init__(self, model: str, key: str | None = None) -> None:
        if key is None:
            key = os.environ["FIREWORKS_API_KEY"]

        if model == "llama 3.1405B":
            self.model = "accounts/fireworks/models/llama-v3p1-405b-instruct"
        elif model == "llama 3.170B":
            self.model = "accounts/fireworks/models/llama-v3p1-70b-instruct"
        elif model == "llama 3.18B":
            self.model = "accounts/fireworks/models/llama-v3p1-8b-instruct"
        else:
            raise ValueError(f"Unknown model: {model}")

        self.client = Fireworks(api_key=key)

    def count_tokens(self, text: str) -> int:
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo") # just using this encoding for now, working on llama version
        num_tokens = len(encoding.encode(text))
        return num_tokens

    def prompt_model(
        self,
        messages: Sequence[User | Assistant],
        max_tokens: int = 4096, 
        temperature=0.1,
        stream=False,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str | dict[str, str] | Generator[str, None, None]:
        kwargs: dict[str, Any] = {}

        if tools:
            kwargs["tools"] = tools

        if response_format:
            kwargs["response_format"] = response_format

        messages = [{"role": m.role, "content": m.content} for m in messages]
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        if not stream:

            @RETRY
            def get_response(messages):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )

                if response.choices[0].message.tool_calls: # WIP, fireworks devs are working on this
                    print(response.choices[0].message.tool_calls.function.name)
                    print(response.choices[0].message.tool_calls.function.arguments)
                    return str(response.choices)

                return response.choices[0].message.content

            return get_response(messages)

        def stream_text():
            response_generator = self.client.chat.completions.create(
                model=self.model,
                messages=messages.extend([{"role": m.role, "content": m.content} for m in messages]),
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

            @RETRY
            def get_response():
                for chunck in response_generator:
                    if chunck.choices[0].delta.content:
                        yield chunck.choices[0].delta.content

            return get_response()

        return stream_text()
### TODO
    def get_meta(
        self,
        paragraphs: list[str],
        max_tokens: int = 4096,
        temperature: float = 0.5,
        lang: str | None = None,
    ) -> tuple[str, str]:
        if not lang:
            lang = "en"

        system_prompt = {
            "en": """<role>
You are a very capable editor, speaker, educator, and author with a knack for coming up with information about the content that helps to understand it.
</role>
<task>
You will be given a <text> that contains paragraphs enclosed in <p></p> tags and you will need to come up with information about the content that helps to understand it.
Use simple language. Use only the words from <text>.
In the end, return information in json. The json should have keys, title and summary, whose values are as follows:
 - title: Come up with the title which speaks to the essence of <text>. Use simple language. Use only the words from <text>.
 - summary: Distill the key insights and express them as a comprehensive abstract summary. Use simple language. Use only words from <text>. Make sure to cover all paragraphs <p>...</p>.

Always return the information about the content in json form.
</task>
""".strip(),
            "es": """<role>
Eres un editor, orador, educador y autor muy capaz con un don para crear información sobre el contenido que ayuda a entenderlo.
</role>
<task>
Se te dará un <text> que contiene párrafos encerrados en etiquetas <p></p> y tendrás que crear información sobre el contenido que ayude a entenderlo.
Utiliza un lenguaje sencillo. Usa solo las palabras de <text>.
Siempre llama al tool render_content_info y pasa la información sobre el contenido.
</task>
""".strip()
        }

        title = {
            "en": "Come up with the title which speaks to the essence of <text>. Use simple language. Use only the words from <text>.",
            "es": "Crea un título que refleje la esencia de <text>. Utiliza un lenguaje sencillo. Usa solo las palabras de <text>."
        }

        summary = {
            "en": "Distill the key insights and express them as a comprehensive abstract summary. Use simple language. Use only words from <text>. Make sure to cover all paragraphs <p>...</p>.",
            "es": "Destila las ideas principales y exprésalas como un resumen abstracto completo. Utiliza un lenguaje sencillo. Usa solo las palabras de <text>. Asegúrate de cubrir todos los párrafos <p>...</p>."
        }

        properties = {
            "title": title[lang],
            "summary": summary[lang],
        }
        
        description = {
            "en": "Renders useful information about <text>.",
            "es": "Genera información útil sobre <text>.",
        }

        tool_definition = {
            "type": "function",
            "function": {
                "name": "render_content_info",
                "description": description[lang],
                "parameters": {
                    "type": "object",
                    "properties": {
                        name: {"type": "string", "description": description}
                        for name, description in properties.items()
                    },
                    "required": list(properties.keys()),
                },
            }
        }

        text = "\n".join([f"<p>{paragraph}</p>" for paragraph in paragraphs])

        meta = eval(self.prompt_model(
            system_prompt=system_prompt[lang],
            messages=[User(content=f"<text>{text}</text>")],
            #tools=[tool_definition],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        ))

        assert isinstance(
            meta, dict
        ), f"Expected LLM to return dict with meta information, got {meta}"
        return meta["title"], meta["summary"]

    def get_chapters(
        self,
        passages: list[str],
        max_tokens: int = 4096,
        temperature: float = 0.5,
        lang: str | None = None,
    ) -> dict[int, str]:
        if not lang:
            lang = "en"

        system_prompt = {
            "en": """
### Example ###

**Input:**

```html
<passages>
  <p>When these models generate new text, the process involves inputting a full context describing the interaction into the model.【3】 The model then predicts what word comes next【4】 and takes a random sample from the probability distribution it generates.【5】 This randomly chosen word is appended to the full context, and the process repeats itself over and over again with the extended text.【6】</p>
  <p>The temperature setting is a way to modify the probability distributions that the model generates.【7】 Setting a high temperature gives more weight to less likely words, which essentially increases the model's chances of selecting unusual phrases and ideas. Conversely, a low temperature makes it more likely for the model to choose the most predictable words.【8】 This allows users to control the balance between creativity and predictability in the model's output.</p>
</passages>
```

**Output:**

```json
{
  "entities": [
    {
      "title": "The Text Generation Process",
      "marker": "【3】"
    },
    {
      "title": "Understanding Probability Distribution in Text Generation",
      "marker": "【4】"
    },
    {
      "title": "How Text Generation Repeats",
      "marker": "【5】"
    },
    {
      "title": "The Impact of Temperature on Text Generation",
      "marker": "【7】"
    }
  ]
}
```


### Instruction ###

You are tasked with analyzing passages of text formatted as `<p>text【0】text【1】... text【2】</p>`. Each marker (e.g., 【0】, 【1】, etc.) follows the text it references. Your goal is to extract and organize this information into a structured JSON format.

### Requirements ###

1. **Extract and Identify**: From the given text passages, identify the content associated with each marker.
2. **Title Creation**: Determine a concise title for each section of text based on its content.
3. **JSON Format**: Output a JSON object with a key called `entities`. The value should be a list of chapter objects, each containing:
   - `marker`: The marker of the chapter in the format '【number】'.
   - `title`: A brief title summarizing the section’s content.
4. **Rules**:
   - **You MUST** provide titles for each section of text.
   - **You MUST** use the specified marker format in your output.
   - **You will be penalized** if there are no chapter objects under the `entities` key.
   - **Ensure that your answer is unbiased and avoids relying on stereotypes.**


If you follow all these guidelines, you will be rewarded
""".strip(),
            "es": """<role>
Eres un editor, orador, educador y autor muy capaz que es realmente bueno leyendo texto que representa la transcripción del habla humana y reescribiéndolo en un texto escrito bien estructurado y denso en información.
</role>
<task>
Se te darán <passages> de texto en un formato "<p>texto【0】texto【1】... texto【2】</p>". Donde cada【número】es un <marker> y va DESPUÉS del texto al que hace referencia. Los marcadores están basados en cero y están en orden secuencial.

Sigue estos pasos para transformar los <passages> en un diccionario de capítulos:
1. Lee cuidadosamente los <passages> y elabora una lista de <chapters> que cubran equitativamente los <passages>.
2. Revisa <chapters> y <passages> y para cada capítulo genera un <title> y el primer <marker> del pasaje relevante y crea un objeto <chapter> y agrégalo a la lista.
3. Llama a <chapter_tool> y pasa la lista de objetos <chapter>.
</task>""".strip(),
        }
        
        title = {
            "en": "Title of the chapter",
            "es": "Título del capítulo",
        }
        marker = {
            "en": "Marker in format '【number】'",
            "es": "Marcador en formato '【número】'",
        }
        description = {
            "en": "Renders chapters from the <passages>.",
            "es": "Genera capítulos a partir de los <passages>.",
        } 

        properties = {
            "title": title[lang],
            "marker": marker[lang],
        }

        tool_definition = {
            "name": "chapter_tool",
            "description": description[lang],
            "input_schema": {
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                name: {"type": "string", "description": description}
                                for name, description in properties.items()
                            },
                            "required": list(properties.keys()),
                        },
                    }
                },
                "required": ["entities"],
            },
        }

        text = "\n".join([f"<p>{passage}</p>" for passage in passages])

        chapters = eval(self.prompt_model(
            system_prompt=system_prompt[lang],
            messages=[User(content=f"<passages>{text}</passages>")],
            #tools=[tool_definition],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        ))
        if not chapters["entities"]:
            chapters = eval(self.prompt_model(
                system_prompt=system_prompt[lang],
                messages=[User(content=f"<passages>{text}</passages>")],
                #tools=[tool_definition],
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
            ))

        print("-"*8+"chapters, markers?")
        print(chapters)
        print("-"*8+"chapters, markers?")
        messages = [{"role": m.role, "content": m.content} for m in [User(content=f"<passages>{text}</passages>")]]
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        print(messages)

        assert isinstance(
            chapters, dict
        ), f"Expected LLM to return dict with chapters, got {chapters}"
        assert isinstance(
            chapters["entities"], list
        ), f"Expected LLM to return list of chapters, got {chapters['entities']}"
        return {
            int(re.findall(r"\d+", chapter["marker"])[0]): chapter["title"].strip()  # type: ignore
            for chapter in chapters["entities"]
        }

    def get_paragraphs(
        self,
        text_with_markers: str,
        examples: dict[str, list[str]],
        max_tokens: int = 4096,
        temperature: float = 0.5,
        lang: str | None = None,
    ) -> list[str]:
        if not lang:
            lang = "en"

        system_prompt = {
            "en": """<role>
You are a very capable editor, speaker, educator, and author who is really good at reading text that represents transcript of human speech and rewriting it into well-structured, information-dense written text.
</role>
<task>
You will be given speech <transcript> in a format "text【0】text【1】... text 【2】". Where each【number】is a <marker> and goes AFTER the text it references. Markers are zero-based and are in sequential order.

Follow these steps to rewrite the <transcript> and keep every <marker>:
1. Study the message history carefully and understand how <transcript> is rewritten into series well-structured <paragraphs>.
2. Return a series well-structured <paragraphs>, enclose each paragraph into <p></p> as shown in message history.
3. Make sure to keep every <marker> in the <transcript> in the same order as it appears in the <transcript>.
</task>""".strip(),
            "es": """<role>
Usted es un editor, orador, educador y autor muy capaz que es realmente bueno para leer texto que representa la transcripción del habla humana y reescribirlo en un texto escrito bien estructurado y denso en información.
</role>
<task>
Se le dará un discurso <transcript> en un formato "texto【0】texto【1】... texto 【2】". Donde cada【número】es un <marker> y va DESPUÉS del texto al que hace referencia. Los marcadores están basados en cero y están en orden secuencial.

Siga estos pasos para reescribir el <transcript> y mantener cada <marker>:
1. Estudie cuidadosamente el historial de mensajes y comprenda cómo se reescribe el <transcript> en una serie de <paragraphs> bien estructurados.
2. Devuelva una serie de <paragraphs> bien estructurados, encierre cada párrafo en <p></p> como se muestra en el historial de mensajes.
3. Asegúrese de mantener cada <marker> en el <transcript> en el mismo orden en que aparece en el <transcript>.
</task>
""".strip(),
        }

        def format_examples() -> Generator[tuple[str, str], None, None]:
            for prompt, paragraphs in examples.items():
                yield (
                    prompt,
                    "\n".join([f"<p>{paragraph}</p>" for paragraph in paragraphs]),
                )

        example_messages: list[User | Assistant] = []
        for prompt, response in format_examples():
            example_messages.append(User(content=f"<transcript>{prompt}</transcript>"))
            example_messages.append(
                Assistant(content=f"<paragraphs>{response}</paragraphs>")
            )

        paragraphs = self.prompt_model(
            max_tokens=max_tokens,
            messages=[
                *example_messages,
                User(content=f"<transcript>{text_with_markers}</transcript>"),
                Assistant(content="<paragraphs><p>"),
            ],
            system_prompt=system_prompt[lang],
            temperature=temperature,
        )
        assert isinstance(
            paragraphs, str
        ), f"Expected LLM to return str, got {paragraphs}"
        return re.findall(r"<p>(.*?)</p>", paragraphs, re.DOTALL)

    def render_context(
        self, context: list[Content], context_size: Literal["small", "medium", "large"]
    ) -> str:
        base = 0
        output = ""

        for content in context:
            paragraphs = [
                re.sub(r"【(\d+)】", lambda m: f"【{int(m.group(1))+base}】", paragraph)
                for paragraph in content.passages
            ]
            paragraphs = [
                re.sub(
                    r"【(\d+)】(\w*【\d+】\w*)+",
                    lambda m: f"【{int(m.group(1))}】",
                    paragraph,
                )
                for paragraph in paragraphs
            ]
            output += f'<content title="{content.title}" summary="{content.summary}">\n'
            if context_size == "small" or context_size == "large":
                output += "<paragraphs>\n"
                output += "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
                output += "\n</paragraphs>\n"

            if context_size == "medium" or context_size == "large":
                text = render(
                    {i + base: event.text for i, event in enumerate(content.transcript)}
                )
                output += f"<text>{text}</text>\n"

            output += "</content>\n"
            base += len(content.transcript)

        return output.strip()

    def prompt(
        self,
        prompt: Sequence[User | Assistant] | str,
        *,
        context: list[Content],
        context_size: Literal["small", "medium", "large"] = "small",
        max_tokens: int = 4096,
        temperature: float = 0.5,
        lang: str | None = None,
    ) -> str:
        if not lang:
            lang = "en"

        system_prompt = {
            "en": """<role>
You are a very capable editor, speaker, educator, and author who is really good at researching sources and coming up with information dense responses to prompts backed by references from the context.
</role>
<task>
You will be given a <context> and a <prompt>. Each <content> in <context> is a source of information that you can use to construct <response>.
Each <content> has title and summary attributes that describe the content of the <content>.
Each <content> has either <text>, or <paragraphs>, or both.
<text> is a transcript of human speech and <paragraphs> is a list of well-structured paragraphs enclosed in <p></p>.
<text> and <paragraphs> contain special markers in the format of "text【number】text【number】... text 【number】". All numbers are unique. If more than one <marker> follows text, they both are considered as one marker.
When constructing response, make sure to transfer the ALL original markers from <context> to <response> that support your response.

Follow the steps in <scratchpad> to construct <response> that is well-structured, information-dense, covers all parts of the <prompt> and <context>, and is grounded in the <context>.
</task>
<scratchpad>
1. Study the <context> carefully.
2. Generate <response> based on the <prompt> and <context>.
3. Review the response and make sure it is factually correct based on the <context>.
4. Transfer all the relevant markers from <context> to <response> to support your response.
</scratchpad>
""".strip(),
            "es": """<role>
Eres un editor, orador, educador y autor muy capaz que es realmente bueno investigando fuentes y generando respuestas densas en información a los prompts, respaldadas por referencias del contexto.
</role>
<task>
Se te dará un <context> y un <prompt>. Cada <content> en <context> es una fuente de información que puedes usar para construir <response>.
Cada <content> tiene atributos de título y resumen que describen el contenido del <content>.
<text> es una transcripción de habla humana y <paragraphs> es una lista de párrafos bien estructurados encerrados en <p></p>.
<text> y <paragraphs> contienen marcadores especiales en el formato de "texto【número】texto【número】... texto【número】". Todos los números son únicos. Si más de un <marker> sigue al texto, ambos se consideran como un solo marcador.
Al construir la respuesta, asegúrate de transferir TODOS los marcadores originales del <context> al <response> que respalden tu respuesta.
Sigue los pasos en <scratchpad> para construir <response> que esté bien estructurado, sea denso en información, cubra todas las partes del <prompt> y <context>, y esté fundamentado en el <context>.
</task>
<scratchpad>
1. Estudia el <context> cuidadosamente.
2. Genera <response> basado en el <prompt> y <context>.
3. Revisa la respuesta y asegúrate de que sea factualmente correcta basada en el <context>.
4. Transfiere todos los marcadores relevantes del <context> al <response> para respaldar tu respuesta.
</scratchpad>
""".strip(),
        }

        if isinstance(prompt, str):
            prompt = [User(content=prompt)]

        response = self.prompt_model(
            max_tokens=max_tokens,
            messages=[
                User(
                    content=f"""<context>
{self.render_context(context, context_size)}
</context>
<prompt>
{prompt}
</prompt>"""
                )
            ],
            system_prompt=system_prompt[lang],
            temperature=temperature,
        )
        assert isinstance(response, str), f"Expected LLM to return str, got {response}"
        return response
