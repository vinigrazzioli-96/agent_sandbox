# Deep Sandbox Agent (produto pronto)

Interface web no navegador para:

1. Conversar com o agente (via Ollama/Gemma 3)
2. Executar tarefas de desenvolvimento dentro de **sandbox Daytona**
3. Ver o “produto final” no mesmo navegador via **Preview URL embutida** (iframe)
4. Opcionalmente observar a sandbox via VNC/Computer Use no Daytona

> Este projeto foi estruturado para um fluxo similar ao Kimi Computer/Manus: chat + execução em VM/sandbox + visualização do resultado.

---

## Arquitetura

- **Frontend web**: painel com chat, logs de comandos e iframe de preview.
- **Backend FastAPI**:
  - cria/encerra sandbox Daytona,
  - chama Ollama para transformar pedido em plano de comandos,
  - executa comandos na sandbox,
  - gera preview URL por porta para embutir no navegador.
- **Ollama**: modelo local (`gemma3`) para planejamento.
- **Daytona**: execução isolada + VNC/Computer Use.

---

## Pré-requisitos

- Python 3.10+
- Ollama rodando com `gemma3`
- Conta Daytona + API key + target configurado

---

## 1) Configurar ambiente

```bash
cp .env.example .env
```

Preencha `.env`:

- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `DAYTONA_API_KEY`
- `DAYTONA_SERVER_URL`
- `DAYTONA_TARGET`
- `DAYTONA_SANDBOX_IMAGE`

Instalar dependências:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2) Subir aplicação

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Abra:

- `http://localhost:8000`

---

## 3) Como usar (fluxo real)

1. Clique em **Iniciar sessão** (cria sandbox)
2. Escreva no chat um pedido, ex:
   - “Crie um app React simples com página de tarefas e rode em 3000”
3. O backend:
   - pede ao Ollama um plano em JSON,
   - executa comandos na sandbox,
   - tenta obter URL de preview da porta.
4. Se houver preview URL, o app carrega automaticamente no iframe (lado direito).

### Botões úteis

- **Gerar preview URL**: força geração de preview para a porta informada.
- **Usar URL manual**: caso você queira colar URL de VNC/preview manualmente.
- **Parar sessão**: encerra sandbox e limpa estado local.

---

## 4) Configuração Daytona UI (passo a passo)

No painel Daytona:

1. Gere API key com escopo de sandbox lifecycle.
2. Valide `target` e organização corretos.
3. Use imagem default para facilitar VNC/Computer Use.
4. Se usar imagem custom, inclua stack VNC (x11vnc/novnc/xfce).
5. Valide que o sandbox consegue abrir portas do app (ex.: 3000).

---

## 5) VNC / Computer Use

Este projeto inicia VNC de forma programática quando disponível no SDK.

- Se a imagem suportar `computer_use`, o backend chama `sandbox.computer_use.start()`.
- Você pode observar manualmente pelo Daytona Dashboard (ação VNC).
- A visualização “produto final” no app é feita via iframe da preview URL.

---

## 6) Segurança

- Não coloque segredos dentro da sandbox quando não for necessário.
- Prefira chaves no backend/host.
- Trate todo output de sandbox como não confiável até validação.

---

## 7) Estrutura do projeto

```text
app/main.py        # API FastAPI + orquestração sandbox/ollama
web/index.html     # UI de chat + preview
web/app.js         # chamadas API e render de mensagens
web/styles.css     # estilo
.env.example       # variáveis obrigatórias
requirements.txt   # dependências
```

---

## 8) Troubleshooting

### Erro ao iniciar sessão
- confira `DAYTONA_API_KEY`, `DAYTONA_SERVER_URL`, `DAYTONA_TARGET`
- confirme que a conta/target está ativo

### Erro no Ollama
- confirme `OLLAMA_BASE_URL`
- rode `ollama list` e valide `gemma3`

### Preview não aparece
- confirme que app realmente subiu na porta escolhida (3000 por padrão)
- clique em **Gerar preview URL**
- se necessário, use **URL manual** com preview do Daytona

---

## 9) Próximo upgrade opcional

- streaming de tokens/respostas via WebSocket
- fila assíncrona de jobs
- persistência de histórico em banco
- política de comandos permitidos (allowlist)
