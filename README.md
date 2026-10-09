# SeuComércioAqui

Cardápio digital e gestão de pedidos para pequenos comércios. Frontend responsivo e backend real, com identidade própria em verde-petróleo e lima.

## O que funciona

- Cadastro de lojistas: cada conta tem uma loja e seus próprios dados.
- Cardápio por link, com fotos, categorias, busca e destaques.
- Sacola, complementos, observações, entrega ou retirada e cupom.
- Total calculado no servidor, estoque reservado em transação e proteção contra pedidos duplicados.
- Acompanhamento por link aleatório, sem expor telefone ou endereço do cliente.
- Painel: novos, em preparo, prontos, em entrega, concluídos e cancelados.
- Produtos, upload de fotos, estoque, categorias e cupons.
- Entregadores e atribuição de pedidos.
- Vendas por período, pagamentos confirmados, despesas e exportação CSV.
- Nome, logo, capa, cor, contato, taxa, pedido mínimo e pagamentos configuráveis.
- Alteração de senha, logout e recuperação administrativa por comando.

**Pagamentos:** Pix é confirmado manualmente pelo lojista. Dinheiro e cartão são recebidos na entrega ou retirada. Não há gateway bancário, captura de cartão ou confirmação automática de Pix. O link do WhatsApp abre uma conversa com a loja; não envia mensagens automaticamente.

## Rodar no computador

Requisitos: Python 3.12 ou superior. Frontend e backend usam o mesmo endereço. Node/npm não são necessários para funcionar.

~~~powershell
git clone https://github.com/Nexusconchal/SeuCom-rcioAqui.git
cd SeuCom-rcioAqui
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
~~~

Abra **http://localhost:8000** e clique em **Criar minha loja**.

1. Cadastre a loja e a conta.
2. Abra Configurações: informe contato, endereço e pagamentos.
3. Cadastre produtos, preços e fotos.
4. Abra a loja pelo botão **Loja fechada**.
5. Copie o link e faça um pedido de teste.

A loja nasce fechada e sem produtos. Nenhuma conta ou senha padrão é instalada. Se usar Pix, informe a chave verdadeira da loja. Estoque vazio significa sem controle de quantidades. Remover categorias move seus produtos para Outros. Produtos são pausados, preservando o histórico.

No Linux/macOS, use .venv/bin/python no lugar de .venv\Scripts\python.exe.

## Demonstração opcional

~~~powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-demo
~~~

O comando pede seu e-mail e senha (mínimo 10 caracteres). Cria **Bistrô da Vila**, fotos e pedidos de exemplo. Visite **/loja/bistro-da-vila** e entre em **/entrar** com a conta criada.

**Dados fictícios: a chave Pix da demo não deve ser usada para pagamento.** A demo não é instalada automaticamente em produção. Fotos externas do Unsplash podem ser substituídas por fotos próprias. Uma ilustração local aparece se a imagem não carregar.

## Hospedar

O GitHub contém o código, não um servidor publicado. Use hospedagem Python/Gunicorn ou Docker com **disco persistente**. GitHub Pages e hospedagem exclusivamente estática não executam o backend.

| Variável | Produção |
| --- | --- |
| APP_ENV | production |
| SECRET_KEY | Chave aleatória com pelo menos 32 caracteres |
| PUBLIC_URL | URL HTTPS final sem barra no fim |
| TRUSTED_HOSTS | Hosts permitidos, separados por vírgula, sem https:// |
| DATABASE_PATH | Caminho do SQLite no disco persistente |
| UPLOAD_DIR | Diretório das fotos no disco persistente |
| TRUST_PROXY | 1 apenas atrás de um proxy confiável; 0 nos demais casos |
| ALLOW_REGISTRATION | 1 para permitir novas lojas; 0 para fechar cadastros |
| PORT | Porta da hospedagem, padrão 8000 |

Gere a chave:

~~~powershell
python -c "import secrets; print(secrets.token_hex(32))"
~~~

Não coloque segredos no código/GitHub. .env.example documenta os valores; a aplicação lê variáveis de ambiente. No Windows use $env:NOME="valor"; no Linux, export NOME="valor". Em desenvolvimento, sem SECRET_KEY, uma chave temporária é criada e as sessões expiram ao reiniciar.

Comando de produção (Linux):

~~~sh
gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 60 --access-logfile -
~~~

Esta configuração usa uma instância com SQLite em WAL. Para várias réplicas, migre para PostgreSQL e armazenamento compartilhado de fotos. Não coloque SQLite em filesystem de rede e não use disco efêmero para dados de produção.

### Docker

~~~sh
docker build -t seucomercio-aqui .
docker run --rm -p 8000:8000 \
  -e SECRET_KEY=SUA_CHAVE_ALEATORIA_LONGA \
  -v commerce-data:/data seucomercio-aqui
~~~

Para Docker Compose local, copie .env.example para .env, preencha SECRET_KEY e rode:

~~~sh
docker compose up --build
~~~

O Compose usa HTTP e APP_ENV=development no computador local. Em produção, configure HTTPS, APP_ENV=production, URL final e hosts permitidos. /health verifica serviço e banco.

### Backup e recuperação

Faça backup do banco e das fotos. Com o sistema em uso, use a API de backup do SQLite, não copie apenas o arquivo .sqlite3 enquanto houver escrita/WAL:

~~~sh
python scripts/backup.py /data/seucomercio.sqlite3 /backups/loja.sqlite3
~~~

Guarde a cópia fora do servidor junto com as fotos. Não versione bancos, backups, dados de clientes ou segredos.

Recuperação de senha pelo administrador no servidor:

~~~sh
python -m flask --app app:create_app reset-password --email pessoa@exemplo.com
~~~

O comando pede uma senha nova e invalida sessões anteriores. Recuperação e verificação por e-mail exigem integrar um serviço de envio.

## Testes

~~~sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -v
~~~

Para testar só a API, sem Chromium:

~~~sh
python -m pytest tests/test_api.py -v
~~~

GitHub Actions verifica sintaxe, API e compra/gestão em Chromium. Cobre isolamento entre lojas, preços, estoque concorrente, CSRF, uploads, cupons e fluxo de pedidos. As capturas aparecem no pacote **telas-seucomercio** no resultado da execução.

## Estrutura

~~~text
app.py                    Flask: API, páginas e regras de negócio
schema.sql                Banco SQLite
seed.py                   Demonstração opcional
static/
  index.html              Entrada da aplicação
  app.js                  Página inicial e acesso
  menu.js                 Cardápio, checkout e acompanhamento
  dashboard.js            Painel do lojista
  ui.js                   Componentes e cliente HTTP
  styles.css              Desktop, celular e impressão
  logo.svg                Marca original
tests/                    Testes da API e do navegador
scripts/backup.py         Backup consistente
Dockerfile                Servidor de produção
docker-compose.yml        Ambiente local persistente
docs/API.md               Endpoints e exemplos
~~~

## Escopo

Esta versão cobre cardápio, pedidos e gestão. Não integra emissão fiscal, impressoras via drivers, WhatsApp automático, apps de delivery ou conciliação bancária. A impressão usa o navegador.

As sessões são assinadas; senhas usam scrypt; alterações exigem CSRF; preços e estoque são validados pelo servidor; uploads são reprocessados; o painel limita os dados à loja autenticada. O link do pedido mostra itens, valores e status. Os relatórios usam a data de criação do pedido e excluem cancelados. Cancelamentos não executam reembolsos bancários.

Referências: [segurança no Flask](https://flask.palletsprojects.com/en/stable/web-security/), [uploads](https://flask.palletsprojects.com/en/stable/patterns/fileuploads/), [SQLite](https://docs.python.org/3/library/sqlite3.html).
