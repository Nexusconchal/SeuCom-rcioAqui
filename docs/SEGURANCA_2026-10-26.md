# Auditoria de segurança — 26/10/2026

Escopo: código Python, frontend JavaScript, upload remoto, autenticação e autorização de lojistas/equipe/parceiros, pedidos, mensalidades, Pix/cartão, cashback/fidelidade, mídia, notificações, dependências e configuração pública da implantação Render/Supabase. Referência anterior à correção: `79c0f60792b8f45e3161fb234d16144c30941744`.

Esta é uma revisão técnica com reprodução controlada, testes automatizados e consultas de leitura na produção. Não é certificação, garantia de ausência de vulnerabilidades nem análise forense de incidentes. Não foram feitos testes de carga hostis, cobranças, estornos reais ou envio de mensagens a clientes.

## Correções

| Achado | Risco e evidência | Correção |
|---|---|---|
| Destino arbitrário de Web Push | Usuário autenticado podia cadastrar URLs HTTPS fora dos serviços de push; entradas sintéticas de loopback/rede privada eram aceitas. Isso permitia requisições originadas pelo servidor. | Lista explícita de serviços de navegadores, HTTPS/porta/credenciais/fragmento validados, chave EC validada, limite por usuário e nova validação antes do envio. Sem seguir redirecionamentos. |
| Dados de mensalidade na resposta pública | `sub_pix_id`, `sub_pix_code`, `sub_pix_expires` e `subscribed_at` apareciam como campos do cardápio público. A observação de produção coletou somente os nomes dos campos. Não demonstrava acesso a números de cartão ou tokens Mercado Pago. | Lista explícita de campos públicos, aplicada ao cardápio e ao acompanhamento. Colunas internas futuras ficam privadas por padrão. |
| Cookie reaproveitado depois de sair | Cópia sintética da sessão ainda acessava a loja depois de logout. A exploração pressupõe que alguém já tenha obtido o cookie. | Revogação persistente por sessão, usando somente hash e vencimento. Revoga a cópia sem desconectar outros dispositivos. A versão global continua invalidando sessões na troca/recuperação de senha. |
| Fidelidade por telefone não confirmado | Na versão anterior, dados sintéticos de duas compras permitiam a outro navegador consultar o histórico de fidelidade e obter R$ 7 de desconto informando apenas o telefone. | No checkout público, histórico/resgate exigem código no WhatsApp, reaproveitando a autenticação de cashback. Apenas compras concluídas e pagas acumulam fidelidade. O acompanhamento não revela o histórico do telefone digitado. No balcão, a equipe autorizada pode aplicar a recompensa. |
| Redirecionamento em conectores/upload | Receptor HTTP controlado demonstrou que o conector seguia redirecionamento com credencial. Upload também usava o comportamento padrão de redirecionamento. | Conectores e upload bloqueiam redirects e limitam o tamanho das respostas. Provedores devem estar configurados em sua URL final. |
| Cozinha podia avançar para entrega/conclusão | A filtragem removia alterações financeiras, mas aceitava etapas posteriores ao preparo. | Perfil Cozinha só pode avançar para em preparo/pronto. Caixa, gerente e dono mantêm as ações de sua função. |
| URLs privadas nos logs de acesso | O formato padrão do Gunicorn inclui a URL real e o Referer, que podem conter link de pedido, chave de webhook, telefone e convite. | Novos logs registram o modelo da rota, sem parâmetros/query/Referer. Logs históricos não são apagados nem reescritos. |
| Tentativas de senha atual | Mudança de senha exigia senha atual, mas não tinha limite próprio. | Limite persistente por conta; teste comprova bloqueio após dez erros. |

Proteção adicional: `object-src 'none'` na CSP. A migração cria somente `revoked_sessions` e seu índice; não modifica dados comerciais. Na inicialização PostgreSQL, a nova tabela recebe RLS e revogação de acesso público como as demais tabelas privadas.

A conexão da aplicação com PostgreSQL passa a exigir `sslmode=require` por padrão em produção; `verify-ca`/`verify-full` podem ser configurados com a cadeia de confiança adequada. Modos de conexão em texto claro são rejeitados em produção. A observação de `pg_stat_ssl` mostrou uma conexão do pooler Supavisor com o banco, e não identifica diretamente o trecho Render → pooler; por isso não foi usada para afirmar que o tráfego externo anterior estava em texto claro. Testes conferem que a exigência TLS alcança tanto conexões de operação quanto inicialização/migração.

A sessão não é renovada automaticamente por cada leitura. A revogação é conferida nas páginas públicas e APIs; arquivos estáticos não reemitem o cookie. Isso impede prolongar uma cópia revogada por acessos a páginas/arquivos até o vencimento do registro de revogação.

## Configuração verificada por leitura

- Antes da alteração: 55 tabelas privadas, 55 com RLS, zero com privilégios de leitura/escrita para `anon` ou `authenticated`. A aplicação usa autenticação própria e aplica o isolamento no backend; RLS sem políticas públicas é intencional nessa arquitetura.
- Bucket público `commerce-photos`: somente fotos WebP; limite de 8 MiB. Nenhuma política de escrita pública em Storage foi retornada. Mídia de conversas fica na área privada do backend, não nesse bucket.
- `/api/admin/orders` e `/api/platform/summary` rejeitaram acesso anônimo com 401. Cookie da sessão pública com Secure, HttpOnly e SameSite=Lax. CSP, HSTS e `nosniff` presentes; APIs com `no-store`.
- Não foram lidos valores de variáveis secretas, pedidos ou mensagens reais para a auditoria.

## Verificação

- Regressões adversariais para destinos push, credenciais em redirects, logout/cookie copiado, anonimato em todas as rotas de administração/plataforma, fidelidade, senha e logs.
- Navegador Chromium: compra móvel, gestão e confirmação de recompensa por código; alterar o telefone remove a confirmação e o desconto. O WhatsApp é um provedor simulado, sem mensagem real.
- `pip-audit`: nenhuma vulnerabilidade conhecida nos requisitos de produção na consulta de 26/10/2026. Isso não significa que vulnerabilidades desconhecidas não existam.
- Bandit: 44 arquivos Python de aplicação/scripts analisados, 7.980 linhas na primeira execução finalizada; zero alertas de gravidade alta. Os 29 avisos médios/baixos foram revisados: composição de SQL usa nomes/expressões constantes e placeholders para valores; subprocesso de backup não usa shell; ferramentas de smoke/carga são operacionais, sem endpoint HTTP que execute seus argumentos. Não foram classificados automaticamente como SQL injection confirmado. O CI passa a bloquear novos alertas de alta gravidade; alertas de outros níveis continuam exigindo revisão.
- Busca por padrões de segredos: 164 arquivos de texto rastreados, sem ocorrência nos formatos inspecionados. É uma busca limitada por padrões, não uma garantia sobre todo formato de credencial ou histórico Git.
- A suíte existente cobre adulteração de preço, moeda, recebedor e referência de pagamentos, retorno falso de checkout, replay/idempotência, estornos, concorrência de estoque, acesso entre lojas, CSRF, tokens de recuperação, mídia e upload.
- Inventário: 227 rotas HTTP, 44 arquivos Python de aplicação/scripts, 29 JavaScript e 3 TypeScript. O CI foi fixado em Ubuntu 24.04 após o runner `ubuntu-latest` mudar para uma imagem incompatível com o Playwright fixado; a falha ocorreu na instalação do navegador, antes de executar a suíte.

## Limites e próximos controles

1. Ativar e-mail transacional para recuperação de acesso. O serviço ainda não foi contratado/configurado; não há promessa de envio.
2. MFA para dono da plataforma e lojistas ainda não foi implementado. Usar senha exclusiva/gerenciador e MFA nas contas GitHub, Render, Supabase e Mercado Pago; o estado desses fatores externos não foi auditado.
3. Proteção volumétrica de DDoS, WAF/controle na borda, capacidade sob pico e resposta humana a alertas exigem operação de infraestrutura. Limites no aplicativo não substituem esses controles.
4. Homologar pagamentos, WhatsApp e impressão física em piloto real. Teste simulado não prova liquidação, entrega de mensagem ou papel impresso.
5. Validar restauração completa de produção, incluindo mídia e preservação segura da chave de criptografia. O teste de restore existente usa uma base de teste isolada.
6. Restringir acesso/retenção dos logs antigos no provedor: o novo formato protege requisições futuras. Não foi feita investigação histórica de invasão nem rotação cega de credenciais, que poderia interromper integrações.
7. A verificação do e-mail no cadastro não está ativa; o cadastro exige termos e limites por IP, mas não comprova identidade civil ou legitimidade comercial. Revisão operacional de lojas e prevenção de chargebacks continuam necessárias. Nunca tratar comprovante enviado no WhatsApp como confirmação automática de Pix: a confirmação online vem da consulta ao provedor.

Referências: [Flask — segurança web](https://flask.palletsprojects.com/en/stable/web-security/), [OWASP — autorização](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [OWASP — SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html), [OWASP — autorização de transações](https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html), [Supabase — configuração de segurança](https://supabase.com/docs/guides/security/product-security).
